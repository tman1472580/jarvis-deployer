#!/usr/bin/env python3
"""
Claude Code Tmux Monitor
-------------------------
Real-time dashboard for Claude Code sessions running in tmux.
Reads token usage from Claude Code's JSONL conversation files.
Double-click any row to jump to that session.

Usage:
    python3 claude_monitor.py
"""

from collections import OrderedDict
from datetime import datetime, timedelta
import glob
import json
import os
import pathlib
import queue
import re
import sqlite3
import subprocess
import sys
import threading
import time

try:
    import tkinter as tk
    from tkinter import ttk
except ImportError:
    v = sys.version_info
    print("tkinter not found. Install with:")
    print(f"  brew install python-tk@{v.major}.{v.minor}")
    sys.exit(1)

# ── Config ───────────────────────────────────────────────────────────────
REFRESH_MS = 3000
CONTEXT_WINDOW = 200_000
# Claude sessions can run with the extended window. Transcripts don't record
# which one is in effect, so it is inferred from the largest context actually
# observed (see _parse_session_jsonl).
CONTEXT_WINDOW_LARGE = 1_000_000
CLAUDE_DIR = os.path.expanduser("~/.claude")
PROJECTS_DIR = os.path.join(CLAUDE_DIR, "projects")
CODEX_DIR = os.path.expanduser("~/.codex")
CODEX_SESSIONS_DIR = os.path.join(CODEX_DIR, "sessions")
DEVIN_DB = os.path.expanduser("~/.local/share/devin/cli/sessions.db")
DEVIN_LOCK_DIR = os.path.expanduser("~/.local/share/devin/cli/session_locks")
# Devin's own footer reports "Context: 85k / 1.0M tokens"; the DB stores the
# used-token count but not the window size, so this mirrors what Devin shows.
DEVIN_CONTEXT_WINDOW = 1_000_000

# All agent CLI names to detect
AGENT_KEYWORDS = ["claude", "gemini", "codex", "devin"]

# ── Theme ────────────────────────────────────────────────────────────────
BG = "#0d1117"
SURFACE = "#161b22"
FG = "#c9d1d9"
DIM = "#484f58"
ACCENT = "#58a6ff"
GREEN = "#3fb950"
YELLOW = "#d29922"
RED = "#f85149"
BORDER = "#30363d"
SEL_BG = "#1f6feb"

# ── Utilities ────────────────────────────────────────────────────────────
ANSI_RE = re.compile(
    r"\x1b(?:\[[0-9;]*[a-zA-Z]|\][^\x07]*\x07|[()][AB012]|\[\??\d*[hl])"
)


def _run(cmd, timeout=5, check=True):
    """Run a command and return stdout ("" on failure).

    check=False keeps stdout even on a non-zero exit, for tools like lsof that
    report 1 whenever any path was inaccessible while still printing usable
    output.
    """
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if check and r.returncode != 0:
            return ""
        return r.stdout
    except Exception:
        return ""


def _strip(s):
    return ANSI_RE.sub("", s)


SGR_RE = re.compile(r"\x1b\[([0-9;]*)m")


def _is_highlighted(raw_line, clean_line):
    """True if a TUI menu row looks like the active one.

    Devin highlights the selected row with reverse video (or a background
    colour) instead of a glyph, and _strip() removes that, so this has to run
    against the raw line. Glyph markers are still honoured for agents that use
    them.
    """
    if clean_line.startswith(("❯", "❭", ">", "●", "▸", "▶", "→")):
        return True
    for params in SGR_RE.findall(raw_line):
        codes = [p for p in params.split(";") if p]
        if not codes:            # bare "\x1b[m" is a reset
            continue
        for i, code in enumerate(codes):
            if code == "7":                       # reverse video
                return True
            if code in ("48", "38"):              # extended colour, skip args
                break
            if code.isdigit() and (40 <= int(code) <= 47 or 100 <= int(code) <= 107):
                return True                       # explicit background colour
        if "48" in codes:                         # 256/truecolor background
            return True
    return False


def _flat_button(parent, text, command, bg=BORDER, fg=FG,
                 hover_bg=SEL_BG, hover_fg="#ffffff",
                 font=("Menlo", 10, "bold")):
    """A clickable Label styled as a button.

    On macOS (windowingsystem "aqua") tk.Button renders with the native theme
    and ignores -background, so the dark-themed buttons came out white with
    pale grey text and read as disabled. Labels honour the colours, so this
    reproduces the button behaviour by hand.
    """
    btn = tk.Label(parent, text=text, bg=bg, fg=fg, font=font, padx=10, pady=3)

    btn.bind("<Button-1>", lambda _e: command())
    btn.bind("<Enter>", lambda _e: btn.config(bg=hover_bg, fg=hover_fg))
    btn.bind("<Leave>", lambda _e: btn.config(bg=bg, fg=fg))
    try:
        btn.config(cursor="pointinghand")
    except tk.TclError:
        btn.config(cursor="hand2")
    return btn


def _bar(pct, width=12):
    # Clamp: an over-100% reading would otherwise render a bar wider than
    # `width` (the padding term goes negative and yields ""), which knocks the
    # whole column out of alignment.
    filled = max(0, min(width, round(pct / 100 * width)))
    return "\u2588" * filled + "\u2591" * (width - filled)


def _fmt_tokens(n):
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}k"
    return str(n)


# ── JSONL session data ──────────────────────────────────────────────────
# Re-parsing every transcript on each refresh dominated the refresh cost, so
# parsed results are memoised on (path, mtime, size) and only recomputed when
# the file actually changes.
_SESSION_CACHE: dict[str, tuple[tuple, dict]] = {}


def _cached_parse(path, parser):
    try:
        st = os.stat(path)
    except OSError:
        return None
    key = (st.st_mtime_ns, st.st_size)
    hit = _SESSION_CACHE.get(path)
    if hit and hit[0] == key:
        return hit[1]
    data = parser(path)
    _SESSION_CACHE[path] = (key, data)
    return data


def _load_devin_sessions():
    """Read context usage from Devin's CLI sqlite database.

    Devin doesn't write Claude-style JSONL transcripts, so its panes never
    matched a session and the Context column always read 0%. The DB is the same
    source Devin's own footer uses. The schema is undocumented, so every failure
    mode here degrades to "no data" rather than raising.
    """
    try:
        st = os.stat(DEVIN_DB)
    except OSError:
        return {}
    key = (st.st_mtime_ns, st.st_size)
    hit = _SESSION_CACHE.get(DEVIN_DB)
    if hit and hit[0] == key:
        return hit[1]

    sessions = {}
    try:
        # Read-only URI so a live Devin process is never blocked or modified.
        conn = sqlite3.connect(f"file:{DEVIN_DB}?mode=ro", uri=True, timeout=2)
        try:
            rows = conn.execute("""
                SELECT s.id, s.working_directory, s.model, s.last_activity_at,
                       (SELECT json_extract(m.metadata, '$.num_tokens_preceding')
                          FROM message_nodes m
                         WHERE m.session_id = s.id
                           AND json_extract(m.metadata,
                                            '$.num_tokens_preceding') IS NOT NULL
                         ORDER BY m.node_id DESC
                         LIMIT 1)
                  FROM sessions s
            """).fetchall()
        finally:
            conn.close()
    except Exception:
        return {}

    for sid, cwd, model, last_activity, tokens in rows:
        tokens = tokens or 0
        sessions[f"devin:{sid}"] = {
            "agent_type": "devin",
            "working_directory": cwd or "",
            "model": model or "",
            "last_activity_at": last_activity or 0,
            "input_tokens": tokens,
            "output_tokens": 0,
            "context_window": DEVIN_CONTEXT_WINDOW,
            "ctx_pct": round(tokens / DEVIN_CONTEXT_WINDOW * 100, 1),
            "num_turns": 0,
            "first_user_msg": "",
        }
    _SESSION_CACHE[DEVIN_DB] = (key, sessions)
    return sessions


def _apply_live_context(sessions):
    """Overlay Claude Code's own context reading onto the matching session.

    Transcripts don't record which context window is in effect, so a 1M-window
    session was measured against 200k and read ~5x too high. The statusline
    payload in rate-limits.json carries the real window size and percentage,
    keyed by session_id. It only ever describes the session that most recently
    rendered a statusline; every other session keeps its transcript estimate.
    """
    try:
        with open(RATE_LIMITS_FILE) as f:
            data = json.load(f)
        sid = data.get("session_id")
        ctx = data.get("context_window") or {}
        window = ctx.get("context_window_size")
        if not sid or sid not in sessions or not window:
            return
        used = ctx.get("total_input_tokens")
        if used is None:
            cur = ctx.get("current_usage") or {}
            used = _usage_total(cur)
        sessions[sid] = {
            **sessions[sid],
            "context_window": window,
            "input_tokens": used,
            "ctx_pct": ctx.get("used_percentage",
                               round(used / window * 100, 1) if window else 0),
        }
        display = (data.get("model") or {}).get("display_name")
        if display:
            sessions[sid]["model"] = display
    except Exception:
        pass


def _load_all_sessions():
    sessions = {}
    sessions.update(_load_codex_sessions())
    sessions.update(_load_devin_sessions())
    seen = set()
    for proj_dir in glob.glob(os.path.join(PROJECTS_DIR, "*")):
        if not os.path.isdir(proj_dir):
            continue
        for jf in glob.glob(os.path.join(proj_dir, "*.jsonl")):
            sid = os.path.basename(jf).replace(".jsonl", "")
            seen.add(jf)
            try:
                data = _cached_parse(jf, _parse_session_jsonl)
            except Exception:
                continue
            if data is not None:
                sessions[sid] = data
    # Drop cache entries for transcripts that no longer exist.
    for stale in [p for p in _SESSION_CACHE
                  if p.startswith(PROJECTS_DIR) and p not in seen]:
        _SESSION_CACHE.pop(stale, None)
    _apply_live_context(sessions)
    return sessions


def _load_codex_sessions():
    sessions = {}
    pattern = os.path.join(CODEX_SESSIONS_DIR, "**", "*.jsonl")
    for jf in glob.glob(pattern, recursive=True):
        try:
            data = _cached_parse(jf, _parse_codex_session_jsonl)
        except Exception:
            continue
        if data is not None:
            sessions[f"codex:{os.path.basename(jf).replace('.jsonl', '')}"] = data
    return sessions


def _parse_codex_session_jsonl(path):
    first_user_text = None
    user_messages = []
    last_token = None
    last_rate_limits = None
    context_window = CONTEXT_WINDOW
    num_turns = 0
    cwd = None

    with open(path) as f:
        for line in f:
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            payload = d.get("payload", {})
            if d.get("type") == "session_meta":
                cwd = payload.get("cwd", cwd)
            if d.get("type") == "event_msg" and payload.get("type") == "user_message":
                t = payload.get("message") or ""
                if t and not t.startswith("/"):
                    if first_user_text is None:
                        first_user_text = t
                    user_messages.append(t)
            if d.get("type") == "event_msg" and payload.get("type") == "token_count":
                info = payload.get("info", {})
                last_token = info
                last_rate_limits = payload.get("rate_limits")
                context_window = info.get("model_context_window") or context_window
                num_turns += 1

    usage = (last_token or {}).get("last_token_usage", {})
    total_usage = (last_token or {}).get("total_token_usage", {})
    input_tokens = usage.get("input_tokens", 0)
    output_tokens = usage.get("output_tokens", 0)

    return dict(
        agent_type="codex",
        model=None,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        context_window=context_window,
        ctx_pct=round(input_tokens / context_window * 100, 1) if context_window else 0,
        first_user_msg=first_user_text or "",
        user_messages=user_messages,
        total_output=total_usage.get("output_tokens", 0),
        num_turns=num_turns,
        rate_limits=last_rate_limits,
        mtime=os.path.getmtime(path),
        cwd=cwd,
    )


def _usage_total(usage):
    """Context size for one request: fresh input plus both cache tiers."""
    return (usage.get("input_tokens", 0)
            + usage.get("cache_creation_input_tokens", 0)
            + usage.get("cache_read_input_tokens", 0))


def _parse_session_jsonl(path):
    last_usage = None
    model = None
    first_user_text = None
    user_messages = []
    total_output = 0
    num_turns = 0
    max_ctx = 0

    with open(path) as f:
        for line in f:
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            msg = d.get("message", {})
            if d.get("type") == "user":
                t = _extract_text(msg)
                if t and not t.startswith("/"):
                    if first_user_text is None:
                        first_user_text = t
                    user_messages.append(t)
            if isinstance(msg, dict) and "usage" in msg:
                last_usage = msg["usage"]
                model = msg.get("model", model)
                total_output += last_usage.get("output_tokens", 0)
                num_turns += 1
                max_ctx = max(max_ctx, _usage_total(last_usage))

    if not last_usage:
        return dict(model=model, input_tokens=0, output_tokens=0,
                    ctx_pct=0, context_window=CONTEXT_WINDOW,
                    first_user_msg=first_user_text or "",
                    user_messages=user_messages,
                    total_output=0, num_turns=0)

    total_ctx = _usage_total(last_usage)
    # Pick the smallest standard window the session actually fits in. Without
    # this a 1M-window session reported >100% and rendered an oversized bar.
    context_window = (CONTEXT_WINDOW_LARGE if max_ctx > CONTEXT_WINDOW
                      else CONTEXT_WINDOW)

    return dict(
        model=model, input_tokens=total_ctx,
        output_tokens=last_usage.get("output_tokens", 0),
        context_window=context_window,
        ctx_pct=round(total_ctx / context_window * 100, 1) if context_window else 0,
        first_user_msg=first_user_text or "",
        user_messages=user_messages,
        total_output=total_output, num_turns=num_turns,
    )


def _extract_text(msg):
    raw = ""
    if isinstance(msg, str):
        raw = msg
    elif isinstance(msg, dict):
        content = msg.get("content", "")
        if isinstance(content, str):
            raw = content
        elif isinstance(content, list):
            for c in content:
                if isinstance(c, dict) and c.get("type") == "text":
                    raw = c.get("text", "")
                    break
    # Strip XML tags (e.g. <local-command-caveat>...</local-command-caveat>)
    cleaned = re.sub(r"<[^>]+>", "", raw).strip()
    # Skip system caveats that aren't real user messages
    if cleaned.startswith("Caveat:") or not cleaned:
        return ""
    return cleaned


# ── Usage stats ────────────────────────────────────────────────────────
STATS_CACHE = os.path.join(CLAUDE_DIR, "stats-cache.json")
RATE_LIMITS_FILE = os.path.join(CLAUDE_DIR, "rate-limits.json")


def _load_usage_stats():
    """Compute usage directly from JSONL session files."""
    now = datetime.now()
    today_str = now.strftime("%Y-%m-%d")
    week_ago = time.time() - 7 * 86400
    five_h_ago = time.time() - 5 * 3600

    stats = {
        "today_messages": 0, "today_tokens": 0, "today_sessions": 0,
        "week_messages": 0, "week_tokens": 0, "week_sessions": 0,
        "five_h_messages": 0, "five_h_tokens": 0,
        "subscription": None, "tier": None,
        "five_h_pct": None, "seven_d_pct": None,
        "five_h_resets": None, "seven_d_resets": None,
        "codex_primary_pct": None, "codex_primary_resets": None,
        "codex_primary_window": None,
        "codex_secondary_pct": None, "codex_secondary_resets": None,
        "codex_secondary_window": None,
        "codex_plan": None,
    }

    # Read credentials for subscription info
    try:
        with open(os.path.join(CLAUDE_DIR, ".credentials.json")) as f:
            creds = json.load(f)
        oauth = creds.get("claudeAiOauth", {})
        stats["subscription"] = oauth.get("subscriptionType")
        stats["tier"] = oauth.get("rateLimitTier")
    except Exception:
        pass

    # Scan JSONL files modified in the last 7 days
    today_session_ids = set()
    week_session_ids = set()
    try:
        for proj_dir in glob.glob(os.path.join(PROJECTS_DIR, "*")):
            if not os.path.isdir(proj_dir):
                continue
            for jf in glob.glob(os.path.join(proj_dir, "*.jsonl")):
                if os.path.getmtime(jf) < week_ago:
                    continue
                sid = os.path.basename(jf).replace(".jsonl", "")
                file_has_today = False
                file_has_week = False
                try:
                    with open(jf) as f:
                        for line in f:
                            try:
                                d = json.loads(line)
                            except json.JSONDecodeError:
                                continue
                            ts = d.get("timestamp")
                            if not ts:
                                continue
                            try:
                                epoch = datetime.fromisoformat(
                                    ts.replace("Z", "+00:00")).timestamp()
                            except Exception:
                                continue
                            msg = d.get("message", {})
                            if not isinstance(msg, dict) or "usage" not in msg:
                                continue
                            u = msg["usage"]
                            tok = (u.get("input_tokens", 0) +
                                   u.get("output_tokens", 0))
                            # 5-hour window
                            if epoch >= five_h_ago:
                                stats["five_h_messages"] += 1
                                stats["five_h_tokens"] += tok
                            # Today
                            if ts.startswith(today_str):
                                stats["today_messages"] += 1
                                stats["today_tokens"] += tok
                                file_has_today = True
                            # This week
                            if epoch >= week_ago:
                                stats["week_messages"] += 1
                                stats["week_tokens"] += tok
                                file_has_week = True
                except Exception:
                    continue
                if file_has_today:
                    today_session_ids.add(sid)
                if file_has_week:
                    week_session_ids.add(sid)
    except Exception:
        pass

    stats["today_sessions"] = len(today_session_ids)
    stats["week_sessions"] = len(week_session_ids)
    stats.update(_read_codex_rate_limits())
    return stats


def _fmt_window(minutes):
    if minutes is None:
        return None
    if minutes % 10080 == 0:
        weeks = minutes // 10080
        return "7d" if weeks == 1 else f"{weeks}w"
    if minutes % 1440 == 0:
        days = minutes // 1440
        return "24h" if days == 1 else f"{days}d"
    if minutes % 60 == 0:
        hours = minutes // 60
        return f"{hours}h"
    return f"{minutes}m"


def _read_codex_rate_limits():
    result = {
        "codex_primary_pct": None, "codex_primary_resets": None,
        "codex_primary_window": None,
        "codex_secondary_pct": None, "codex_secondary_resets": None,
        "codex_secondary_window": None,
        "codex_plan": None,
    }
    codex_sessions = _load_codex_sessions()
    latest = max(codex_sessions.values(), key=lambda s: s.get("mtime", 0), default=None)
    if not latest:
        return result
    rl = latest.get("rate_limits") or {}
    result["codex_plan"] = rl.get("plan_type")
    for prefix, data in (("primary", rl.get("primary")), ("secondary", rl.get("secondary"))):
        if not isinstance(data, dict):
            continue
        out_prefix = f"codex_{prefix}"
        result[f"{out_prefix}_pct"] = data.get("used_percent")
        result[f"{out_prefix}_window"] = _fmt_window(data.get("window_minutes"))
        if data.get("resets_at"):
            result[f"{out_prefix}_resets"] = datetime.fromtimestamp(
                data["resets_at"]).strftime("Resets %a %I:%M %p")
    return result


def _read_rate_limits():
    """Read rate limits from ~/.claude/rate-limits.json (written by Claude Code)."""
    result = {"five_h_pct": None, "five_h_resets": None,
              "seven_d_pct": None, "seven_d_resets": None}
    try:
        with open(RATE_LIMITS_FILE) as f:
            data = json.load(f)
        rl = data.get("rate_limits", {})
        fh = rl.get("five_hour", {})
        sd = rl.get("seven_day", {})
        if "used_percentage" in fh:
            result["five_h_pct"] = fh["used_percentage"]
        if "resets_at" in fh:
            reset_dt = datetime.fromtimestamp(fh["resets_at"])
            result["five_h_resets"] = f"Resets {reset_dt.strftime('%I:%M %p')}"
        if "used_percentage" in sd:
            result["seven_d_pct"] = sd["used_percentage"]
        if "resets_at" in sd:
            reset_dt = datetime.fromtimestamp(sd["resets_at"])
            result["seven_d_resets"] = f"Resets {reset_dt.strftime('%a %I:%M %p')}"
    except Exception:
        pass
    return result


def _run_slash_command(target, command):
    """Send a slash command to a pane and capture the output."""
    # Capture scrollback before
    before = _run(["tmux", "capture-pane", "-t", target, "-p", "-S", "-", "-E", "-"])
    before_lines = before.splitlines()
    before_len = len(before_lines)

    # Send the command
    _run(["tmux", "send-keys", "-t", target, "-l", command])
    _run(["tmux", "send-keys", "-t", target, "Enter"])

    # Wait and poll for output to stabilize
    time.sleep(2)
    last_len = 0
    for _ in range(4):
        snap = _run(["tmux", "capture-pane", "-t", target, "-p", "-S", "-", "-E", "-"])
        cur_len = len(snap.splitlines())
        if cur_len == last_len and cur_len != before_len:
            break
        last_len = cur_len
        time.sleep(1)

    # Also capture the visible pane (alternate screen / TUI dialogs)
    visible = _run(["tmux", "capture-pane", "-t", target, "-p"])

    # Full scrollback after
    after = _run(["tmux", "capture-pane", "-t", target, "-p", "-S", "-", "-E", "-"])
    after_lines = after.splitlines()

    # Extract new output from scrollback delta
    new_lines = after_lines[max(0, before_len - 2):]

    # Strip ANSI and box-drawing chars
    box_chars = set("─━═╔╗╚╝║│┌┐└┘├┤┬┴┼╭╮╰╯▏▕▔▁ ")
    def _clean_lines(lines):
        out = []
        for line in lines:
            c = _strip(line).strip()
            if c and not set(c) <= box_chars:
                out.append(c)
        return out

    scroll_result = _clean_lines(new_lines)
    visible_result = _clean_lines(visible.splitlines())

    # Use whichever captured more content (TUI commands render in visible pane)
    if len(visible_result) > len(scroll_result) + 2:
        result_lines = visible_result
    else:
        result_lines = scroll_result

    # Close any dialog (Escape) - some commands open TUI dialogs
    _run(["tmux", "send-keys", "-t", target, "Escape"])
    time.sleep(0.3)
    _run(["tmux", "send-keys", "-t", target, "Escape"])

    return "\n".join(result_lines)


# ── Tmux introspection ──────────────────────────────────────────────────
def _detect_agent_from_proc(pid, depth=3):
    """Walk the process tree and return which agent keyword is found, or None."""
    if depth <= 0:
        return None
    out = _run(["ps", "-o", "command=", "-p", str(pid)])
    for kw in AGENT_KEYWORDS:
        if kw in out.lower():
            return kw
    for child in _run(["pgrep", "-P", str(pid)]).split():
        child = child.strip()
        if child:
            found = _detect_agent_from_proc(child, depth - 1)
            if found:
                return found
    return None


# Keep backward-compat alias
def _has_claude_descendant(pid, depth=3):
    return _detect_agent_from_proc(pid, depth) is not None


def _devin_lock_owners():
    """Map pid -> devin session id via the lock each running session holds.

    Two Devin sessions can be started from the same directory, so the working
    directory can't tell them apart; the lock file name can.
    """
    owners = {}
    for line in _run(["lsof", "+D", DEVIN_LOCK_DIR],
                     check=False).splitlines()[1:]:
        parts = line.split()
        if len(parts) < 2:
            continue
        m = re.search(r"([^/\s]+)\.lock$", parts[-1])
        if m:
            owners[parts[1]] = m.group(1)
    return owners


def _devin_session_for_pane(pid, owners, depth=3):
    """Walk a pane's process tree to the devin process and return its session."""
    if depth <= 0 or not owners:
        return None
    if str(pid) in owners:
        return owners[str(pid)]
    for child in _run(["pgrep", "-P", str(pid)]).split():
        found = _devin_session_for_pane(child.strip(), owners, depth - 1)
        if found:
            return found
    return None


def get_claude_panes():
    """Return all panes running any supported agent."""
    fmt = "\t".join([
        "#{session_name}", "#{window_index}", "#{pane_index}",
        "#{pane_id}", "#{pane_current_command}", "#{pane_pid}",
        "#{window_name}", "#{session_name}:#{window_index}.#{pane_index}",
    ])
    raw = _run(["tmux", "list-panes", "-a", "-F", fmt])
    panes = []
    for line in raw.strip().splitlines():
        parts = line.split("\t")
        if len(parts) < 8:
            continue
        p = dict(
            session=parts[0], win_idx=parts[1], pane_idx=parts[2],
            pane_id=parts[3], cmd=parts[4], pid=parts[5],
            win_name=parts[6], target=parts[7],
        )
        cmd_lower = p["cmd"].lower()
        agent_kw = next((kw for kw in AGENT_KEYWORDS if kw in cmd_lower), None)
        if not agent_kw:
            agent_kw = _detect_agent_from_proc(p["pid"])
        if agent_kw:
            p["agent_type"] = agent_kw
            panes.append(p)
    return panes


def _is_gemini_idle(vis_lines):
    """Check if the last non-empty visible line is a bare Gemini '>' prompt."""
    for line in reversed(vis_lines):
        c = _strip(line).strip()
        if c:
            return c == ">" or c.startswith("> ")
    return False


def _is_gemini_waiting(vis_lines):
    """Check if Gemini is waiting for follow-up input."""
    for line in reversed(vis_lines[-10:]):
        c = _strip(line).strip()
        if c and (c.endswith("?") or "continue" in c.lower() or "enter" in c.lower()):
            return True
    return False


def _last_prompt_line(vis_lines):
    for line in reversed(vis_lines):
        c = _strip(line).strip()
        if c.startswith(("❯", "❭", "›")):
            return c
    return ""


def _status_from_prompt(vis_lines, agent_type):
    """Classify only the latest prompt block, not stale prompts in scrollback."""
    clean = [_strip(line).strip() for line in vis_lines]
    prompt_idx = None
    prompt_line = ""
    for i in range(len(clean) - 1, -1, -1):
        if clean[i].startswith(("❯", "❭", "›")):
            prompt_idx, prompt_line = i, clean[i]
            break
    if prompt_idx is None:
        return None

    # If agent output appears after the last submitted prompt, it is still working.
    chrome_hints = (
        "CTX", "5H", "7D", "manual mode", "for shortcuts", "to start fresh",
        "Press opt+t", "cycle thinking levels", "select ·", "confirm ·", "esc cancel",
    )
    box_chars = set("─━═╔╗╚╝║│┌┐└┘├┤┬┴┼ ")
    after_prompt = []
    for line in clean[prompt_idx + 1:]:
        if not line or set(line) <= box_chars or any(h in line for h in chrome_hints):
            continue
        after_prompt.append(line)
    if after_prompt:
        return "Working"

    prompt_text = prompt_line.lstrip("❯❭›>  ").strip()
    idle_placeholders = ("Ask Devin to", "Ask Claude", "Ask Codex", "? for shortcuts")
    if not prompt_text or any(prompt_text.startswith(p) for p in idle_placeholders):
        return "Idle"
    return "Waiting for input"


def read_pane_content(target, agent_type=None):
    scrollback = _run(["tmux", "capture-pane", "-t", target, "-p", "-S", "-200"])
    visible = _run(["tmux", "capture-pane", "-t", target, "-p"])
    all_lines = scrollback.splitlines() if scrollback else visible.splitlines()
    vis_lines = visible.splitlines()

    forced_agent = agent_type if agent_type in AGENT_KEYWORDS else None
    info = dict(model=None, version=None, status="Idle", activity="",
                first_user_msg=None, prompt_options=[], prompt_desc="",
                nav_selected=None,
                agent_type=forced_agent or "claude")

    for line in all_lines:
        c = _strip(line).strip()
        if not c:
            continue
        # Claude model detection
        m = re.search(r"(Opus|Sonnet|Haiku)\s+([\d.]+)", c, re.I)
        if m:
            info["model"] = f"{m.group(1)} {m.group(2)}"
        m = re.search(r"(claude-(?:opus|sonnet|haiku)[\w.-]*)", c, re.I)
        if m and not info["model"]:
            info["model"] = m.group(1)
        m = re.search(r"Claude Code\s+(v[\d.]+)", c, re.I)
        if m:
            info["version"] = m.group(1)
        # Devin version/model detection
        m = re.search(r"\bDevin(?: for Terminal| CLI)?\b", c, re.I)
        if m and not forced_agent:
            info["agent_type"] = "devin"
        m = re.search(r"\bv\d{4}\.\d+\.\d+(?:-\d+)?\b|\bv\d{3,}\.\d+\.\d+\b", c)
        if m and info["agent_type"] == "devin":
            info["version"] = m.group(0)
        m = re.search(r"\bClaude\s+(Opus|Sonnet|Haiku)\s+[\d.]+\s+Max\b", c, re.I)
        if m and info["agent_type"] == "devin":
            info["model"] = c.split("Context:", 1)[0].split("Press ", 1)[0].strip()
        # Gemini model detection
        m = re.search(r"(gemini-[\w.-]+)", c, re.I)
        if m and not forced_agent:
            info["model"] = m.group(1)
            info["agent_type"] = "gemini"
        if re.search(r"\bgemini\b", c, re.I) and not info["model"] and not forced_agent:
            info["agent_type"] = "gemini"
        # Codex model detection
        m = re.search(r"(codex-[\w.-]+|gpt-[\w.-]+)", c, re.I)
        if m and info["agent_type"] == "claude" and not forced_agent:
            info["model"] = m.group(1)
            info["agent_type"] = "codex"
        # Devin detection
        if re.search(r"\bdevin\b", c, re.I) and not forced_agent:
            info["agent_type"] = "devin"

    for i, line in enumerate(all_lines):
        c = _strip(line).strip()
        if c.startswith(("\u276f", "❯", "❭", "›")):
            msg_part = c.lstrip("\u276f❯❭›  ").strip()
            if (msg_part and len(msg_part) > 2 and not msg_part.startswith("/")
                    and not msg_part.startswith("Ask Devin to")):
                info["first_user_msg"] = msg_part
                break

    vis_text = "\n".join(_strip(l) for l in vis_lines)
    approval_keywords = [
        "Do you want to proceed?", "Yes, and don",
        "Allow once", "Allow always", "Deny",
        "1. Yes", "2. Yes, and don", "3. No",
        "1. Allow", "2. Allow always", "3. Deny",
    ]
    parsed_opts, parsed_desc, nav_selected = _parse_prompt_options(vis_lines)

    # Detect y/N or Y/n style prompts (common in Gemini CLI and other agents)
    yn_match = re.search(r'\?\s*\(([yYnN])/([yYnN])\)', vis_text)
    if not parsed_opts and yn_match:
        yes_key, no_key = yn_match.group(1), yn_match.group(2)
        parsed_opts = [("1", yes_key.upper()), ("2", no_key.upper())]
        parsed_desc = re.sub(r'\s*\([yYnN]/[yYnN]\)', '', vis_text.strip().splitlines()[-1]).strip()

    has_approval = (any(kw in vis_text for kw in approval_keywords)
                    or len(parsed_opts) >= 2)
    if has_approval:
        info["status"] = "Needs approval"
        info["prompt_options"] = parsed_opts
        info["prompt_desc"] = parsed_desc
        info["nav_selected"] = nav_selected
    elif (prompt_status := _status_from_prompt(vis_lines, info["agent_type"])):
        info["status"] = prompt_status
    elif _is_gemini_idle(vis_lines):
        info["status"] = "Idle"
    elif _is_gemini_waiting(vis_lines):
        info["status"] = "Waiting for input"
    else:
        info["status"] = "Working"

    action_stems = {
        "read", "writ", "edit", "search", "run", "think", "analy",
        "install", "build", "test", "compil", "fetch", "creat",
        "updat", "delet", "commit", "push", "pull", "clon",
        "grep", "glob", "bash", "agent", "sav", "load", "launch",
        "check", "deploy", "start", "finish", "download", "upload",
        "searched", "scanning", "processing",
    }
    statusbar_hints = {
        "Auto-update", "claude doctor", "npm i -g",
        "Press opt+t", "remaining (resets", "Context:",
        # Claude Code's own status bar sits below the prompt, so the bottom-up
        # scan reaches it first. "for agents" in particular contains the
        # "agent" stem and would otherwise always win.
        "manual mode on", "for agents", "/effort", "for shortcuts",
        "ctrl+o to expand", "esc to interrupt", "Tip: Use",
        "CTX ", "5H ", "7D ",
    }
    skip = {"? for shortcuts", "❯", "\u276f", "for shortcuts",
            "Esc to cancel", "Tab to amend", "❭ Ask Devin to"}
    # Claude Code marks its current action with a spinner glyph ("✻ Reticulating…
    # (12s · ↓ 4.1k tokens)") and finished steps with "⏺". Neither wording
    # contains an action stem, so match the glyphs directly and prefer them.
    if info["agent_type"] == "claude":
        for line in reversed(vis_lines[-40:]):
            c = _strip(line).strip()
            if any(h in c for h in statusbar_hints):
                continue
            m_act = re.match(r"^[⏺✻✽✢✶✳*]\s+(.{4,})", c)
            if m_act:
                info["activity"] = m_act.group(1).strip()[:120]
                break

    for line in reversed(vis_lines[-40:]):
        if info["activity"]:
            break
        c = _strip(line).strip()
        if len(c) < 4 or any(c.startswith(s) for s in skip):
            continue
        if any(h in c for h in statusbar_hints):
            continue
        if any(k in c.lower() for k in action_stems):
            info["activity"] = c[:120]
            break

    if not info["activity"]:
        box_chars = set("─━═╔╗╚╝║│┌┐└┘├┤┬┴┼\u2500\u2501\u2550 ")
        for line in reversed(vis_lines):
            c = _strip(line).strip()
            if (c and len(c) > 3 and not any(c.startswith(s) for s in skip)
                    and not set(c) <= box_chars
                    and not any(h in c for h in statusbar_hints)):
                info["activity"] = c[:120]
                break

    if info["agent_type"] == "devin" and info["status"] == "Idle":
        info["activity"] = "Idle"
    elif not info["activity"]:
        info["activity"] = info["status"]

    return info


def _parse_prompt_options(vis_lines):
    """Returns (options, description, nav_selected).

    nav_selected is the index of the currently highlighted row for arrow-key
    menus, or None if it could not be determined (and for numbered menus).
    """
    options = []
    desc_parts = []
    nav_selected = None
    in_approval_block = False
    option_label_re = re.compile(
        r"^(yes|no|allow|deny|always allow|allow once|y|n)\b", re.I
    )
    approval_markers = (
        "Bash command", "Edit file", "Read file", "Write file",
        "Execute", "Run", "Running command", "This command requires approval",
        "Do you want to proceed", "Do you want to allow",
        "Would you like to run", "Contains command_substitution",
        "Requires approval",
    )
    clean_lines = [_strip(line).strip() for line in vis_lines]
    nav_footer = any(
        ("select" in line.lower() and "confirm" in line.lower()
         and "cancel" in line.lower())
        for line in clean_lines[-30:]
    )
    for line in vis_lines:
        c = _strip(line).strip()
        if not c:
            continue
        # Capture tool/action description
        if any(kw in c for kw in approval_markers):
            in_approval_block = True
            desc_parts.append(c)
            continue
        # Match numbered options: "1. Yes", " 2) No", "3 - Allow", etc.
        # Also handles leading special chars like ❯, >, ●, etc.
        m = re.match(r'^[\s❯❭>●○*\-]*(\d{1,2})\s*[.):\-]\s+(.+)', c)
        if m:
            num, label = m.group(1), m.group(2).strip().rstrip(':')
            if in_approval_block and label and option_label_re.match(label):
                options.append((num, label))
    # Devin renders an arrow-key menu without option numbers. Only parse these
    # when its select/confirm/cancel footer proves that this is an active menu,
    # avoiding false positives from ordinary assistant bullet lists.
    if not options and nav_footer:
        nav_options = []
        highlighted = []
        for raw, c in list(zip(vis_lines, clean_lines))[-30:]:
            m = re.match(r'^[❯❭>●○*·•\-\s]*(yes|no|allow|deny)(.*)$', c, re.I)
            if m:
                label = (m.group(1) + m.group(2)).strip()
                if _is_highlighted(raw, c):
                    highlighted.append(len(nav_options))
                nav_options.append(label)
        # Devin marks the active row with reverse video rather than a glyph, so
        # the highlight only survives if we look at the raw line. When exactly
        # one row is marked we can navigate relative to it; otherwise fall back
        # to pinning the cursor at the top first (see _send_option).
        nav_selected = highlighted[0] if len(highlighted) == 1 else None
        options = [
            (f"nav:{idx}", label) for idx, label in enumerate(nav_options)
        ]
    # Deduplicate by option number
    seen_nums, clean = set(), []
    for num, label in options:
        if num not in seen_nums:
            seen_nums.add(num)
            clean.append((num, label))
    return clean, " ".join(desc_parts).strip()[:200], nav_selected


def match_pane_to_session(pane_info, sessions):
    if pane_info.get("agent_type") == "devin":
        # Identified exactly by the session lock the devin process holds. A
        # session with no messages yet has no DB row, so it correctly resolves
        # to nothing rather than borrowing another session's token count.
        sid = pane_info.get("devin_session")
        key = f"devin:{sid}" if sid else None
        return key if key in sessions else None

    if pane_info.get("agent_type") == "codex":
        codex_sessions = [
            (sid, sdata) for sid, sdata in sessions.items()
            if sdata.get("agent_type") == "codex"
        ]
        if codex_sessions and not pane_info.get("first_user_msg"):
            return max(codex_sessions, key=lambda item: item[1].get("mtime", 0))[0]

    pane_msg = pane_info.get("first_user_msg", "")
    if not pane_msg:
        return None
    pane_msg_lower = pane_msg.lower().strip()
    best_sid, best_score = None, 0
    for sid, sdata in sessions.items():
        # Check all user messages in the session, not just the first
        msgs = sdata.get("user_messages", [])
        if not msgs:
            s = sdata.get("first_user_msg", "")
            msgs = [s] if s else []
        for s_msg_raw in msgs:
            s_msg = s_msg_raw.lower().strip()
            if not s_msg:
                continue
            if pane_msg_lower in s_msg or s_msg.startswith(pane_msg_lower[:30]):
                score = len(pane_msg_lower)
            elif s_msg in pane_msg_lower:
                score = len(s_msg)
            else:
                continue
            if score > best_score:
                best_score, best_sid = score, sid
    return best_sid


# ── Send keys ────────────────────────────────────────────────────────────
def send_keys(target, text, enter=False):
    _run(["tmux", "send-keys", "-t", target, "-l", text])
    if enter:
        _run(["tmux", "send-keys", "-t", target, "Enter"])


# ── Attach / focus ──────────────────────────────────────────────────────
def attach(target):
    session_window = target.rsplit(".", 1)[0]
    session = session_window.split(":")[0]
    _run(["tmux", "select-window", "-t", session_window])
    _run(["tmux", "select-pane", "-t", target])
    clients = _run(["tmux", "list-clients", "-t", session, "-F", "#{client_tty}"])
    if clients.strip():
        tty = clients.strip().splitlines()[0]
        if _focus_terminal_tab(tty):
            return
    attach_cmd = f"tmux attach-session -t '{session}'"
    iterm_script = (
        'tell application "System Events"\n'
        '  if exists (processes where name is "iTerm2") then\n'
        '    tell application "iTerm"\n'
        '      activate\n'
        '      set W to (create window with default profile)\n'
        f'      tell current session of W to write text "{attach_cmd}"\n'
        '    end tell\n'
        '    return "ok"\n'
        '  end if\n'
        'end tell\n'
        'return "no"'
    )
    result = _run(["osascript", "-e", iterm_script])
    if "ok" not in result:
        subprocess.Popen(["osascript", "-e",
                          f'tell application "Terminal"\nactivate\n'
                          f'do script "{attach_cmd}"\nend tell'])


def _focus_terminal_tab(tty):
    iterm_script = f'''
    tell application "System Events"
        if not (exists (processes where name is "iTerm2")) then return "no"
    end tell
    tell application "iTerm"
        repeat with w in windows
            repeat with t in tabs of w
                repeat with s in sessions of t
                    if tty of s is "{tty}" then
                        select t
                        set index of w to 1
                        activate
                        return "ok"
                    end if
                end repeat
            end repeat
        end repeat
    end tell
    return "no"
    '''
    if "ok" in _run(["osascript", "-e", iterm_script]):
        return True
    term_script = f'''
    tell application "Terminal"
        set winCount to count of windows
        repeat with i from 1 to winCount
            set w to window i
            set tabCount to count of tabs of w
            repeat with j from 1 to tabCount
                set t to tab j of w
                if tty of t is "{tty}" then
                    set selected of t to true
                    set index of w to 1
                    activate
                    return "ok"
                end if
            end repeat
        end repeat
    end tell
    return "no"
    '''
    if "ok" in _run(["osascript", "-e", term_script]):
        return True
    return False


# ── GUI ──────────────────────────────────────────────────────────────────
COLUMNS = ("pane", "model", "context", "turns", "status", "activity")
COL_WIDTHS = dict(pane=55, model=140, context=250,
                   turns=65, status=120, activity=420)

AGENTS = [
    ("Claude Code", "claude"),
    ("Gemini CLI", "gemini"),
    ("Codex CLI", "codex"),
    ("Devin", "devin"),
]

SKILLS_DIR = pathlib.Path.home() / ".claude" / "skills"


def _parse_skill_md(path):
    content = path.read_text(encoding="utf-8")
    name = path.parent.name
    description = ""
    body = content
    if content.startswith("---"):
        parts = content.split("---", 2)
        if len(parts) >= 3:
            for line in parts[1].splitlines():
                if line.startswith("name:"):
                    name = line.split(":", 1)[1].strip()
                elif line.startswith("description:"):
                    description = line.split(":", 1)[1].strip()
            body = parts[2].strip()
    return {"name": name, "slug": path.parent.name, "description": description, "body": body}


def get_skills():
    """Return all available skills from ~/.claude/skills/"""
    if not SKILLS_DIR.exists():
        return []
    skills = []
    for skill_dir in sorted(SKILLS_DIR.iterdir()):
        skill_file = skill_dir / "SKILL.md"
        if skill_file.exists():
            try:
                skills.append(_parse_skill_md(skill_file))
            except Exception:
                continue
    return skills


def run_skill(target, skill_slug, user_prompt=""):
    """Send a skill's instructions + optional user request to any agent pane."""
    skill_file = SKILLS_DIR / skill_slug / "SKILL.md"
    if not skill_file.exists():
        if user_prompt:
            send_keys(target, user_prompt, enter=True)
        return
    parsed = _parse_skill_md(skill_file)
    body = parsed["body"]
    message = f"{body}\n\n---\nUser request: {user_prompt}" if user_prompt else body
    send_keys(target, message, enter=True)


SLASH_COMMANDS = [
    # Session & Conversation
    "/clear", "/compact", "/context", "/copy", "/branch", "/resume",
    "/rename", "/rewind",
    # File & Code
    "/add-dir", "/diff", "/export",
    # Config & Settings
    "/config", "/status", "/theme", "/color", "/terminal-setup",
    "/vim", "/keybindings",
    # Model & Performance
    "/model", "/effort", "/fast",
    # Skills & Tools
    "/skills", "/agents", "/mcp", "/hooks",
    # Security & Permissions
    "/permissions", "/security-review",
    # Auth & Account
    "/login", "/logout", "/privacy-settings",
    # Info & Help
    "/help", "/btw", "/doctor", "/cost", "/usage", "/stats",
    "/insights", "/release-notes",
    # Integrations
    "/install-github-app", "/install-slack-app", "/chrome", "/ide",
    # Memory & Context
    "/memory", "/init",
    # Platform
    "/desktop", "/remote-control",
    # Task & Planning
    "/plan", "/tasks",
    # Other
    "/feedback", "/passes", "/upgrade", "/extra-usage",
    "/statusline", "/pr-comments", "/review",
]


class Monitor:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title("Claude Session Monitor")
        root.geometry("1260x680")
        root.configure(bg=BG)
        root.minsize(900, 400)
        self._targets: dict[str, str] = {}       # iid -> tmux target (sess:win.pane)
        self._pane_info: dict[str, dict] = {}     # iid -> pane content info
        self._pane_data: dict[str, dict] = {}     # iid -> {pane_id, session, win_idx, target}
        self._group_iids: dict[str, str] = {}     # session_name -> treeview iid
        self._window_iids: dict[str, str] = {}    # "session:win_idx" -> treeview iid
        self._cached_usage: dict = {}             # cached /usage scrape result
        self._btn_sig = None                      # (target, options) currently rendered
        self._refreshing = False                  # a background gather is in flight
        self._refresh_pending = False             # a refresh was requested mid-gather
        self._result_q: queue.Queue = queue.Queue()  # worker thread -> UI thread
        self._build()
        self._drain_results()
        self._tick()
        self._poll_usage()

    def _build(self):
        self._apply_theme()
        self._build_header()
        self._build_usage_panel()
        self._build_table()
        self._build_interact_panel()
        self._build_footer()

    def _apply_theme(self):
        s = ttk.Style()
        s.theme_use("clam")
        s.configure(".", background=BG, foreground=FG)
        s.configure("Treeview", background=SURFACE, foreground=FG,
                     fieldbackground=SURFACE, rowheight=40,
                     font=("Menlo", 12))
        s.configure("Treeview.Heading", background=BORDER, foreground=ACCENT,
                     font=("Menlo", 11, "bold"), borderwidth=0)
        s.map("Treeview",
               background=[("selected", SEL_BG)],
               foreground=[("selected", "#ffffff")])

    def _build_header(self):
        hdr = tk.Frame(self.root, bg=BG)
        hdr.pack(fill="x", padx=24, pady=(18, 6))
        tk.Label(hdr, text="\u2b21  Claude Code Tmux Sessions", bg=BG, fg=ACCENT,
                 font=("Menlo", 17, "bold")).pack(side="left")
        self.lbl_count = tk.Label(hdr, bg=BG, fg=FG, font=("Menlo", 12))
        self.lbl_count.pack(side="right")

        # + button to launch new agent
        self._launch_menu = tk.Menu(self.root, tearoff=0, bg=SURFACE, fg=FG,
                                     activebackground=SEL_BG, activeforeground="#fff",
                                     font=("Menlo", 12))

        self._plus_btn = tk.Button(
            hdr, text="+ Add", bg=GREEN, fg="#000",
            activebackground="#2ea043", activeforeground="#000",
            font=("Menlo", 13, "bold"), bd=0, padx=12, pady=4,
            command=self._show_launch_menu)
        self._plus_btn.pack(side="right", padx=(0, 12))

        # / Commands button
        self._slash_menu = tk.Menu(self.root, tearoff=0, bg=SURFACE, fg=FG,
                                    activebackground=SEL_BG, activeforeground="#fff",
                                    font=("Menlo", 12))
        self._slash_btn = tk.Button(
            hdr, text="/ Cmd", bg=ACCENT, fg="#000",
            activebackground="#79b8ff", activeforeground="#000",
            font=("Menlo", 13, "bold"), bd=0, padx=12, pady=4,
            command=self._show_slash_menu)
        self._slash_btn.pack(side="right", padx=(0, 8))

        # Skills button
        self._skills_menu = tk.Menu(self.root, tearoff=0, bg=SURFACE, fg=FG,
                                     activebackground=SEL_BG, activeforeground="#fff",
                                     font=("Menlo", 12))
        self._skills_btn = tk.Button(
            hdr, text="✦ Skills", bg="#4a1d7a", fg="#c084fc",
            activebackground="#6b21a8", activeforeground="#e9d5ff",
            font=("Menlo", 13, "bold"), bd=0, padx=12, pady=4,
            command=self._show_skills_menu)
        self._skills_btn.pack(side="right", padx=(0, 8))

    def _build_usage_panel(self):
        panel = tk.Frame(self.root, bg=SURFACE, highlightbackground=BORDER,
                          highlightthickness=1)
        panel.pack(fill="x", padx=24, pady=(0, 4))

        row = tk.Frame(panel, bg=SURFACE)
        row.pack(fill="x", padx=12, pady=8)

        self._usage_labels = {}
        self._usage_bars = {}
        sections = [
            ("5h", "5 Hour Limit"),
            ("7d", "Weekly Limit"),
            ("codex", "Codex Limit"),
            ("today", "Today"),
            ("plan", "Plan"),
        ]
        for i, (key, title) in enumerate(sections):
            f = tk.Frame(row, bg=SURFACE)
            f.pack(side="left", expand=True, fill="x")
            if i > 0:
                tk.Frame(row, bg=BORDER, width=1).pack(side="left", fill="y", padx=8)
                f.pack(side="left", expand=True, fill="x")
            tk.Label(f, text=title, bg=SURFACE, fg=DIM,
                     font=("Menlo", 10)).pack(anchor="w")
            # Progress bar for limit sections
            if key in ("5h", "7d", "codex"):
                bar_frame = tk.Frame(f, bg=SURFACE)
                bar_frame.pack(anchor="w", fill="x", pady=(2, 0))
                bar_lbl = tk.Label(bar_frame, text="\u2591" * 20, bg=SURFACE, fg=DIM,
                                    font=("Menlo", 10))
                bar_lbl.pack(side="left")
                pct_lbl = tk.Label(bar_frame, text="", bg=SURFACE, fg=FG,
                                    font=("Menlo", 10, "bold"))
                pct_lbl.pack(side="left", padx=(6, 0))
                self._usage_bars[key] = (bar_lbl, pct_lbl)
            lbl = tk.Label(f, text="--", bg=SURFACE, fg=FG,
                           font=("Menlo", 11, "bold"))
            lbl.pack(anchor="w")
            self._usage_labels[key] = lbl

    def _update_usage_panel(self):
        stats = _load_usage_stats()
        usage = self._cached_usage

        # 5-hour limit
        fh_pct = usage.get("five_h_pct")
        if fh_pct is not None:
            self._set_limit_bar("5h", fh_pct)
            reset_str = ""
            if usage.get("five_h_resets"):
                reset_str = f"  |  {usage['five_h_resets']}"
            self._usage_labels["5h"].config(
                text=f"{stats['five_h_messages']} msgs  |  {_fmt_tokens(stats['five_h_tokens'])} tok{reset_str}")
        else:
            self._set_limit_bar("5h", None)
            self._usage_labels["5h"].config(
                text=f"{stats['five_h_messages']} msgs  |  {_fmt_tokens(stats['five_h_tokens'])} tok")

        # 7-day limit
        sd_pct = usage.get("seven_d_pct")
        if sd_pct is not None:
            self._set_limit_bar("7d", sd_pct)
            reset_str = ""
            if usage.get("seven_d_resets"):
                reset_str = f"  |  {usage['seven_d_resets']}"
            self._usage_labels["7d"].config(
                text=f"{stats['week_messages']} msgs  |  {_fmt_tokens(stats['week_tokens'])} tok  |  {stats['week_sessions']} sess{reset_str}")
        else:
            self._set_limit_bar("7d", None)
            self._usage_labels["7d"].config(
                text=f"{stats['week_messages']} msgs  |  {_fmt_tokens(stats['week_tokens'])} tok  |  {stats['week_sessions']} sess")

        # Today
        codex_bits = []
        cp = stats.get("codex_primary_pct")
        if cp is not None:
            codex_bits.append(f"{stats.get('codex_primary_window') or 'limit'} {cp:.0f}%")
        cs = stats.get("codex_secondary_pct")
        if cs is not None:
            codex_bits.append(f"{stats.get('codex_secondary_window') or 'limit'} {cs:.0f}%")
        if codex_bits:
            display_pct = cp if cp is not None else cs
            self._set_limit_bar("codex", display_pct)
            self._usage_labels["codex"].config(text="  |  ".join(codex_bits))
        else:
            self._set_limit_bar("codex", None)
            self._usage_labels["codex"].config(text="--")

        # Today
        self._usage_labels["today"].config(
            text=f"{stats['today_messages']} msgs  |  {_fmt_tokens(stats['today_tokens'])} tok  |  {stats['today_sessions']} sess")

        # Plan
        plan = stats.get("subscription") or "unknown"
        self._usage_labels["plan"].config(text=plan.capitalize())

    def _set_limit_bar(self, key, pct):
        if key not in self._usage_bars:
            return
        bar_lbl, pct_lbl = self._usage_bars[key]
        if pct is None:
            bar_lbl.config(text="\u2591" * 20, fg=DIM)
            pct_lbl.config(text="no data yet", fg=DIM)
            return
        width = 20
        filled = round(pct / 100 * width)
        bar = "\u2588" * filled + "\u2591" * (width - filled)
        if pct < 50:
            color = GREEN
        elif pct < 80:
            color = YELLOW
        else:
            color = RED
        bar_lbl.config(text=bar, fg=color)
        pct_lbl.config(text=f"{pct:.1f}%", fg=color)


    def _build_table(self):
        container = tk.Frame(self.root, bg=BG)
        container.pack(fill="both", expand=True, padx=24, pady=8)

        self.tv = ttk.Treeview(
            container, columns=COLUMNS, show="tree headings", selectmode="browse")
        sb = ttk.Scrollbar(container, orient="vertical", command=self.tv.yview)
        self.tv.configure(yscrollcommand=sb.set)

        # Tree column (used for session group names)
        self.tv.heading("#0", text="Task")
        self.tv.column("#0", width=150, minwidth=80)

        headings = dict(pane="Pane", model="Model",
                        context="Context Window", turns="Turns",
                        status="Status", activity="Activity")
        for col in COLUMNS:
            self.tv.heading(col, text=headings[col])
            self.tv.column(col, width=COL_WIDTHS[col], minwidth=50)

        for tag, color in [("ctx_green", GREEN), ("ctx_yellow", YELLOW),
                           ("ctx_red", RED), ("dim", DIM),
                           ("group", ACCENT), ("window", DIM)]:
            self.tv.tag_configure(tag, foreground=color)
        self.tv.tag_configure("group", font=("Menlo", 12, "bold"))
        self.tv.tag_configure("window", font=("Menlo", 11, "italic"))

        self.tv.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.tv.bind("<Double-1>", self._on_dbl_click)
        self.tv.bind("<<TreeviewSelect>>", self._on_select)
        self.tv.bind("<Button-3>", self._on_right_click)       # standard right-click
        self.tv.bind("<Button-2>", self._on_right_click)        # macOS two-finger
        self.tv.bind("<Control-Button-1>", self._on_right_click)  # Ctrl+click

    def _build_interact_panel(self):
        self._interact_frame = tk.Frame(self.root, bg=SURFACE,
                                         highlightbackground=BORDER,
                                         highlightthickness=1)
        self._interact_frame.pack(fill="x", padx=24, pady=(0, 4))

        row1 = tk.Frame(self._interact_frame, bg=SURFACE)
        row1.pack(fill="x", padx=12, pady=(8, 4))
        self._interact_label = tk.Label(
            row1, text="Select a session above", bg=SURFACE, fg=DIM,
            font=("Menlo", 11), anchor="w")
        self._interact_label.pack(side="left")
        self._btn_frame = tk.Frame(row1, bg=SURFACE)
        self._btn_frame.pack(side="right")
        self._esc_btn = _flat_button(
            self._btn_frame, "Esc (Cancel)", self._send_escape,
            bg="#3d1f1f", fg=RED, hover_bg="#5c2626", hover_fg="#ff7b72")

        row2 = tk.Frame(self._interact_frame, bg=SURFACE)
        row2.pack(fill="x", padx=12, pady=(0, 8))
        self._type_label = tk.Label(row2, text="Type:", bg=SURFACE, fg=DIM,
                                     font=("Menlo", 11))
        self._type_label.pack(side="left")
        self._text_entry = tk.Entry(
            row2, bg=BG, fg=FG, insertbackground=ACCENT,
            font=("Menlo", 12), bd=0, highlightbackground=BORDER,
            highlightcolor=ACCENT, highlightthickness=1)
        self._text_entry.pack(side="left", fill="x", expand=True, padx=(8, 8))
        self._text_entry.bind("<Return>", self._send_text)
        tk.Button(
            row2, text="Send", bg=ACCENT, fg="#000",
            activebackground="#79b8ff", activeforeground="#000",
            font=("Menlo", 11, "bold"), bd=0, padx=14, pady=3,
            command=self._send_text,
        ).pack(side="right")

    def _update_interact_panel(self):
        sel = self.tv.selection()
        if not sel or sel[0] not in self._targets:
            # Check if a group or window row is selected
            if sel and sel[0] in self._group_iids.values():
                sess = [k for k, v in self._group_iids.items() if v == sel[0]]
                name = sess[0] if sess else "?"
                self._interact_label.config(
                    text=f"Task: {name} — select a pane or click + to add agent", fg=ACCENT)
            elif sel and sel[0] in self._window_iids.values():
                wkey = [k for k, v in self._window_iids.items() if v == sel[0]]
                name = wkey[0] if wkey else "?"
                self._interact_label.config(
                    text=f"Window: {name} — select a pane or click + to split here", fg=ACCENT)
            else:
                self._interact_label.config(text="Select a session above", fg=DIM)
            self._clear_option_buttons()
            return
        iid = sel[0]
        target = self._targets[iid]
        info = self._pane_info.get(iid, {})
        status = info.get("status", "")
        pane_idx = self.tv.item(iid, "values")[0]
        if status != "Needs approval":
            self._clear_option_buttons()

        if status == "Needs approval":
            desc = info.get("prompt_desc", "")
            options = info.get("prompt_options", [])
            label = f"Pane {pane_idx} needs approval"
            if desc:
                label += f"  \u2502  {desc[:80]}"
            self._interact_label.config(text=label, fg=YELLOW)
            self._type_label.config(text="Follow-up (opt):", fg=ACCENT)
            # Only rebuild when the options actually changed. Destroying and
            # re-packing these every refresh swallowed clicks that landed
            # between mouse-down and mouse-up.
            sig = (target, tuple(options))
            if sig != self._btn_sig:
                self._clear_option_buttons()
                for display_num, (num, lbl) in enumerate(options, 1):
                    btn = _flat_button(
                        self._btn_frame, f"{display_num}. {lbl}",
                        lambda n=num, t=target: self._send_option(t, n))
                    btn.pack(side="left", padx=(0, 6))
                self._btn_sig = sig
            self._esc_btn.bind(
                "<Button-1>", lambda _e, t=target: self._send_escape(t))
            self._esc_btn.pack(side="left")
        elif status == "Waiting for input":
            self._type_label.config(text="Type:", fg=DIM)
            self._interact_label.config(
                text=f"Pane {pane_idx} is waiting for your input", fg=ACCENT)
        elif status == "Idle":
            self._type_label.config(text="Type:", fg=DIM)
            self._interact_label.config(
                text=f"Pane {pane_idx} is idle — type a message below", fg=GREEN)
        elif status == "Working":
            self._type_label.config(text="Type:", fg=DIM)
            self._interact_label.config(
                text=f"Pane {pane_idx} is working...", fg=DIM)
        else:
            self._type_label.config(text="Type:", fg=DIM)
            self._interact_label.config(text=f"Pane {pane_idx} — {status}", fg=FG)

    def _clear_option_buttons(self):
        for w in self._btn_frame.winfo_children():
            if w is not self._esc_btn:
                w.destroy()
        self._esc_btn.pack_forget()
        self._btn_sig = None

    def _send_option(self, target, num):
        num = str(num)
        if num.startswith("nav:"):
            want = int(num.split(":", 1)[1])
            # Arrow-key menus are navigated relative to whatever row is
            # highlighted right now, and that can have moved since this button
            # was built (the refresh is up to REFRESH_MS old, and the user can
            # arrow around in the terminal directly). Re-read it at click time.
            fresh = read_pane_content(target)
            current = fresh.get("nav_selected")
            if current is None:
                # Highlight undetectable: walk to the top so the index below is
                # absolute rather than a guess.
                for _ in range(max(len(fresh.get("prompt_options", [])) - 1, 0)):
                    _run(["tmux", "send-keys", "-t", target, "Up"])
                current = 0
            delta = want - current
            direction = "Down" if delta > 0 else "Up"
            for _ in range(abs(delta)):
                _run(["tmux", "send-keys", "-t", target, direction])
            _run(["tmux", "send-keys", "-t", target, "Enter"])
        else:
            send_keys(target, num, enter=True)
        extra = self._text_entry.get().strip()
        if extra:
            self._text_entry.delete(0, tk.END)
            self.root.after(400, lambda: send_keys(target, extra, enter=True))
        self.root.after(800, self._refresh)

    def _send_escape(self, target=None):
        if target is None:
            sel = self.tv.selection()
            if sel and sel[0] in self._targets:
                target = self._targets[sel[0]]
        if target:
            _run(["tmux", "send-keys", "-t", target, "Escape"])
            self.root.after(800, self._refresh)

    def _send_text(self, _event=None):
        sel = self.tv.selection()
        if not sel or sel[0] not in self._targets:
            return
        target = self._targets[sel[0]]
        text = self._text_entry.get().strip()
        if not text:
            return
        send_keys(target, text, enter=True)
        self._text_entry.delete(0, tk.END)
        self.root.after(800, self._refresh)

    def _on_select(self, _event):
        self._update_interact_panel()

    def _get_selected_target(self):
        """Get selection context: {session, window (optional), pane_target (optional)}."""
        sel = self.tv.selection()
        if not sel:
            return None
        iid = sel[0]

        # Check if it's a session group row
        for sess_name, giid in self._group_iids.items():
            if giid == iid:
                return {"session": sess_name}

        # Check if it's a window row
        for wkey, wiid in self._window_iids.items():
            if wiid == iid:
                sess, win = wkey.split(":", 1)
                return {"session": sess, "window": win}

        # It's a pane row — get pane data
        pdata = self._pane_data.get(iid)
        if pdata:
            return {"session": pdata["session"], "window": pdata["win_idx"],
                    "pane_target": pdata["target"], "pane_id": pdata["pane_id"]}

        return None

    def _show_launch_menu(self):
        self._launch_menu.delete(0, tk.END)
        target = self._get_selected_target()
        menu_style = dict(tearoff=0, bg=SURFACE, fg=FG,
                          activebackground=SEL_BG, activeforeground="#fff",
                          font=("Menlo", 12))

        # ── New Session (always) ──
        new_sess_sub = tk.Menu(self._launch_menu, **menu_style)
        for label, cmd in AGENTS:
            new_sess_sub.add_command(
                label=f"  {label}",
                command=lambda c=cmd, l=label: self._launch_new_session(c, l))
        self._launch_menu.add_cascade(label="  \u2795 New Session", menu=new_sess_sub)

        # ── New Window (if a session is in context) ──
        if target and "session" in target:
            sess = target["session"]
            new_win_sub = tk.Menu(self._launch_menu, **menu_style)
            for label, cmd in AGENTS:
                new_win_sub.add_command(
                    label=f"  {label}",
                    command=lambda c=cmd, s=sess: self._launch_new_window(c, s))
            self._launch_menu.add_cascade(
                label=f"  \u2795 New Window in {sess}", menu=new_win_sub)

        self._launch_menu.add_separator()

        # ── Split into specific window (if window or pane selected) ──
        if target and "window" in target:
            sess = target["session"]
            win = target["window"]
            for label, cmd in AGENTS:
                self._launch_menu.add_command(
                    label=f"  {label}  \u2192  {sess}:{win}",
                    command=lambda c=cmd, s=sess, w=win: self._launch_split(c, s, w))
        elif target and "session" in target:
            sess = target["session"]
            for label, cmd in AGENTS:
                self._launch_menu.add_command(
                    label=f"  {label}  \u2192  {sess}",
                    command=lambda c=cmd, s=sess: self._launch_split(c, s))
        else:
            # Nothing selected — list all sessions
            raw = _run(["tmux", "list-sessions", "-F", "#{session_name}"])
            sessions = [s.strip() for s in raw.strip().splitlines() if s.strip()]
            for s in sessions:
                sub = tk.Menu(self._launch_menu, **menu_style)
                for label, cmd in AGENTS:
                    sub.add_command(
                        label=f"  {label}",
                        command=lambda c=cmd, ss=s: self._launch_split(c, ss))
                self._launch_menu.add_cascade(label=f"  Split in {s}", menu=sub)

        self.root.update_idletasks()
        x = self._plus_btn.winfo_rootx()
        y = self._plus_btn.winfo_rooty() + self._plus_btn.winfo_height()
        try:
            self._launch_menu.tk_popup(x, y, 0)
        finally:
            self._launch_menu.grab_release()

    def _launch_new_session(self, cmd, label):
        """Create a brand new tmux session running the given agent."""
        from tkinter import filedialog

        dialog = tk.Toplevel(self.root)
        dialog.title(f"New Session — {label}")
        dialog.geometry("500x200")
        dialog.configure(bg=SURFACE)
        dialog.transient(self.root)
        dialog.grab_set()

        tk.Label(dialog, text="Session name:", bg=SURFACE, fg=FG,
                 font=("Menlo", 12)).pack(pady=(16, 4), padx=16, anchor="w")
        entry = tk.Entry(dialog, bg=BG, fg=FG, insertbackground=ACCENT,
                         font=("Menlo", 13), bd=0, highlightbackground=BORDER,
                         highlightcolor=ACCENT, highlightthickness=1)
        entry.pack(fill="x", padx=16)
        entry.focus_set()

        tk.Label(dialog, text="Working directory:", bg=SURFACE, fg=FG,
                 font=("Menlo", 12)).pack(pady=(10, 4), padx=16, anchor="w")
        dir_frame = tk.Frame(dialog, bg=SURFACE)
        dir_frame.pack(fill="x", padx=16)
        dir_var = tk.StringVar(value=os.path.expanduser("~"))
        dir_entry = tk.Entry(dir_frame, textvariable=dir_var, bg=BG, fg=FG,
                             insertbackground=ACCENT, font=("Menlo", 13), bd=0,
                             highlightbackground=BORDER, highlightcolor=ACCENT,
                             highlightthickness=1)
        dir_entry.pack(side="left", fill="x", expand=True)

        def _browse():
            d = filedialog.askdirectory(initialdir=dir_var.get(),
                                        parent=dialog)
            if d:
                dir_var.set(d)
        tk.Button(dir_frame, text="Browse", bg=ACCENT, fg="#000",
                  font=("Menlo", 11), bd=0, padx=8, pady=2,
                  command=_browse).pack(side="right", padx=(6, 0))

        def _create(_event=None):
            name = entry.get().strip()
            if not name:
                return
            name = re.sub(r"[^a-zA-Z0-9_-]", "-", name)
            cwd = dir_var.get().strip() or os.path.expanduser("~")
            dialog.destroy()
            _run(["tmux", "new-session", "-d", "-s", name, "-c", cwd, cmd])
            self.root.after(1500, self._refresh)

        entry.bind("<Return>", _create)
        btn_frame = tk.Frame(dialog, bg=SURFACE)
        btn_frame.pack(fill="x", padx=16, pady=(10, 12))
        tk.Button(btn_frame, text="Cancel", bg=BORDER, fg=FG,
                  font=("Menlo", 11), bd=0, padx=12, pady=3,
                  command=dialog.destroy).pack(side="right")
        tk.Button(btn_frame, text="Create", bg=GREEN, fg="#000",
                  activebackground="#2ea043", activeforeground="#000",
                  font=("Menlo", 11, "bold"), bd=0, padx=12, pady=3,
                  command=_create).pack(side="right", padx=(0, 8))

    def _launch_new_window(self, cmd, session):
        """Create a new tmux window in the given session with the agent."""
        _run(["tmux", "new-window", "-t", session, cmd])
        self.root.after(1500, self._refresh)

    def _launch_split(self, cmd, session, window=None):
        """Split a pane in the given session (optionally specific window)."""
        target = f"{session}:{window}" if window else session
        _run(["tmux", "split-window", "-t", target, cmd])
        self.root.after(1500, self._refresh)

    # ── Slash commands ──
    def _resolve_target(self, iid=None):
        """Resolve a tree selection to a tmux pane target.
        Works for pane, window, or session rows (picks first child pane)."""
        if iid and iid in self._targets:
            return self._targets[iid]
        # Walk children to find first pane target
        if iid:
            for child in self.tv.get_children(iid):
                t = self._resolve_target(child)
                if t:
                    return t
        return None

    def _show_slash_menu(self):
        sel = self.tv.selection()
        if not sel:
            self._interact_label.config(
                text="Select a pane first to run a / command", fg=YELLOW)
            return
        target = self._resolve_target(sel[0])
        if not target:
            self._interact_label.config(
                text="Select a pane first to run a / command", fg=YELLOW)
            return
        self._slash_menu.delete(0, tk.END)
        for cmd in SLASH_COMMANDS:
            self._slash_menu.add_command(
                label=f"  {cmd}",
                command=lambda c=cmd, t=target: self._exec_slash_command(t, c))
        self.root.update_idletasks()
        x = self._slash_btn.winfo_rootx()
        y = self._slash_btn.winfo_rooty() + self._slash_btn.winfo_height()
        try:
            self._slash_menu.tk_popup(x, y, 0)
        finally:
            self._slash_menu.grab_release()

    def _exec_slash_command(self, target, command):
        """Run a slash command in a background thread and show result in popup."""
        # Show loading indicator
        self._interact_label.config(text=f"Running {command}...", fg=ACCENT)

        def _do():
            result = _run_slash_command(target, command)
            # Tk is not thread-safe, so hand the popup back to the main thread
            # via the result queue rather than calling root.after() here.
            self._result_q.put(
                ("popup", lambda: self._show_result_popup(command, target, result)))

        threading.Thread(target=_do, daemon=True).start()

    # ── Skills ──
    def _show_skills_menu(self):
        sel = self.tv.selection()
        if not sel:
            self._interact_label.config(
                text="Select a pane first to apply a skill", fg=YELLOW)
            return
        target = self._resolve_target(sel[0])
        if not target:
            self._interact_label.config(
                text="Select a pane first to apply a skill", fg=YELLOW)
            return
        skills = get_skills()
        self._skills_menu.delete(0, tk.END)
        if not skills:
            self._skills_menu.add_command(label="  No skills found in ~/.claude/skills/",
                                           state="disabled")
        else:
            for skill in skills:
                self._skills_menu.add_command(
                    label=f"  {skill['name']}",
                    command=lambda s=skill, t=target: self._exec_skill(t, s))
        self.root.update_idletasks()
        x = self._skills_btn.winfo_rootx()
        y = self._skills_btn.winfo_rooty() + self._skills_btn.winfo_height()
        try:
            self._skills_menu.tk_popup(x, y, 0)
        finally:
            self._skills_menu.grab_release()

    def _exec_skill(self, target, skill):
        """Show a dialog to enter a user request, then send skill to pane."""
        dialog = tk.Toplevel(self.root)
        dialog.title(f"Skill: {skill['name']}")
        dialog.geometry("520x220")
        dialog.configure(bg=SURFACE)
        dialog.transient(self.root)
        dialog.grab_set()

        tk.Label(dialog, text=f"✦  {skill['name']}", bg=SURFACE, fg="#c084fc",
                 font=("Menlo", 14, "bold")).pack(pady=(14, 4), padx=16, anchor="w")
        if skill.get("description"):
            tk.Label(dialog, text=skill["description"][:120], bg=SURFACE, fg=DIM,
                     font=("Menlo", 10), wraplength=460, justify="left"
                     ).pack(padx=16, anchor="w")

        tk.Label(dialog, text="Your request (optional):", bg=SURFACE, fg=FG,
                 font=("Menlo", 11)).pack(pady=(10, 4), padx=16, anchor="w")
        entry = tk.Entry(dialog, bg=BG, fg=FG, insertbackground=ACCENT,
                         font=("Menlo", 12), bd=0, highlightbackground=BORDER,
                         highlightcolor=ACCENT, highlightthickness=1)
        entry.pack(fill="x", padx=16)
        entry.focus_set()

        def _send(_event=None):
            user_prompt = entry.get().strip()
            dialog.destroy()
            run_skill(target, skill["slug"], user_prompt)
            self._interact_label.config(
                text=f"Skill '{skill['name']}' sent to {target}", fg="#c084fc")
            self.root.after(800, self._refresh)

        entry.bind("<Return>", _send)
        btn_frame = tk.Frame(dialog, bg=SURFACE)
        btn_frame.pack(fill="x", padx=16, pady=(10, 14))
        tk.Button(btn_frame, text="Cancel", bg=BORDER, fg=FG,
                  font=("Menlo", 11), bd=0, padx=12, pady=3,
                  command=dialog.destroy).pack(side="right")
        tk.Button(btn_frame, text="Send Skill", bg="#4a1d7a", fg="#e9d5ff",
                  activebackground="#6b21a8", activeforeground="#f3e8ff",
                  font=("Menlo", 11, "bold"), bd=0, padx=12, pady=3,
                  command=_send).pack(side="right", padx=(0, 8))

    def _show_result_popup(self, command, target, result):
        self._interact_label.config(text=f"{command} completed", fg=GREEN)

        popup = tk.Toplevel(self.root)
        popup.title(f"{command}  —  {target}")
        popup.geometry("700x500")
        popup.configure(bg=BG)
        popup.transient(self.root)

        # Header
        hdr = tk.Frame(popup, bg=SURFACE)
        hdr.pack(fill="x", padx=0, pady=0)
        tk.Label(hdr, text=f"  {command}  —  {target}", bg=SURFACE, fg=ACCENT,
                 font=("Menlo", 14, "bold")).pack(side="left", pady=8, padx=8)
        tk.Button(hdr, text="Close", bg=BORDER, fg=FG,
                  font=("Menlo", 11), bd=0, padx=12, pady=4,
                  command=popup.destroy).pack(side="right", padx=8, pady=8)

        # Content
        text = tk.Text(popup, bg=SURFACE, fg=FG, font=("Menlo", 12),
                       wrap="word", bd=0, padx=16, pady=12,
                       insertbackground=ACCENT,
                       highlightbackground=BORDER, highlightthickness=1)
        sb = ttk.Scrollbar(popup, orient="vertical", command=text.yview)
        text.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        text.pack(fill="both", expand=True, padx=12, pady=(4, 12))
        text.insert("1.0", result if result.strip() else "(no output)")
        text.config(state="disabled")

        # Bind Escape to close
        popup.bind("<Escape>", lambda e: popup.destroy())

    # ── Right-click context menu (move panes) ──
    def _on_right_click(self, event):
        iid = self.tv.identify_row(event.y)
        if not iid or iid not in self._pane_data:
            return
        self.tv.selection_set(iid)
        pdata = self._pane_data[iid]
        menu_style = dict(tearoff=0, bg=SURFACE, fg=FG,
                          activebackground=SEL_BG, activeforeground="#fff",
                          font=("Menlo", 12))
        ctx = tk.Menu(self.root, **menu_style)

        # Move to → submenu with all session:window targets
        move_sub = tk.Menu(ctx, **menu_style)
        for wkey in sorted(self._window_iids.keys()):
            # Skip current window
            cur_key = f"{pdata['session']}:{pdata['win_idx']}"
            if wkey == cur_key:
                continue
            move_sub.add_command(
                label=f"  {wkey}",
                command=lambda w=wkey, pd=pdata: self._move_pane_to(pd, w))

        # "Move to new window" option
        move_sub.add_separator()
        move_sub.add_command(
            label="  \u2795 New window",
            command=lambda pd=pdata: self._break_pane(pd))
        ctx.add_cascade(label="  Move to...", menu=move_sub)

        # Reorder within window
        ctx.add_separator()
        ctx.add_command(label="  \u2191 Move Up",
                        command=lambda pd=pdata: self._swap_pane(pd, "U"))
        ctx.add_command(label="  \u2193 Move Down",
                        command=lambda pd=pdata: self._swap_pane(pd, "D"))

        # / Commands submenu
        ctx.add_separator()
        slash_sub = tk.Menu(ctx, **menu_style)
        target = pdata["target"]
        for cmd in SLASH_COMMANDS:
            slash_sub.add_command(
                label=f"  {cmd}",
                command=lambda c=cmd, t=target: self._exec_slash_command(t, c))
        ctx.add_cascade(label="  / Commands", menu=slash_sub)

        # Skills submenu
        skills = get_skills()
        if skills:
            skills_sub = tk.Menu(ctx, **menu_style)
            for skill in skills:
                skills_sub.add_command(
                    label=f"  {skill['name']}",
                    command=lambda s=skill, t=target: self._exec_skill(t, s))
            ctx.add_cascade(label="  ✦ Skills", menu=skills_sub)

        ctx.tk_popup(event.x_root, event.y_root)

    def _move_pane_to(self, pdata, target_wkey):
        """Move a pane to a different window using tmux join-pane."""
        _run(["tmux", "join-pane", "-s", pdata["pane_id"], "-t", target_wkey])
        self.root.after(800, self._refresh)

    def _break_pane(self, pdata):
        """Break a pane out into its own new window."""
        _run(["tmux", "break-pane", "-s", pdata["pane_id"]])
        self.root.after(800, self._refresh)

    def _swap_pane(self, pdata, direction):
        """Swap pane up (U) or down (D) within its window."""
        _run(["tmux", "swap-pane", "-t", pdata["target"],
              f"-{direction}"])
        self.root.after(800, self._refresh)

    def _build_footer(self):
        ft = tk.Frame(self.root, bg=BG)
        ft.pack(fill="x", padx=24, pady=(0, 14))
        tk.Label(ft, text="Double-click to attach", bg=BG, fg=DIM,
                 font=("Menlo", 11)).pack(side="left")
        self.lbl_updated = tk.Label(ft, text="", bg=BG, fg=DIM,
                                     font=("Menlo", 11))
        self.lbl_updated.pack(side="right")
        tk.Button(
            ft, text="Refresh Now", bg=BORDER, fg=FG,
            activebackground=SEL_BG, activeforeground="#fff",
            font=("Menlo", 11), bd=0, padx=12, pady=2,
            command=self._manual_refresh,
        ).pack(side="right", padx=(0, 12))

    # ── data loop ──
    def _tick(self):
        self._refresh()
        self.root.after(REFRESH_MS, self._tick)

    def _manual_refresh(self):
        self._refresh()

    def _poll_usage(self):
        """Read rate limits from ~/.claude/rate-limits.json every refresh."""
        result = _read_rate_limits()
        if result.get("five_h_pct") is not None:
            self._cached_usage = result

    def _refresh(self):
        """Gather tmux/transcript state off-thread, then apply it on the UI thread.

        All of this used to run inline on the Tk main loop every 3s, freezing
        the window (and swallowing clicks) for as long as the tmux captures and
        transcript parsing took.
        """
        if self._refreshing:
            # Don't drop it — the refresh queued right after sending keys is the
            # one showing the user the result of their click.
            self._refresh_pending = True
            return
        self._refreshing = True
        self._refresh_pending = False

        def _gather():
            try:
                panes = get_claude_panes()
                lock_owners = (_devin_lock_owners()
                               if any(p.get("agent_type") == "devin" for p in panes)
                               else {})
                pane_infos = {}
                for p in panes:
                    info = read_pane_content(p["target"], p.get("agent_type"))
                    info["agent_type"] = (p.get("agent_type")
                                          or info.get("agent_type", "claude"))
                    if info["agent_type"] == "devin":
                        info["devin_session"] = _devin_session_for_pane(
                            p["pid"], lock_owners)
                    pane_infos[p["pane_id"]] = info
                payload = (panes, pane_infos, _load_all_sessions(),
                           _read_rate_limits())
            except Exception:
                payload = None
            # Tk is not thread-safe — even root.after() from a worker thread
            # raises "main thread is not in main loop". Hand the result over a
            # queue that the main thread drains in _drain_results().
            self._result_q.put(payload)

        threading.Thread(target=_gather, daemon=True).start()

    def _drain_results(self):
        """Main-thread poll: apply any payloads the worker threads produced."""
        try:
            while True:
                item = self._result_q.get_nowait()
                # ("popup", fn) is a plain callable to run on the main thread;
                # anything else is a refresh payload.
                if isinstance(item, tuple) and item and item[0] == "popup":
                    item[1]()
                else:
                    self._apply_refresh(item)
        except queue.Empty:
            pass
        self.root.after(100, self._drain_results)

    def _apply_refresh(self, payload):
        self._refreshing = False
        if self._refresh_pending:
            self._refresh_pending = False
            self.root.after(100, self._refresh)
        if payload is None:
            return
        panes, pane_infos, all_sessions, usage = payload

        now = time.strftime("%H:%M:%S")
        self.lbl_updated.config(text=f"Last updated: {now}")
        if usage.get("five_h_pct") is not None:
            self._cached_usage = usage
        self._update_usage_panel()

        prev_sel = None
        sel = self.tv.selection()
        if sel and sel[0] in self._targets:
            prev_sel = self._targets[sel[0]]

        self._targets.clear()
        self._pane_info.clear()
        self._pane_data.clear()
        self._group_iids.clear()
        self._window_iids.clear()
        desired_iids = set()

        n = len(panes)
        self.lbl_count.config(text=f"{n} pane{'s' * (n != 1)}")

        if not panes:
            for iid in self.tv.get_children():
                self.tv.delete(iid)
            self.tv.insert("", "end", text="", tags=("dim",), values=(
                "\u2014", "\u2014", "No sessions detected",
                "\u2014", "\u2014", "Start claude inside a tmux window"))
            self._update_interact_panel()
            return

        # Group panes: session → window → panes
        groups: dict[str, dict[str, list]] = OrderedDict()
        for p in panes:
            sess = p["session"]
            win = p["win_idx"]
            groups.setdefault(sess, OrderedDict()).setdefault(win, []).append(p)

        restore_iid = None

        for sess_name, windows in groups.items():
            total_panes = sum(len(pl) for pl in windows.values())
            # Session row
            group_iid = f"group:{sess_name}"
            group_text = f"\u25b8 {sess_name}  ({total_panes} pane{'s' * (total_panes != 1)}, {len(windows)} win)"
            group_values = ("", "", "", "", "", "")
            if self.tv.exists(group_iid):
                self.tv.item(group_iid, text=group_text, tags=("group",),
                             values=group_values)
                self.tv.move(group_iid, "", "end")
            else:
                self.tv.insert("", "end", iid=group_iid, text=group_text,
                               tags=("group",), values=group_values, open=True)
            desired_iids.add(group_iid)
            self._group_iids[sess_name] = group_iid

            for win_idx, win_panes in windows.items():
                win_name = win_panes[0].get("win_name", "")
                wkey = f"{sess_name}:{win_idx}"
                # Window row
                win_iid = f"window:{sess_name}:{win_idx}"
                win_text = (f"  \u25ab Window {win_idx}: {win_name}"
                            if win_name else f"  \u25ab Window {win_idx}")
                win_values = ("", "", "", "", "", "")
                if self.tv.exists(win_iid):
                    self.tv.item(win_iid, text=win_text, tags=("window",),
                                 values=win_values)
                    self.tv.move(win_iid, group_iid, "end")
                else:
                    self.tv.insert(group_iid, "end", iid=win_iid,
                                   text=win_text, tags=("window",),
                                   values=win_values, open=True)
                desired_iids.add(win_iid)
                self._window_iids[wkey] = win_iid

                for p in win_panes:
                    pane_info = pane_infos[p["pane_id"]]
                    sid = match_pane_to_session(pane_info, all_sessions)
                    sdata = all_sessions.get(sid, {}) if sid else {}

                    default_window = (DEVIN_CONTEXT_WINDOW
                                      if pane_info.get("agent_type") == "devin"
                                      else CONTEXT_WINDOW)
                    context_window = sdata.get("context_window", default_window)
                    input_tok = sdata.get("input_tokens", 0)
                    pct = sdata.get("ctx_pct", 0)
                    if input_tok > 0:
                        ctx_str = f"{_bar(pct)} {_fmt_tokens(input_tok)}/{_fmt_tokens(context_window)} ({pct:.0f}%)"
                        tag = "ctx_green" if pct < 50 else "ctx_yellow" if pct < 80 else "ctx_red"
                    else:
                        ctx_str = f"{_bar(0)} 0/{_fmt_tokens(context_window)} (0%)"
                        tag = "ctx_green"

                    raw_model = pane_info.get("model") or sdata.get("model") or ""
                    agent_t = p.get("agent_type") or pane_info.get("agent_type", "claude")
                    if raw_model:
                        model_str = raw_model
                    elif agent_t != "claude":
                        model_str = f"[{agent_t}]"
                    else:
                        model_str = "\u2014"
                    turns = str(sdata.get("num_turns", 0))
                    status = pane_info["status"]
                    status_icons = {
                        "Idle": "\u25cf Idle", "Working": "\u25cf Working",
                        "Waiting for input": "\u25cf Waiting",
                        "Needs approval": "\u26a0 Approval",
                    }

                    iid = f"pane:{p['pane_id']}"
                    pane_values = (
                        p["pane_idx"], model_str, ctx_str, turns,
                        status_icons.get(status, status),
                        (pane_info["activity"] or "\u2014")[:80])
                    if self.tv.exists(iid):
                        self.tv.item(iid, text="", tags=(tag,), values=pane_values)
                        self.tv.move(iid, win_iid, "end")
                    else:
                        self.tv.insert(win_iid, "end", iid=iid, text="",
                                       tags=(tag,), values=pane_values)
                    desired_iids.add(iid)
                    self._targets[iid] = p["target"]
                    self._pane_info[iid] = pane_info
                    self._pane_data[iid] = {
                        "pane_id": p["pane_id"],
                        "session": p["session"],
                        "win_idx": p["win_idx"],
                        "target": p["target"],
                    }
                    if p["target"] == prev_sel:
                        restore_iid = iid

        # Delete only rows that disappeared. Stable pane IDs keep selections
        # and button targets intact while the monitor refreshes.
        def _descendants(parent=""):
            result = []
            for child in self.tv.get_children(parent):
                result.extend(_descendants(child))
                result.append(child)
            return result

        for iid in _descendants():
            if iid not in desired_iids and self.tv.exists(iid):
                self.tv.delete(iid)

        if restore_iid:
            self.tv.selection_set(restore_iid)
            self.tv.focus(restore_iid)
        self._update_interact_panel()

    def _on_dbl_click(self, _event):
        sel = self.tv.selection()
        if not sel:
            return
        iid = sel[0]
        if iid in self._targets:
            attach(self._targets[iid])
        # If it's a group row, just toggle open/close (default treeview behavior)


# ── Entry point ──────────────────────────────────────────────────────────
def main():
    if not _run(["tmux", "list-sessions"]):
        subprocess.Popen(["tmux", "new-session", "-d", "-s", "main"])
        time.sleep(0.5)
        if not _run(["tmux", "list-sessions"]):
            print("Failed to start tmux. Please start it manually.")
            sys.exit(1)
    root = tk.Tk()
    Monitor(root)
    root.mainloop()


if __name__ == "__main__":
    main()

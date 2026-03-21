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
import re
import subprocess
import sys
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
CLAUDE_DIR = os.path.expanduser("~/.claude")
PROJECTS_DIR = os.path.join(CLAUDE_DIR, "projects")

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


def _run(cmd, timeout=5):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.stdout if r.returncode == 0 else ""
    except Exception:
        return ""


def _strip(s):
    return ANSI_RE.sub("", s)


def _bar(pct, width=12):
    filled = round(pct / 100 * width)
    return "\u2588" * filled + "\u2591" * (width - filled)


def _fmt_tokens(n):
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}k"
    return str(n)


# ── JSONL session data ──────────────────────────────────────────────────
def _load_all_sessions():
    sessions = {}
    for proj_dir in glob.glob(os.path.join(PROJECTS_DIR, "*")):
        if not os.path.isdir(proj_dir):
            continue
        for jf in glob.glob(os.path.join(proj_dir, "*.jsonl")):
            sid = os.path.basename(jf).replace(".jsonl", "")
            try:
                sessions[sid] = _parse_session_jsonl(jf)
            except Exception:
                continue
    return sessions


def _parse_session_jsonl(path):
    last_usage = None
    model = None
    first_user_text = None
    total_output = 0
    num_turns = 0

    with open(path) as f:
        for line in f:
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            msg = d.get("message", {})
            if first_user_text is None and d.get("type") == "user":
                first_user_text = _extract_text(msg)
            if isinstance(msg, dict) and "usage" in msg:
                last_usage = msg["usage"]
                model = msg.get("model", model)
                total_output += last_usage.get("output_tokens", 0)
                num_turns += 1

    if not last_usage:
        return dict(model=model, input_tokens=0, output_tokens=0,
                    ctx_pct=0, first_user_msg=first_user_text or "",
                    total_output=0, num_turns=0)

    inp = last_usage.get("input_tokens", 0)
    cache_create = last_usage.get("cache_creation_input_tokens", 0)
    cache_read = last_usage.get("cache_read_input_tokens", 0)
    total_ctx = inp + cache_create + cache_read

    return dict(
        model=model, input_tokens=total_ctx,
        output_tokens=last_usage.get("output_tokens", 0),
        ctx_pct=round(total_ctx / CONTEXT_WINDOW * 100, 1) if CONTEXT_WINDOW else 0,
        first_user_msg=first_user_text or "",
        total_output=total_output, num_turns=num_turns,
    )


def _extract_text(msg):
    if isinstance(msg, str):
        return msg
    if isinstance(msg, dict):
        content = msg.get("content", "")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            for c in content:
                if isinstance(c, dict) and c.get("type") == "text":
                    return c.get("text", "")
    return ""


# ── Usage stats ────────────────────────────────────────────────────────
STATS_CACHE = os.path.join(CLAUDE_DIR, "stats-cache.json")
RATE_LIMITS_FILE = os.path.join(CLAUDE_DIR, "rate-limits.json")
USAGE_POLL_MS = 60_000  # poll /usage every 60 seconds


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
    return stats


def _scrape_usage(target):
    """Send /usage to a Claude pane, scrape the output, then close it."""
    _run(["tmux", "send-keys", "-t", target, "-l", "/usage"])
    _run(["tmux", "send-keys", "-t", target, "Enter"])
    time.sleep(4)

    # Capture full scrollback (TUI renders above visible area)
    content = _run(["tmux", "capture-pane", "-t", target, "-p", "-S", "-", "-E", "-"])

    # Close the /usage screen
    _run(["tmux", "send-keys", "-t", target, "Escape"])

    # Parse
    result = {"five_h_pct": None, "five_h_resets": None,
              "seven_d_pct": None, "seven_d_resets": None}
    lines = [_strip(l).strip() for l in content.splitlines()]

    # Find the /usage output section (look for "Current session" and "Current week")
    section = None
    for line in lines:
        low = line.lower()
        if "current session" in low:
            section = "5h"
            continue
        elif "current week" in low:
            section = "7d"
            continue
        m = re.search(r'(\d+)%\s*used', line)
        if m and section:
            pct = int(m.group(1))
            if section == "5h":
                result["five_h_pct"] = pct
            elif section == "7d":
                result["seven_d_pct"] = pct
        if low.startswith("resets") and section:
            if section == "5h":
                result["five_h_resets"] = line
                section = None
            elif section == "7d":
                result["seven_d_resets"] = line
                section = None

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
def _has_claude_descendant(pid, depth=3):
    if depth <= 0:
        return False
    out = _run(["ps", "-o", "command=", "-p", str(pid)])
    if "claude" in out.lower():
        return True
    for child in _run(["pgrep", "-P", str(pid)]).split():
        child = child.strip()
        if child and _has_claude_descendant(child, depth - 1):
            return True
    return False


def get_claude_panes():
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
        if "claude" in p["cmd"].lower() or _has_claude_descendant(p["pid"]):
            panes.append(p)
    return panes


def read_pane_content(target):
    scrollback = _run(["tmux", "capture-pane", "-t", target, "-p", "-S", "-200"])
    visible = _run(["tmux", "capture-pane", "-t", target, "-p"])
    all_lines = scrollback.splitlines() if scrollback else visible.splitlines()
    vis_lines = visible.splitlines()

    info = dict(model=None, version=None, status="Idle", activity="",
                first_user_msg=None, prompt_options=[], prompt_desc="")

    for line in all_lines:
        c = _strip(line).strip()
        if not c:
            continue
        m = re.search(r"(Opus|Sonnet|Haiku)\s+([\d.]+)\s*[·\xb7]", c, re.I)
        if m:
            info["model"] = f"{m.group(1)} {m.group(2)}"
        m = re.search(r"(claude-[\w.-]+)", c, re.I)
        if m and not info["model"]:
            info["model"] = m.group(1)
        m = re.search(r"Claude Code\s+(v[\d.]+)", c, re.I)
        if m:
            info["version"] = m.group(1)

    for i, line in enumerate(all_lines):
        c = _strip(line).strip()
        if c.startswith("\u276f") or c.startswith("❯"):
            msg_part = c.lstrip("\u276f❯ ").strip()
            if msg_part and len(msg_part) > 2:
                info["first_user_msg"] = msg_part
                break

    vis_text = "\n".join(_strip(l) for l in vis_lines)
    approval_keywords = [
        "Do you want to proceed?", "Yes, and don",
        "Allow once", "Allow always", "Deny",
        "1. Yes", "2. Yes, and don", "3. No",
        "1. Allow", "2. Allow always", "3. Deny",
    ]
    has_approval = any(kw in vis_text for kw in approval_keywords)
    if has_approval:
        info["status"] = "Needs approval"
        info["prompt_options"], info["prompt_desc"] = _parse_prompt_options(vis_lines)
    elif "❯" in vis_text or "\u276f" in vis_text:
        last_prompt_after = vis_text.split("❯")[-1] if "❯" in vis_text else ""
        if "? for shortcuts" in last_prompt_after and not last_prompt_after.strip().replace("? for shortcuts", "").replace("─", "").strip():
            info["status"] = "Idle"
        else:
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
    skip = {"? for shortcuts", "❯", "\u276f", "for shortcuts",
            "Esc to cancel", "Tab to amend"}
    for line in reversed(vis_lines[-40:]):
        c = _strip(line).strip()
        if len(c) < 4 or any(c.startswith(s) for s in skip):
            continue
        if any(k in c.lower() for k in action_stems):
            info["activity"] = c[:120]
            break

    if not info["activity"]:
        box_chars = set("─━═╔╗╚╝║│┌┐└┘├┤┬┴┼\u2500\u2501\u2550 ")
        for line in reversed(vis_lines):
            c = _strip(line).strip()
            if (c and len(c) > 3 and not any(c.startswith(s) for s in skip)
                    and not set(c) <= box_chars):
                info["activity"] = c[:120]
                break

    if not info["activity"]:
        info["activity"] = info["status"]

    return info


def _parse_prompt_options(vis_lines):
    options = []
    desc_parts = []
    for line in vis_lines:
        c = _strip(line).strip()
        if not c:
            continue
        # Capture tool/action description
        if any(kw in c for kw in ("Bash command", "Edit file", "Read file",
                                   "Write file", "Execute", "Run")):
            desc_parts.append(c)
            continue
        # Match numbered options: "1. Yes", " 2) No", "3 - Allow", etc.
        # Also handles leading special chars like ❯, >, ●, etc.
        cleaned = re.sub(r'^[^\d]*', '', c)  # strip non-digit prefix
        m = re.match(r'(\d+)\s*[.):\-]\s*(.+)', cleaned)
        if m:
            num, label = m.group(1), m.group(2).strip().rstrip(':')
            if label and len(label) > 1:
                options.append((num, label))
    # Deduplicate by option number
    seen_nums, clean = set(), []
    for num, label in options:
        if num not in seen_nums:
            seen_nums.add(num)
            clean.append((num, label))
    return clean, " ".join(desc_parts).strip()[:200]


def match_pane_to_session(pane_info, sessions):
    pane_msg = pane_info.get("first_user_msg", "")
    if not pane_msg:
        return None
    pane_msg_lower = pane_msg.lower().strip()
    best_sid, best_score = None, 0
    for sid, sdata in sessions.items():
        s_msg = sdata.get("first_user_msg", "").lower().strip()
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
]

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
        self._build()
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
            if key in ("5h", "7d"):
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
        self._esc_btn = tk.Button(
            self._btn_frame, text="Esc (Cancel)", bg="#3d1f1f", fg=RED,
            activebackground="#5c2626", activeforeground="#ff7b72",
            font=("Menlo", 10, "bold"), bd=0, padx=10, pady=3,
            command=self._send_escape)

        row2 = tk.Frame(self._interact_frame, bg=SURFACE)
        row2.pack(fill="x", padx=12, pady=(0, 8))
        tk.Label(row2, text="Type:", bg=SURFACE, fg=DIM,
                 font=("Menlo", 11)).pack(side="left")
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
        self._clear_option_buttons()

        if status == "Needs approval":
            desc = info.get("prompt_desc", "")
            options = info.get("prompt_options", [])
            label = f"Pane {pane_idx} needs approval"
            if desc:
                label += f"  \u2502  {desc[:80]}"
            self._interact_label.config(text=label, fg=YELLOW)
            for num, lbl in options:
                btn = tk.Button(
                    self._btn_frame, text=f"{num}. {lbl}", bg=BORDER, fg=FG,
                    activebackground=SEL_BG, activeforeground="#fff",
                    font=("Menlo", 10, "bold"), bd=0, padx=10, pady=3,
                    command=lambda n=num, t=target: self._send_option(t, n))
                btn.pack(side="left", padx=(0, 6))
            self._esc_btn.config(command=lambda t=target: self._send_escape(t))
            self._esc_btn.pack(side="left")
        elif status == "Waiting for input":
            self._interact_label.config(
                text=f"Pane {pane_idx} is waiting for your input", fg=ACCENT)
        elif status == "Idle":
            self._interact_label.config(
                text=f"Pane {pane_idx} is idle — type a message below", fg=GREEN)
        elif status == "Working":
            self._interact_label.config(
                text=f"Pane {pane_idx} is working...", fg=DIM)
        else:
            self._interact_label.config(text=f"Pane {pane_idx} — {status}", fg=FG)

    def _clear_option_buttons(self):
        for w in self._btn_frame.winfo_children():
            if w is not self._esc_btn:
                w.destroy()
        self._esc_btn.pack_forget()

    def _send_option(self, target, num):
        send_keys(target, num, enter=True)
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
        dialog = tk.Toplevel(self.root)
        dialog.title(f"New Session — {label}")
        dialog.geometry("400x130")
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

        def _create(_event=None):
            name = entry.get().strip()
            if not name:
                return
            name = re.sub(r"[^a-zA-Z0-9_-]", "-", name)
            dialog.destroy()
            _run(["tmux", "new-session", "-d", "-s", name, cmd])
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
        import threading

        # Show loading indicator
        self._interact_label.config(text=f"Running {command}...", fg=ACCENT)

        def _do():
            result = _run_slash_command(target, command)
            self.root.after(0, lambda: self._show_result_popup(command, target, result))

        t = threading.Thread(target=_do, daemon=True)
        t.start()

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
        """Scrape /usage from an idle Claude pane every 60s (in background)."""
        import threading

        def _do_poll():
            # Find an idle pane
            panes = get_claude_panes()
            for p in panes:
                info = read_pane_content(p["target"])
                if info["status"] in ("Idle", "Waiting for input"):
                    result = _scrape_usage(p["target"])
                    if result.get("five_h_pct") is not None:
                        self._cached_usage = result
                    break

        t = threading.Thread(target=_do_poll, daemon=True)
        t.start()
        self.root.after(USAGE_POLL_MS, self._poll_usage)

    def _refresh(self):
        now = time.strftime("%H:%M:%S")
        self.lbl_updated.config(text=f"Last updated: {now}")
        self._update_usage_panel()

        prev_sel = None
        sel = self.tv.selection()
        if sel and sel[0] in self._targets:
            prev_sel = self._targets[sel[0]]

        for i in self.tv.get_children():
            self.tv.delete(i)
        self._targets.clear()
        self._pane_info.clear()
        self._pane_data.clear()
        self._group_iids.clear()
        self._window_iids.clear()

        panes = get_claude_panes()
        n = len(panes)
        self.lbl_count.config(text=f"{n} pane{'s' * (n != 1)}")

        if not panes:
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

        all_sessions = _load_all_sessions()
        restore_iid = None

        for sess_name, windows in groups.items():
            total_panes = sum(len(pl) for pl in windows.values())
            # Session row
            group_iid = self.tv.insert(
                "", "end",
                text=f"\u25b8 {sess_name}  ({total_panes} pane{'s' * (total_panes != 1)}, {len(windows)} win)",
                tags=("group",), values=("", "", "", "", "", ""), open=True)
            self._group_iids[sess_name] = group_iid

            for win_idx, win_panes in windows.items():
                win_name = win_panes[0].get("win_name", "")
                wkey = f"{sess_name}:{win_idx}"
                # Window row
                win_iid = self.tv.insert(
                    group_iid, "end",
                    text=f"  \u25ab Window {win_idx}: {win_name}" if win_name else f"  \u25ab Window {win_idx}",
                    tags=("window",), values=("", "", "", "", "", ""), open=True)
                self._window_iids[wkey] = win_iid

                for p in win_panes:
                    pane_info = read_pane_content(p["target"])
                    sid = match_pane_to_session(pane_info, all_sessions)
                    sdata = all_sessions.get(sid, {}) if sid else {}

                    input_tok = sdata.get("input_tokens", 0)
                    pct = sdata.get("ctx_pct", 0)
                    if input_tok > 0:
                        ctx_str = f"{_bar(pct)} {_fmt_tokens(input_tok)}/{_fmt_tokens(CONTEXT_WINDOW)} ({pct:.0f}%)"
                        tag = "ctx_green" if pct < 50 else "ctx_yellow" if pct < 80 else "ctx_red"
                    else:
                        ctx_str = f"{_bar(0)} 0/{_fmt_tokens(CONTEXT_WINDOW)} (0%)"
                        tag = "ctx_green"

                    model_str = pane_info.get("model") or sdata.get("model") or "\u2014"
                    turns = str(sdata.get("num_turns", 0))
                    status = pane_info["status"]
                    status_icons = {
                        "Idle": "\u25cf Idle", "Working": "\u25cf Working",
                        "Waiting for input": "\u25cf Waiting",
                        "Needs approval": "\u26a0 Approval",
                    }

                    iid = self.tv.insert(win_iid, "end", text="", tags=(tag,), values=(
                        p["pane_idx"], model_str, ctx_str, turns,
                        status_icons.get(status, status),
                        (pane_info["activity"] or "\u2014")[:80]))
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
        print("No tmux server running. Start tmux first, then run this again.")
        sys.exit(1)
    root = tk.Tk()
    Monitor(root)
    root.mainloop()


if __name__ == "__main__":
    main()

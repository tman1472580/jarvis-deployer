"""
JSONL session data loading and usage statistics.
"""

import glob
import json
import os
import re
import time
from datetime import datetime

# ── Config ───────────────────────────────────────────────────────────────
CONTEXT_WINDOW = 200_000
CLAUDE_DIR = os.path.expanduser("~/.claude")
PROJECTS_DIR = os.path.join(CLAUDE_DIR, "projects")
CODEX_DIR = os.path.expanduser("~/.codex")
CODEX_SESSIONS_DIR = os.path.join(CODEX_DIR, "sessions")


# ── JSONL session data ──────────────────────────────────────────────────
def _load_all_sessions():
    sessions = {}
    sessions.update(_load_codex_sessions())
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


def _load_codex_sessions():
    sessions = {}
    pattern = os.path.join(CODEX_SESSIONS_DIR, "**", "*.jsonl")
    for jf in glob.glob(pattern, recursive=True):
        try:
            sessions[f"codex:{os.path.basename(jf).replace('.jsonl', '')}"] = (
                _parse_codex_session_jsonl(jf)
            )
        except Exception:
            continue
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


def _parse_session_jsonl(path):
    last_usage = None
    model = None
    first_user_text = None
    user_messages = []
    total_output = 0
    num_turns = 0

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

    if not last_usage:
        return dict(model=model, input_tokens=0, output_tokens=0,
                    ctx_pct=0, first_user_msg=first_user_text or "",
                    user_messages=user_messages,
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
    cleaned = re.sub(r"<[^>]+>", "", raw).strip()
    if cleaned.startswith("Caveat:") or not cleaned:
        return ""
    return cleaned


def match_pane_to_session(pane_info, sessions):
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


# ── Usage stats ────────────────────────────────────────────────────────
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
                            if epoch >= five_h_ago:
                                stats["five_h_messages"] += 1
                                stats["five_h_tokens"] += tok
                            if ts.startswith(today_str):
                                stats["today_messages"] += 1
                                stats["today_tokens"] += tok
                                file_has_today = True
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

    # Merge rate limits from local file (much more reliable than scraping)
    rl = _read_rate_limits()
    stats.update(rl)
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
    """Read usage percentages directly from ~/.claude/rate-limits.json."""
    result = {"five_h_pct": None, "five_h_resets": None,
              "seven_d_pct": None, "seven_d_resets": None}
    try:
        path = os.path.join(CLAUDE_DIR, "rate-limits.json")
        with open(path) as f:
            data = json.load(f)
        rl = data.get("rate_limits", {})
        five = rl.get("five_hour", {})
        seven = rl.get("seven_day", {})
        if "used_percentage" in five:
            result["five_h_pct"] = five["used_percentage"]
        if "resets_at" in five:
            result["five_h_resets"] = datetime.fromtimestamp(
                five["resets_at"]).strftime("Resets at %I:%M %p")
        if "used_percentage" in seven:
            result["seven_d_pct"] = seven["used_percentage"]
        if "resets_at" in seven:
            result["seven_d_resets"] = datetime.fromtimestamp(
                seven["resets_at"]).strftime("Resets %a %I:%M %p")
    except Exception:
        pass
    return result


def _scrape_usage(target):
    """Legacy: Send /usage to a Claude pane and scrape the output."""
    from .tmux import _run, _strip

    _run(["tmux", "send-keys", "-t", target, "-l", "/usage"])
    _run(["tmux", "send-keys", "-t", target, "Enter"])
    time.sleep(4)

    content = _run(["tmux", "capture-pane", "-t", target, "-p", "-S", "-", "-E", "-"])
    _run(["tmux", "send-keys", "-t", target, "Escape"])

    result = {"five_h_pct": None, "five_h_resets": None,
              "seven_d_pct": None, "seven_d_resets": None}
    lines = [_strip(l).strip() for l in content.splitlines()]

    import re
    section = None
    for line in lines:
        low = line.lower()
        if any(k in low for k in ("current session", "5-hour", "5 hour", "daily")):
            section = "5h"
            m = re.search(r'(\d+)%', line)
            if m:
                result["five_h_pct"] = int(m.group(1))
            continue
        elif any(k in low for k in ("current week", "weekly", "7-day", "7 day")):
            section = "7d"
            m = re.search(r'(\d+)%', line)
            if m:
                result["seven_d_pct"] = int(m.group(1))
            continue
        m = re.search(r'(\d+)%', line)
        if m and section:
            pct = int(m.group(1))
            if section == "5h" and result["five_h_pct"] is None:
                result["five_h_pct"] = pct
            elif section == "7d" and result["seven_d_pct"] is None:
                result["seven_d_pct"] = pct
        if "reset" in low and section:
            if section == "5h":
                result["five_h_resets"] = line
                section = None
            elif section == "7d":
                result["seven_d_resets"] = line
                section = None

    return result

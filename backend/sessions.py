"""
JSONL session data loading and usage statistics.
"""

import glob
import json
import os
import time
from datetime import datetime

# ── Config ───────────────────────────────────────────────────────────────
CONTEXT_WINDOW = 200_000
CLAUDE_DIR = os.path.expanduser("~/.claude")
PROJECTS_DIR = os.path.join(CLAUDE_DIR, "projects")


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
    return stats


def _scrape_usage(target):
    """Send /usage to a Claude pane, scrape the output, then close it."""
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

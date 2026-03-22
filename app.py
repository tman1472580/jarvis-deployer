#!/usr/bin/env python3
"""
Eel-based web UI for Claude Code Tmux Monitor.
Serves the Next.js static export and exposes Python backend functions.
"""

import threading
import time
from collections import OrderedDict

import eel

from backend.tmux import (
    _run, _bar, _fmt_tokens, get_claude_panes, read_pane_content,
)
from backend.sessions import (
    CONTEXT_WINDOW, _load_all_sessions, _load_usage_stats,
    _scrape_usage, match_pane_to_session,
)
from backend.commands import (
    AGENTS, SLASH_COMMANDS, send_keys, attach,
    _run_slash_command, move_pane_to, break_pane, swap_pane,
    new_session, new_window, split_window,
)

# ── Initialize Eel ──────────────────────────────────────────────────────
eel.init("frontend/out")

# Cached usage data from /usage scrape
_usage_cache = {}
_usage_cache_lock = threading.Lock()


# ── Exposed functions ────────────────────────────────────────────────────

@eel.expose
def get_full_state():
    """Return all pane data merged with JSONL session info."""
    panes = get_claude_panes()
    all_sessions = _load_all_sessions()

    # Group: session → window → panes
    groups = OrderedDict()
    for p in panes:
        sess = p["session"]
        win = p["win_idx"]
        groups.setdefault(sess, OrderedDict()).setdefault(win, []).append(p)

    result = []
    for sess_name, windows in groups.items():
        for win_idx, win_panes in windows.items():
            win_name = win_panes[0].get("win_name", "")
            for p in win_panes:
                pane_info = read_pane_content(p["target"])
                sid = match_pane_to_session(pane_info, all_sessions)
                sdata = all_sessions.get(sid, {}) if sid else {}

                input_tok = sdata.get("input_tokens", 0)
                ctx_pct = sdata.get("ctx_pct", 0)
                model_str = pane_info.get("model") or sdata.get("model") or ""
                turns = sdata.get("num_turns", 0)

                result.append({
                    "session": sess_name,
                    "win_idx": win_idx,
                    "win_name": win_name,
                    "pane_idx": p["pane_idx"],
                    "pane_id": p["pane_id"],
                    "target": p["target"],
                    "model": model_str,
                    "input_tokens": input_tok,
                    "context_pct": ctx_pct,
                    "context_window": CONTEXT_WINDOW,
                    "turns": turns,
                    "status": pane_info["status"],
                    "activity": pane_info.get("activity", ""),
                    "prompt_options": pane_info.get("prompt_options", []),
                    "prompt_desc": pane_info.get("prompt_desc", ""),
                    "first_user_msg": pane_info.get("first_user_msg", ""),
                })

    return result


@eel.expose
def get_usage_stats():
    """Return aggregated usage stats from JSONL + cached /usage scrape."""
    stats = _load_usage_stats()
    with _usage_cache_lock:
        stats.update(_usage_cache)
    return stats


@eel.expose
def run_send_keys(target, text, enter=True):
    """Send text to a tmux pane."""
    send_keys(target, text, enter=enter)


@eel.expose
def run_attach(target):
    """Open terminal and attach to a tmux pane."""
    attach(target)


@eel.expose
def run_slash_command(target, cmd):
    """Execute a slash command in a pane and return the output."""
    return _run_slash_command(target, cmd)


@eel.expose
def run_send_option(target, num):
    """Send an approval option number to a pane."""
    send_keys(target, str(num), enter=True)


@eel.expose
def run_send_escape(target):
    """Send Escape key to a pane."""
    _run(["tmux", "send-keys", "-t", target, "Escape"])


@eel.expose
def launch_new_session(cmd, name):
    """Create a new tmux session."""
    new_session(cmd, name)


@eel.expose
def launch_new_window(cmd, session):
    """Create a new window in a session."""
    new_window(cmd, session)


@eel.expose
def launch_split(cmd, session, window=None):
    """Split a pane in a session."""
    split_window(cmd, session, window)


@eel.expose
def run_move_pane(pane_id, target):
    """Move a pane to a different window."""
    move_pane_to(pane_id, target)


@eel.expose
def run_break_pane(pane_id):
    """Break a pane into its own window."""
    break_pane(pane_id)


@eel.expose
def run_swap_pane(target, direction):
    """Swap pane up/down within its window."""
    swap_pane(target, direction)


@eel.expose
def get_agents():
    """Return list of available agents."""
    return [{"label": label, "cmd": cmd} for label, cmd in AGENTS]


@eel.expose
def get_slash_commands():
    """Return list of slash commands."""
    return SLASH_COMMANDS


# ── Background usage poller ──────────────────────────────────────────────

def _usage_poller():
    """Poll /usage from an idle Claude pane every 60s."""
    while True:
        time.sleep(60)
        try:
            panes = get_claude_panes()
            for p in panes:
                info = read_pane_content(p["target"])
                if info["status"] in ("Idle", "Waiting for input"):
                    result = _scrape_usage(p["target"])
                    if result.get("five_h_pct") is not None:
                        with _usage_cache_lock:
                            _usage_cache.update(result)
                    break
        except Exception:
            pass


# ── Entry point ──────────────────────────────────────────────────────────

def main():
    if not _run(["tmux", "list-sessions"]):
        print("No tmux server running. Start tmux first, then run this again.")
        return

    # Start background usage poller
    poller = threading.Thread(target=_usage_poller, daemon=True)
    poller.start()

    # Start Eel server without auto-opening browser, print URL
    print("Starting server on http://localhost:8178")
    eel.start("index.html", size=(1400, 900), port=8178, mode=None, block=False)
    print("Server running at http://localhost:8178")
    print("Opening in browser...")
    import webbrowser
    webbrowser.open("http://localhost:8178")

    # Block forever (until Ctrl+C)
    try:
        while True:
            eel.sleep(1.0)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()

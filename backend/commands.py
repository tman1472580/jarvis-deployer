"""
Slash commands, send keys, attach, pane management, session launching.
"""

import re
import subprocess
import time

from .tmux import _run, _strip

# ── Agent definitions ────────────────────────────────────────────────────
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


# ── Send keys ────────────────────────────────────────────────────────────
def send_keys(target, text, enter=False):
    _run(["tmux", "send-keys", "-t", target, "-l", text])
    if enter:
        _run(["tmux", "send-keys", "-t", target, "Enter"])


# ── Pane selection ──────────────────────────────────────────────────────
def select_pane(target):
    """Select a pane in tmux (window + pane) without opening a terminal."""
    session_window = target.rsplit(".", 1)[0]
    _run(["tmux", "select-window", "-t", session_window])
    _run(["tmux", "select-pane", "-t", target])


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
    # Select pane right before attach so there's no race condition
    attach_cmd = (
        f"tmux select-window -t '{session_window}' && "
        f"tmux select-pane -t '{target}' && "
        f"tmux attach-session -t '{session}'"
    )
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


# ── Slash command execution ──────────────────────────────────────────────
def _run_slash_command(target, command):
    """Send a slash command to a pane and capture the output."""
    before = _run(["tmux", "capture-pane", "-t", target, "-p", "-S", "-", "-E", "-"])
    before_lines = before.splitlines()
    before_len = len(before_lines)

    _run(["tmux", "send-keys", "-t", target, "-l", command])
    _run(["tmux", "send-keys", "-t", target, "Enter"])

    time.sleep(2)
    last_len = 0
    for _ in range(4):
        snap = _run(["tmux", "capture-pane", "-t", target, "-p", "-S", "-", "-E", "-"])
        cur_len = len(snap.splitlines())
        if cur_len == last_len and cur_len != before_len:
            break
        last_len = cur_len
        time.sleep(1)

    visible = _run(["tmux", "capture-pane", "-t", target, "-p"])
    after = _run(["tmux", "capture-pane", "-t", target, "-p", "-S", "-", "-E", "-"])
    after_lines = after.splitlines()
    new_lines = after_lines[max(0, before_len - 2):]

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

    if len(visible_result) > len(scroll_result) + 2:
        result_lines = visible_result
    else:
        result_lines = scroll_result

    _run(["tmux", "send-keys", "-t", target, "Escape"])
    time.sleep(0.3)
    _run(["tmux", "send-keys", "-t", target, "Escape"])

    return "\n".join(result_lines)


# ── Pane management ─────────────────────────────────────────────────────
def move_pane_to(pane_id, target_wkey):
    """Move a pane to a different window using tmux join-pane."""
    _run(["tmux", "join-pane", "-s", pane_id, "-t", target_wkey])


def break_pane(pane_id):
    """Break a pane out into its own new window."""
    _run(["tmux", "break-pane", "-s", pane_id])


def swap_pane(target, direction):
    """Swap pane up (U) or down (D) within its window."""
    _run(["tmux", "swap-pane", "-t", target, f"-{direction}"])


# ── Session launching ────────────────────────────────────────────────────
def new_session(cmd, name):
    """Create a brand new tmux session running the given agent."""
    name = re.sub(r"[^a-zA-Z0-9_-]", "-", name)
    _run(["tmux", "new-session", "-d", "-s", name, cmd])


def new_window(cmd, session):
    """Create a new tmux window in the given session with the agent."""
    _run(["tmux", "new-window", "-t", session, cmd])


def split_window(cmd, session, window=None):
    """Split a pane in the given session (optionally specific window)."""
    target = f"{session}:{window}" if window else session
    _run(["tmux", "split-window", "-t", target, cmd])


def kill_session(session):
    """Kill an entire tmux session."""
    _run(["tmux", "kill-session", "-t", session])

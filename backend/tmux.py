"""
Tmux introspection — pane discovery, content reading, status detection.
"""

import re
import subprocess

# ── Utilities ────────────────────────────────────────────────────────────
ANSI_RE = re.compile(
    r"\x1b(?:\[[0-9;]*[a-zA-Z]|\][^\x07]*\x07|[()][AB012]|\[\??\d*[hl])"
)

# All agent CLI names to detect
AGENT_KEYWORDS = ["claude", "gemini", "codex"]


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


def get_claude_panes():
    """Return all panes running any supported agent (Claude, Gemini, Codex)."""
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
        # Detect agent from command name first (fast path)
        cmd_lower = p["cmd"].lower()
        agent_kw = next((kw for kw in AGENT_KEYWORDS if kw in cmd_lower), None)
        # Fallback: walk process tree (handles node-wrapped CLIs like gemini)
        if not agent_kw:
            agent_kw = _detect_agent_from_proc(p["pid"])
        if agent_kw:
            p["agent_type"] = agent_kw
            panes.append(p)
    return panes


def _is_gemini_idle(vis_lines):
    """Check if the last non-empty visible line is a bare Gemini "> " prompt."""
    for line in reversed(vis_lines):
        c = _strip(line).strip()
        if c:
            return c == ">" or c.startswith("> ")
    return False


def _is_gemini_waiting(vis_lines):
    """Check if Gemini is waiting for multi-line input or a follow-up."""
    for line in reversed(vis_lines[-10:]):
        c = _strip(line).strip()
        if c and (c.endswith("?") or "continue" in c.lower() or "enter" in c.lower()):
            return True
    return False


def read_pane_content(target):
    scrollback = _run(["tmux", "capture-pane", "-t", target, "-p", "-S", "-200"])
    visible = _run(["tmux", "capture-pane", "-t", target, "-p"])
    all_lines = scrollback.splitlines() if scrollback else visible.splitlines()
    vis_lines = visible.splitlines()

    info = dict(model=None, version=None, status="Idle", activity="",
                first_user_msg=None, prompt_options=[], prompt_desc="",
                agent_type="claude")

    for line in all_lines:
        c = _strip(line).strip()
        if not c:
            continue
        # Claude model detection
        m = re.search(r"(Opus|Sonnet|Haiku)\s+([\d.]+)\s*[·\xb7]", c, re.I)
        if m:
            info["model"] = f"{m.group(1)} {m.group(2)}"
        m = re.search(r"(claude-[\w.-]+)", c, re.I)
        if m and not info["model"]:
            info["model"] = m.group(1)
        m = re.search(r"Claude Code\s+(v[\d.]+)", c, re.I)
        if m:
            info["version"] = m.group(1)
        # Gemini model detection
        m = re.search(r"(gemini-[\w.-]+)", c, re.I)
        if m:
            info["model"] = m.group(1)
            info["agent_type"] = "gemini"
        if re.search(r"\bgemini\b", c, re.I) and not info["model"]:
            info["agent_type"] = "gemini"
        # Codex model detection
        m = re.search(r"(codex-[\w.-]+|gpt-[\w.-]+)", c, re.I)
        if m and info["agent_type"] == "claude":
            info["model"] = m.group(1)
            info["agent_type"] = "codex"

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
    elif _is_gemini_idle(vis_lines):
        # Gemini CLI uses "> " as its idle prompt
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
        if any(kw in c for kw in ("Bash command", "Edit file", "Read file",
                                   "Write file", "Execute", "Run")):
            desc_parts.append(c)
            continue
        cleaned = re.sub(r'^[^\d]*', '', c)
        m = re.match(r'(\d+)\s*[.):\-]\s*(.+)', cleaned)
        if m:
            num, label = m.group(1), m.group(2).strip().rstrip(':')
            if label and len(label) > 1:
                options.append((num, label))
    seen_nums, clean = set(), []
    for num, label in options:
        if num not in seen_nums:
            seen_nums.add(num)
            clean.append((num, label))
    return clean, " ".join(desc_parts).strip()[:200]

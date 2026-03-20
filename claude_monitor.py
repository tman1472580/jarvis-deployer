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
    has_approval = ("Do you want to proceed?" in vis_text
                    or "Yes, and don" in vis_text)
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
    in_desc = False
    for line in vis_lines:
        c = _strip(line).strip()
        if not c:
            continue
        if any(kw in c for kw in ("Bash command", "Edit file", "Read file", "Write file")):
            in_desc = True
            desc_parts.append(c)
            continue
        if in_desc and "Do you want to proceed?" not in c:
            if re.match(r"^\d+\.", c):
                in_desc = False
            else:
                desc_parts.append(c)
        m = re.match(r"(\d+)\.\s*(.+)", c)
        if m:
            num, label = m.group(1), re.sub(r"\s*:\s*$", "", m.group(2).strip())
            if label and len(label) > 1:
                options.append((num, label))
    seen, clean = set(), []
    for num, label in options:
        short = label[:20]
        if short not in seen:
            seen.add(short)
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
COLUMNS = ("session", "pane", "model", "context", "turns", "status", "activity")
COL_WIDTHS = dict(session=100, pane=55, model=140, context=250,
                   turns=65, status=120, activity=420)


class Monitor:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title("Claude Session Monitor")
        root.geometry("1260x620")
        root.configure(bg=BG)
        root.minsize(900, 400)
        self._targets: dict[str, str] = {}
        self._pane_info: dict[str, dict] = {}
        self._build()
        self._tick()

    def _build(self):
        self._apply_theme()
        self._build_header()
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

    def _build_table(self):
        container = tk.Frame(self.root, bg=BG)
        container.pack(fill="both", expand=True, padx=24, pady=8)

        self.tv = ttk.Treeview(
            container, columns=COLUMNS, show="headings", selectmode="browse")
        sb = ttk.Scrollbar(container, orient="vertical", command=self.tv.yview)
        self.tv.configure(yscrollcommand=sb.set)

        headings = dict(session="Session", pane="Pane", model="Model",
                        context="Context Window", turns="Turns",
                        status="Status", activity="Activity")
        for col in COLUMNS:
            self.tv.heading(col, text=headings[col])
            self.tv.column(col, width=COL_WIDTHS[col], minwidth=50)

        for tag, color in [("ctx_green", GREEN), ("ctx_yellow", YELLOW),
                           ("ctx_red", RED), ("dim", DIM)]:
            self.tv.tag_configure(tag, foreground=color)

        self.tv.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.tv.bind("<Double-1>", self._on_dbl_click)
        self.tv.bind("<<TreeviewSelect>>", self._on_select)

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
            self._interact_label.config(text="Select a session above", fg=DIM)
            self._clear_option_buttons()
            return
        iid = sel[0]
        target = self._targets[iid]
        info = self._pane_info.get(iid, {})
        status = info.get("status", "")
        pane_idx = self.tv.item(iid, "values")[1]
        self._clear_option_buttons()

        if status == "Needs approval":
            desc = info.get("prompt_desc", "")
            options = info.get("prompt_options", [])
            label = f"Pane {pane_idx} needs approval"
            if desc:
                label += f"  \u2502  {desc[:80]}"
            self._interact_label.config(text=label, fg=YELLOW)
            colors = {"1": (GREEN, "#143d1f"), "2": (YELLOW, "#3d2f00"),
                      "3": (RED, "#3d1f1f")}
            for num, lbl in options:
                fg_c, bg_c = colors.get(num, (FG, BORDER))
                btn = tk.Button(
                    self._btn_frame, text=f"{num}. {lbl}", bg=bg_c, fg=fg_c,
                    activebackground=BORDER, activeforeground="#fff",
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

    def _refresh(self):
        now = time.strftime("%H:%M:%S")
        self.lbl_updated.config(text=f"Last updated: {now}")

        prev_sel = None
        sel = self.tv.selection()
        if sel and sel[0] in self._targets:
            prev_sel = self._targets[sel[0]]

        for i in self.tv.get_children():
            self.tv.delete(i)
        self._targets.clear()
        self._pane_info.clear()

        panes = get_claude_panes()
        n = len(panes)
        self.lbl_count.config(text=f"{n} session{'s' * (n != 1)}")

        if not panes:
            self.tv.insert("", "end", tags=("dim",), values=(
                "\u2014", "\u2014", "\u2014", "No sessions detected",
                "\u2014", "\u2014", "Start claude inside a tmux window"))
            self._update_interact_panel()
            return

        all_sessions = _load_all_sessions()
        restore_iid = None

        for p in panes:
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

            iid = self.tv.insert("", "end", tags=(tag,), values=(
                p["session"], p["pane_idx"], model_str, ctx_str, turns,
                status_icons.get(status, status),
                (pane_info["activity"] or "\u2014")[:80]))
            self._targets[iid] = p["target"]
            self._pane_info[iid] = pane_info
            if p["target"] == prev_sel:
                restore_iid = iid

        if restore_iid:
            self.tv.selection_set(restore_iid)
            self.tv.focus(restore_iid)
        self._update_interact_panel()

    def _on_dbl_click(self, _event):
        sel = self.tv.selection()
        if sel and sel[0] in self._targets:
            attach(self._targets[sel[0]])


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

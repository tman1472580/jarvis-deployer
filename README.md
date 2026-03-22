# Jarvis Deployer

Real-time web dashboard for monitoring and controlling Claude Code sessions running in tmux.

## How It Works

The app has three layers:

1. **Python Backend** (`app.py` + `backend/`) — Uses [Eel](https://github.com/python-eel/Eel) to bridge Python and the browser. Introspects tmux to discover Claude Code panes, reads JSONL session files for token/context data, and reads `~/.claude/rate-limits.json` for usage percentages. Exposes all functionality as `@eel.expose` functions callable from JavaScript.

2. **Next.js Frontend** (`frontend/`) — A statically exported Next.js app with a sci-fi HUD interface. Polls the backend every 3s for pane state and every 2 min for usage stats. Each tmux session appears as a draggable folder card you can stack, minimize, and rearrange.

3. **Tmux** — The actual Claude Code sessions. The backend discovers panes running Claude, reads their content for status detection (idle, working, needs approval, waiting for input), and can send keystrokes, slash commands, or kill sessions.

### Key Features

- **Live status monitoring** — See which Claude sessions are idle, working, waiting for input, or need approval
- **Usage bars** — 5-hour and 7-day usage percentages read directly from `~/.claude/rate-limits.json`
- **Send prompts** — Click a card to select it, type in the bottom prompt bar to send text to that pane
- **Approval handling** — See approval prompts and send option numbers directly from the UI
- **Pane selection** — Clicking a card selects the corresponding tmux pane so switching to your terminal lands on the right one
- **Double-click to attach** — Opens your terminal (iTerm2 or Terminal.app) attached to that exact session and pane
- **Session management** — Launch new sessions, create windows, split panes, close/kill sessions
- **Slash commands** — Right-click a card to run `/usage`, `/status`, `/compact`, `/cost`, `/model`
- **Drag and drop** — Drag folder tabs to reorganize, stack sessions together, or break them apart

## Prerequisites

- **macOS** (uses AppleScript for terminal integration)
- **tmux** — Must be running with at least one session
- **Python 3.10+**
- **Node.js 18+** and **pnpm** (for frontend development/building)

## Quick Start

```bash
# 1. Clone
git clone git@github.com:tman1472580/jarvis-deployer.git
cd jarvis-deployer

# 2. Install Python dependency
pip install eel

# 3. Make sure tmux is running
tmux new-session -d -s my-session

# 4. Run
python3 app.py
```

The dashboard opens at **http://localhost:8178**.

## Frontend Development

The frontend is pre-built in `frontend/out/`. To modify it:

```bash
cd frontend

# Install dependencies
pnpm install

# Dev server (hot reload, but won't connect to Eel backend)
pnpm dev

# Build static export (required for the Eel app to serve)
pnpm build
```

After building, restart `python3 app.py` to pick up the new frontend.

## Project Structure

```
jarvis-deployer/
  app.py                  # Eel server — entry point
  requirements.txt        # Python dependencies (eel)
  backend/
    tmux.py               # Tmux pane discovery and content parsing
    sessions.py           # JSONL session data, usage stats, rate limits
    commands.py           # Send keys, attach, pane management, session ops
  frontend/
    pages/                # Next.js pages (Pages Router)
    components/jarvis/    # UI components (HUD header, task folders, prompt bar)
    hooks/use-eel.ts      # React hook for polling backend state
    lib/eel-bridge.ts     # Typed wrappers for Eel-exposed Python functions
    out/                  # Static export (served by Eel)
```

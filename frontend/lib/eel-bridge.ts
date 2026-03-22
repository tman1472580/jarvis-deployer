/**
 * Typed wrappers for Python @eel.expose functions.
 * Eel injects window.eel at runtime via /eel.js.
 *
 * Eel calling convention: eel.py_function(args)()
 *   - First () sends the call over websocket, returns a thunk
 *   - Second () calls the thunk with no args, returns a Promise
 */

// ── Data interfaces ─────────────────────────────────────────────────────

export interface PaneData {
  session: string
  win_idx: string
  win_name: string
  pane_idx: string
  pane_id: string
  target: string
  model: string
  input_tokens: number
  context_pct: number
  context_window: number
  turns: number
  status: "Idle" | "Working" | "Needs approval" | "Waiting for input"
  activity: string
  prompt_options: [string, string][]  // [num, label]
  prompt_desc: string
  first_user_msg: string
}

export interface UsageStats {
  today_messages: number
  today_tokens: number
  today_sessions: number
  week_messages: number
  week_tokens: number
  week_sessions: number
  five_h_messages: number
  five_h_tokens: number
  subscription: string | null
  tier: string | null
  five_h_pct: number | null
  seven_d_pct: number | null
  five_h_resets: string | null
  seven_d_resets: string | null
}

export interface AgentDef {
  label: string
  cmd: string
}

// ── Helper: safe eel call ───────────────────────────────────────────────

function eelReady(): boolean {
  return typeof window !== "undefined" && !!window.eel
}

/**
 * Safely call an Eel-exposed Python function.
 * @param fn - A function that calls the eel method and returns the thunk
 *             e.g. () => window.eel.get_full_state()
 * @param fallback - Value to return if eel isn't ready or call fails
 */
async function callEel<T>(fn: () => any, fallback: T): Promise<T> {
  if (!eelReady()) return fallback
  try {
    // fn() calls the eel function → returns a thunk
    // thunk() with no args → returns a Promise
    const thunk = fn()
    const result = await thunk()
    return result !== undefined && result !== null ? result : fallback
  } catch {
    return fallback
  }
}

// ── Typed wrappers ──────────────────────────────────────────────────────

export const eel = {
  isReady: eelReady,

  getFullState: () =>
    callEel<PaneData[]>(() => window.eel.get_full_state(), []),

  refreshUsage: () =>
    callEel<UsageStats>(() => window.eel.refresh_usage(), {
      today_messages: 0, today_tokens: 0, today_sessions: 0,
      week_messages: 0, week_tokens: 0, week_sessions: 0,
      five_h_messages: 0, five_h_tokens: 0,
      subscription: null, tier: null,
      five_h_pct: null, seven_d_pct: null,
      five_h_resets: null, seven_d_resets: null,
    }),

  getUsageStats: () =>
    callEel<UsageStats>(() => window.eel.get_usage_stats(), {
      today_messages: 0, today_tokens: 0, today_sessions: 0,
      week_messages: 0, week_tokens: 0, week_sessions: 0,
      five_h_messages: 0, five_h_tokens: 0,
      subscription: null, tier: null,
      five_h_pct: null, seven_d_pct: null,
      five_h_resets: null, seven_d_resets: null,
    }),

  sendKeys: (target: string, text: string, enter = true) =>
    callEel(() => window.eel.run_send_keys(target, text, enter), undefined),

  selectPane: (target: string) =>
    callEel(() => window.eel.run_select_pane(target), undefined),

  attach: (target: string) =>
    callEel(() => window.eel.run_attach(target), undefined),

  slashCommand: (target: string, cmd: string) =>
    callEel<string>(() => window.eel.run_slash_command(target, cmd), ""),

  sendOption: (target: string, num: string) =>
    callEel(() => window.eel.run_send_option(target, num), undefined),

  sendEscape: (target: string) =>
    callEel(() => window.eel.run_send_escape(target), undefined),

  launchNewSession: (cmd: string, name: string) =>
    callEel(() => window.eel.launch_new_session(cmd, name), undefined),

  launchNewWindow: (cmd: string, session: string) =>
    callEel(() => window.eel.launch_new_window(cmd, session), undefined),

  launchSplit: (cmd: string, session: string, win?: string) =>
    callEel(() => window.eel.launch_split(cmd, session, win), undefined),

  movePane: (paneId: string, target: string) =>
    callEel(() => window.eel.run_move_pane(paneId, target), undefined),

  breakPane: (paneId: string) =>
    callEel(() => window.eel.run_break_pane(paneId), undefined),

  swapPane: (target: string, direction: string) =>
    callEel(() => window.eel.run_swap_pane(target, direction), undefined),

  killSession: (session: string) =>
    callEel(() => window.eel.run_kill_session(session), undefined),

  getAgents: () =>
    callEel<AgentDef[]>(() => window.eel.get_agents(), []),

  getSlashCommands: () =>
    callEel<string[]>(() => window.eel.get_slash_commands(), []),
}

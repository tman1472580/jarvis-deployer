"use client"

import { useState, useCallback, useRef, useEffect } from "react"
import { HudBackground } from "@/components/jarvis/hud-background"
import { HudHeader } from "@/components/jarvis/hud-header"
import { TaskFolder } from "@/components/jarvis/task-folder"
import { PromptBar } from "@/components/jarvis/prompt-bar"
import { useEelState } from "@/hooks/use-eel"
import { eel, type PaneData } from "@/lib/eel-bridge"

const BUILD_VERSION = "v4-eel-2026-03-21"

interface TerminalEntry {
  type: "user" | "assistant" | "system"
  content: string
  timestamp?: string
}

export interface TaskData {
  id: string
  session: string
  pane: string
  target: string
  pane_id: string
  model: string
  contextUsed: number
  contextTotal: number
  turns: number
  status: "Idle" | "Waiting" | "Processing" | "Approval"
  activity: string
  terminalHistory?: TerminalEntry[]
  prompt_options: [string, string][]
  prompt_desc: string
}

interface FolderStack {
  id: string
  taskIds: string[]
  position: { x: number; y: number }
  size: { width: number; height: number }
  isMinimized: boolean
  savedPosition?: { x: number; y: number }
}

// Map PaneData status to TaskData status
function mapStatus(s: string): TaskData["status"] {
  switch (s) {
    case "Idle": return "Idle"
    case "Working": return "Processing"
    case "Needs approval": return "Approval"
    case "Waiting for input": return "Waiting"
    default: return "Idle"
  }
}

// Convert PaneData[] to TaskData[]
function panesToTasks(panes: PaneData[]): TaskData[] {
  if (!Array.isArray(panes)) return []
  return panes.map(p => ({
    id: `${p.session}:${p.win_idx}.${p.pane_idx}`,
    session: p.session,
    pane: p.pane_idx,
    target: p.target,
    pane_id: p.pane_id,
    model: p.model || "Unknown",
    contextUsed: p.input_tokens / 1000,
    contextTotal: p.context_window / 1000,
    turns: p.turns,
    status: mapStatus(p.status),
    activity: p.activity || p.status,
    prompt_options: p.prompt_options,
    prompt_desc: p.prompt_desc,
  }))
}

// Group tasks by tmux session into FolderStacks
function tasksToFolderStacks(tasks: TaskData[], existing: FolderStack[]): FolderStack[] {
  // Group tasks by session name
  const bySession = new Map<string, string[]>()
  for (const t of tasks) {
    const ids = bySession.get(t.session) || []
    ids.push(t.id)
    bySession.set(t.session, ids)
  }

  const result: FolderStack[] = []
  let col = 0
  const totalSessions = bySession.size
  // Spread folders across available width with no overlap
  const folderWidth = 380
  const gap = 20
  const startX = 40
  for (const [sessName, taskIds] of bySession) {
    const prev = existing.find(f => f.id === `sess-${sessName}`)
    // Stagger vertically for better visibility
    const row = Math.floor(col / 3)
    const colInRow = col % 3
    result.push({
      id: `sess-${sessName}`,
      taskIds,
      position: prev?.position ?? { x: startX + colInRow * (folderWidth + gap), y: 120 + row * 340 },
      size: prev?.size ?? { width: folderWidth, height: 300 },
      isMinimized: prev?.isMinimized ?? false,
      savedPosition: prev?.savedPosition,
    })
    col++
  }
  return result
}

const generateFolderId = () => `f-${Date.now()}-${Math.random().toString(36).slice(2, 11)}`

function fmtTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`
  return String(n)
}

export default function AICommandCenter() {
  const { panes, usageStats, connected, refresh } = useEelState()
  const [tasks, setTasks] = useState<TaskData[]>([])
  const [folderStacks, setFolderStacks] = useState<FolderStack[]>([])
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null)
  const [zIndices, setZIndices] = useState<number[]>([])
  const [maxZ, setMaxZ] = useState(0)
  const [dragTargetFolderId, setDragTargetFolderId] = useState<string | null>(null)
  const [slashDialogResult, setSlashDialogResult] = useState<{ cmd: string; result: string } | null>(null)
  const folderRefs = useRef<Map<string, DOMRect>>(new Map())
  const [mountKey] = useState(() => `${BUILD_VERSION}-${Date.now()}`)
  const prevFolderStacksRef = useRef<FolderStack[]>([])
  const [hiddenFolderIds, setHiddenFolderIds] = useState<Set<string>>(new Set())

  // Update tasks and folder stacks when panes change
  useEffect(() => {
    const newTasks = panesToTasks(panes)
    setTasks(newTasks)
    setFolderStacks(prev => {
      const updated = tasksToFolderStacks(newTasks, prev)
        .filter(s => !hiddenFolderIds.has(s.id))
      // Preserve z-indices
      if (updated.length !== prev.length) {
        setZIndices(updated.map((_, i) => i + 1))
        setMaxZ(updated.length)
      }
      prevFolderStacksRef.current = updated
      return updated
    })
  }, [panes, hiddenFolderIds])

  const tasksMap = new Map(tasks.map(t => [t.id, t]))
  const selectedTask = selectedTaskId ? tasksMap.get(selectedTaskId) : null

  // Count tasks by status
  const statusCounts = tasks.reduce((acc, task) => {
    acc[task.status] = (acc[task.status] || 0) + 1
    return acc
  }, {} as Record<string, number>)

  const minimizedFolders = folderStacks
    .map((stack, index) => ({ stack, index }))
    .filter(({ stack }) => stack.isMinimized)

  const handleSendPrompt = useCallback(async (message: string) => {
    if (!selectedTask) return
    await eel.sendKeys(selectedTask.target, message, true)
    setTimeout(refresh, 800)
  }, [selectedTask, refresh])

  const handleSendOption = useCallback(async (num: string) => {
    if (!selectedTask) return
    await eel.sendOption(selectedTask.target, num)
    setTimeout(refresh, 800)
  }, [selectedTask, refresh])

  const handleSendEscape = useCallback(async () => {
    if (!selectedTask) return
    await eel.sendEscape(selectedTask.target)
    setTimeout(refresh, 800)
  }, [selectedTask, refresh])

  const handleAttach = useCallback(async (taskId: string) => {
    const task = tasksMap.get(taskId)
    if (task) await eel.attach(task.target)
  }, [tasksMap])

  const handleSlashCommand = useCallback(async (target: string, cmd: string) => {
    const result = await eel.slashCommand(target, cmd)
    setSlashDialogResult({ cmd, result })
  }, [])

  const handleAddTask = useCallback(async (agentCmd: string, agentLabel: string) => {
    const name = `${agentLabel.replace(/\s+/g, "-")}-${Date.now().toString(36).slice(-4)}`
    await eel.launchNewSession(agentCmd, name)
    setTimeout(refresh, 1500)
  }, [refresh])

  const handleNewWindow = useCallback(async (agentCmd: string, session: string) => {
    await eel.launchNewWindow(agentCmd, session)
    setTimeout(refresh, 1500)
  }, [refresh])

  const handleSplitPane = useCallback(async (agentCmd: string, session: string) => {
    await eel.launchSplit(agentCmd, session)
    setTimeout(refresh, 1500)
  }, [refresh])

  // ── Folder management callbacks (unchanged drag/drop logic) ──
  const handlePositionChange = useCallback((stackIndex: number, pos: { x: number; y: number }) => {
    setFolderStacks(prev => {
      const newStacks = [...prev]
      newStacks[stackIndex] = { ...newStacks[stackIndex], position: pos }
      return newStacks
    })
  }, [])

  const handleSizeChange = useCallback((stackIndex: number, size: { width: number; height: number }) => {
    setFolderStacks(prev => {
      const newStacks = [...prev]
      newStacks[stackIndex] = { ...newStacks[stackIndex], size }
      return newStacks
    })
  }, [])

  const bringToFront = useCallback((stackIndex: number) => {
    setMaxZ(prev => {
      const newZ = prev + 1
      setZIndices(prevIndices => {
        const newIndices = [...prevIndices]
        newIndices[stackIndex] = newZ
        return newIndices
      })
      return newZ
    })
  }, [])

  const handleStackItemClick = useCallback((stackIndex: number, taskId: string) => {
    setFolderStacks(prev => {
      const newStacks = [...prev]
      const stack = newStacks[stackIndex]
      const currentIndex = stack.taskIds.indexOf(taskId)
      if (currentIndex > 0) {
        const newTaskIds = [...stack.taskIds]
        newTaskIds.splice(currentIndex, 1)
        newTaskIds.unshift(taskId)
        newStacks[stackIndex] = { ...stack, taskIds: newTaskIds }
      }
      return newStacks
    })
    setSelectedTaskId(taskId)
    bringToFront(stackIndex)
  }, [bringToFront])

  const handleStackItemDragOut = useCallback((stackIndex: number, taskId: string, position: { x: number; y: number }) => {
    let targetFolderId: string | null = null
    const droppedTabX = position.x
    const droppedTabY = position.y

    folderStacks.forEach((stack, idx) => {
      if (idx === stackIndex || stack.isMinimized) return
      const targetTabX = stack.position.x + 8
      const targetTabY = stack.position.y - 16
      const overlapThreshold = 40
      const tabsOverlap = (
        droppedTabX < targetTabX + 160 + overlapThreshold &&
        droppedTabX + 100 > targetTabX - overlapThreshold &&
        droppedTabY < targetTabY + 16 + overlapThreshold &&
        droppedTabY + 16 > targetTabY - overlapThreshold
      )
      if (tabsOverlap) targetFolderId = stack.id
    })

    const newFolderId = generateFolderId()

    setFolderStacks(prev => {
      const newStacks = prev.map(stack => ({ ...stack, taskIds: [...(stack.taskIds || [])] }))
      const sourceStackIdx = newStacks.findIndex(s => (s.taskIds || []).includes(taskId))
      if (sourceStackIdx === -1) return prev
      newStacks[sourceStackIdx].taskIds = newStacks[sourceStackIdx].taskIds.filter(id => id !== taskId)
      const targetStackIdx = targetFolderId ? newStacks.findIndex(s => s.id === targetFolderId) : -1
      if (targetStackIdx >= 0) {
        newStacks[targetStackIdx].taskIds = [taskId, ...(newStacks[targetStackIdx].taskIds || [])]
      } else {
        newStacks.push({
          id: newFolderId, taskIds: [taskId], position,
          size: { width: 420, height: 320 }, isMinimized: false,
        })
      }
      return newStacks.filter(stack => stack.taskIds.length > 0)
    })

    setZIndices(prev => {
      if (targetFolderId) return prev.slice(0, folderStacks.length)
      return [...prev.slice(0, folderStacks.length), maxZ + 1]
    })
    if (!targetFolderId) setMaxZ(prev => prev + 1)
    setSelectedTaskId(taskId)
    setDragTargetFolderId(null)
  }, [folderStacks, maxZ])

  const handleFolderDrag = useCallback((stackIndex: number, currentPosition: { x: number; y: number }) => {
    const currentStack = folderStacks[stackIndex]
    if (!currentStack || currentStack.isMinimized) return
    const draggingTabX = currentPosition.x + 8
    const draggingTabY = currentPosition.y - 16
    let targetId: string | null = null
    folderStacks.forEach((stack, idx) => {
      if (idx === stackIndex || stack.isMinimized) return
      const targetTabX = stack.position.x + 8
      const targetTabY = stack.position.y - 16
      const overlapThreshold = 30
      const tabsOverlap = (
        draggingTabX < targetTabX + 160 + overlapThreshold &&
        draggingTabX + 160 > targetTabX - overlapThreshold &&
        draggingTabY < targetTabY + 16 + overlapThreshold &&
        draggingTabY + 16 > targetTabY - overlapThreshold
      )
      if (tabsOverlap) targetId = stack.id
    })
    setDragTargetFolderId(targetId)
  }, [folderStacks])

  const handleFolderDragEnd = useCallback((stackIndex: number, finalPosition: { x: number; y: number }) => {
    const currentStack = folderStacks[stackIndex]
    if (!currentStack || currentStack.isMinimized) return
    let targetFolderIndex = -1
    const draggingTabX = finalPosition.x + 8
    const draggingTabY = finalPosition.y - 16
    folderStacks.forEach((stack, idx) => {
      if (idx === stackIndex || stack.isMinimized) return
      const targetTabX = stack.position.x + 8
      const targetTabY = stack.position.y - 16
      const overlapThreshold = 30
      const tabsOverlap = (
        draggingTabX < targetTabX + 160 + overlapThreshold &&
        draggingTabX + 160 > targetTabX - overlapThreshold &&
        draggingTabY < targetTabY + 16 + overlapThreshold &&
        draggingTabY + 16 > targetTabY - overlapThreshold
      )
      if (tabsOverlap) targetFolderIndex = idx
    })
    if (targetFolderIndex >= 0) {
      const sourceId = currentStack.id
      const targetId = folderStacks[targetFolderIndex]?.id
      if (!targetId) return
      setFolderStacks(prev => {
        const sourceIdx = prev.findIndex(s => s.id === sourceId)
        const targetIdx = prev.findIndex(s => s.id === targetId)
        if (sourceIdx === -1 || targetIdx === -1) return prev
        const newStacks = prev.map(stack => ({ ...stack, taskIds: [...(stack.taskIds || [])] }))
        newStacks[targetIdx].taskIds = [...(prev[sourceIdx].taskIds || []), ...(prev[targetIdx].taskIds || [])]
        return newStacks.filter(s => s.id !== sourceId)
      })
      setZIndices(prev => prev.slice(0, -1))
    }
    setDragTargetFolderId(null)
  }, [folderStacks])

  const handleMinimize = useCallback((stackIndex: number) => {
    setFolderStacks(prev => {
      const newStacks = [...prev]
      const stack = newStacks[stackIndex]
      newStacks[stackIndex] = { ...stack, isMinimized: true, savedPosition: stack.position }
      return newStacks
    })
    const stack = folderStacks[stackIndex]
    if (selectedTaskId && stack?.taskIds.includes(selectedTaskId)) setSelectedTaskId(null)
  }, [folderStacks, selectedTaskId])

  const handleExpand = useCallback((stackIndex: number) => {
    setFolderStacks(prev => {
      const newStacks = [...prev]
      const stack = newStacks[stackIndex]
      newStacks[stackIndex] = { ...stack, isMinimized: false, position: stack.savedPosition || stack.position }
      return newStacks
    })
    bringToFront(stackIndex)
  }, [bringToFront])

  const handleClose = useCallback((stackIndex: number) => {
    const stack = folderStacks[stackIndex]
    if (!stack) return
    // Hide this folder so polls don't recreate it
    setHiddenFolderIds(prev => new Set([...prev, stack.id]))
    setFolderStacks(prev => {
      const newStacks = [...prev]
      newStacks.splice(stackIndex, 1)
      return newStacks
    })
    setZIndices(prev => {
      const newIndices = [...prev]
      newIndices.splice(stackIndex, 1)
      return newIndices
    })
    if (selectedTaskId && stack.taskIds.includes(selectedTaskId)) setSelectedTaskId(null)
  }, [folderStacks, selectedTaskId])

  const handleBackgroundClick = () => setSelectedTaskId(null)

  return (
    <div key={mountKey} className="relative min-h-screen overflow-hidden" onClick={handleBackgroundClick}>
      <HudBackground />

      <div className="relative z-10 flex flex-col min-h-screen">
        {/* Header */}
        <HudHeader
          onAddTask={handleAddTask}
          onNewWindow={handleNewWindow}
          onSplitPane={handleSplitPane}
          paneCount={tasks.length}
          connected={connected}
          sessions={Array.from(new Set(tasks.map(t => t.session))).map(name => ({
            name,
            windowCount: new Set(tasks.filter(t => t.session === name).map(t => t.pane)).size,
          }))}
        />

        {/* Stats bar */}
        <div className="mx-6 mt-2 flex items-center justify-between px-4 py-3 bg-slate-900/50 border border-cyan-800/30 rounded-sm">
          <div className="flex items-center gap-6">
            <div className="flex items-center gap-2">
              <span className="text-[10px] font-mono text-cyan-500/60 uppercase tracking-widest">Active Sessions</span>
              <span className="text-lg font-mono text-cyan-300 tabular-nums">{tasks.length}</span>
            </div>
            <div className="w-px h-6 bg-cyan-700/30" />
            <div className="flex items-center gap-2">
              <span className="text-[10px] font-mono text-cyan-500/60 uppercase tracking-widest">Idle</span>
              <span className="text-lg font-mono text-emerald-400 tabular-nums">{statusCounts["Idle"] || 0}</span>
            </div>
            <div className="w-px h-6 bg-cyan-700/30" />
            <div className="flex items-center gap-2">
              <span className="text-[10px] font-mono text-cyan-500/60 uppercase tracking-widest">Waiting</span>
              <span className="text-lg font-mono text-amber-400 tabular-nums">{(statusCounts["Waiting"] || 0) + (statusCounts["Approval"] || 0)}</span>
            </div>
            <div className="w-px h-6 bg-cyan-700/30" />
            <div className="flex items-center gap-2">
              <span className="text-[10px] font-mono text-cyan-500/60 uppercase tracking-widest">Processing</span>
              <span className="text-lg font-mono text-cyan-400 tabular-nums">{statusCounts["Processing"] || 0}</span>
            </div>

            {/* Usage stats */}
            {usageStats && (
              <>
                {/* 5h bar + count */}
                <div className="w-px h-6 bg-cyan-700/30" />
                <div className="flex items-center gap-2">
                  <span className="text-[10px] font-mono text-cyan-500/60 uppercase tracking-widest">5h</span>
                  {usageStats.five_h_pct != null ? (
                    <>
                      <div className="flex gap-0.5">
                        {Array.from({ length: 10 }).map((_, i) => (
                          <div key={i} className={`w-1.5 h-3 ${
                            i < Math.round((usageStats.five_h_pct ?? 0) / 10)
                              ? (usageStats.five_h_pct ?? 0) < 50 ? "bg-emerald-400" : (usageStats.five_h_pct ?? 0) < 80 ? "bg-amber-400" : "bg-red-400"
                              : "bg-cyan-800/40"
                          }`} />
                        ))}
                      </div>
                      <span className={`text-xs font-mono tabular-nums ${
                        (usageStats.five_h_pct ?? 0) < 50 ? "text-emerald-400" : (usageStats.five_h_pct ?? 0) < 80 ? "text-amber-400" : "text-red-400"
                      }`}>{usageStats.five_h_pct}%</span>
                    </>
                  ) : (
                    <span className="text-xs font-mono text-cyan-300 tabular-nums">
                      {usageStats.five_h_messages ?? 0} msgs
                    </span>
                  )}
                </div>

                {/* 7d / Weekly */}
                <div className="w-px h-6 bg-cyan-700/30" />
                <div className="flex items-center gap-2">
                  <span className="text-[10px] font-mono text-cyan-500/60 uppercase tracking-widest">7d</span>
                  {usageStats.seven_d_pct != null ? (
                    <>
                      <div className="flex gap-0.5">
                        {Array.from({ length: 10 }).map((_, i) => (
                          <div key={i} className={`w-1.5 h-3 ${
                            i < Math.round((usageStats.seven_d_pct ?? 0) / 10)
                              ? (usageStats.seven_d_pct ?? 0) < 50 ? "bg-emerald-400" : (usageStats.seven_d_pct ?? 0) < 80 ? "bg-amber-400" : "bg-red-400"
                              : "bg-cyan-800/40"
                          }`} />
                        ))}
                      </div>
                      <span className={`text-xs font-mono tabular-nums ${
                        (usageStats.seven_d_pct ?? 0) < 50 ? "text-emerald-400" : (usageStats.seven_d_pct ?? 0) < 80 ? "text-amber-400" : "text-red-400"
                      }`}>{usageStats.seven_d_pct}%</span>
                    </>
                  ) : (
                    <span className="text-xs font-mono text-cyan-300 tabular-nums">
                      {usageStats.week_messages ?? 0} msgs
                    </span>
                  )}
                </div>

                {/* Today */}
                <div className="w-px h-6 bg-cyan-700/30" />
                <div className="flex items-center gap-2">
                  <span className="text-[10px] font-mono text-cyan-500/60 uppercase tracking-widest">Today</span>
                  <span className="text-xs font-mono text-cyan-300 tabular-nums">{usageStats.today_messages ?? 0} msgs</span>
                  <span className="text-xs font-mono text-cyan-500/50">{fmtTokens(usageStats.today_tokens ?? 0)} tok</span>
                </div>

                {/* Plan */}
                {usageStats.subscription && (
                  <>
                    <div className="w-px h-6 bg-cyan-700/30" />
                    <div className="flex items-center gap-2">
                      <span className="text-[10px] font-mono text-cyan-500/60 uppercase tracking-widest">Plan</span>
                      <span className="text-xs font-mono text-cyan-300 capitalize">{usageStats.subscription}</span>
                    </div>
                  </>
                )}
              </>
            )}
          </div>
          <div className="flex items-center gap-4">
            <span className="text-[10px] font-mono text-cyan-600/40 tracking-wider">
              DRAG FOLDERS TO STACK {"•"} DRAG TABS TO SEPARATE
            </span>
            <div className="flex gap-1">
              {Array.from({ length: 8 }).map((_, i) => (
                <div key={i} className={`w-1.5 h-3 ${i < 6 ? "bg-cyan-500/60" : "bg-cyan-800/40"}`} />
              ))}
            </div>
          </div>
        </div>

        {/* Main content area */}
        <main className="flex-1 relative" style={{ minHeight: "calc(100vh - 200px)" }}>
          {folderStacks.map((stack, stackIndex) => {
            const frontTask = tasksMap.get(stack.taskIds[0])
            if (!frontTask) return null

            const stackedTasks = stack.taskIds.slice(1)
              .map(id => tasksMap.get(id))
              .filter((t): t is TaskData => t !== undefined)

            const minimizedIndex = stack.isMinimized
              ? minimizedFolders.findIndex(f => f.index === stackIndex)
              : 0

            return (
              <TaskFolder
                key={`${mountKey}-${stack.id}`}
                folderId={stack.id}
                task={frontTask}
                stackedTasks={stackedTasks}
                isSelected={selectedTaskId === frontTask.id}
                isMinimized={stack.isMinimized}
                onClick={() => setSelectedTaskId(selectedTaskId === frontTask.id ? null : frontTask.id)}
                onStackItemClick={(taskId) => handleStackItemClick(stackIndex, taskId)}
                onStackItemDragOut={(taskId, pos) => handleStackItemDragOut(stackIndex, taskId, pos)}
                initialPosition={stack.position}
                initialSize={stack.size}
                onPositionChange={(pos) => handlePositionChange(stackIndex, pos)}
                onSizeChange={(size) => handleSizeChange(stackIndex, size)}
                onDrag={(pos) => handleFolderDrag(stackIndex, pos)}
                onDragEnd={(pos) => handleFolderDragEnd(stackIndex, pos)}
                zIndex={zIndices[stackIndex] || 1}
                onBringToFront={() => bringToFront(stackIndex)}
                onClose={() => handleClose(stackIndex)}
                onMinimize={() => handleMinimize(stackIndex)}
                onExpand={() => handleExpand(stackIndex)}
                minimizedIndex={minimizedIndex}
                isDragTarget={dragTargetFolderId === stack.id}
                onDoubleClick={(taskId) => handleAttach(taskId)}
                onSlashCommand={handleSlashCommand}
              />
            )
          })}
        </main>

        {/* Bottom prompt bar */}
        <footer className="sticky bottom-0 z-50 p-6 pt-0 bg-gradient-to-t from-slate-950 via-slate-950/95 to-transparent">
          <PromptBar
            selectedTask={selectedTask ? selectedTask.target : null}
            onSend={handleSendPrompt}
            promptOptions={selectedTask?.prompt_options}
            promptDesc={selectedTask?.prompt_desc}
            taskStatus={selectedTask?.status}
            onSendOption={handleSendOption}
            onSendEscape={handleSendEscape}
          />
        </footer>
      </div>

      {/* Slash command result dialog */}
      {slashDialogResult && (
        <div className="fixed inset-0 z-[9999] flex items-center justify-center bg-black/60 backdrop-blur-sm"
          onClick={() => setSlashDialogResult(null)}>
          <div className="w-[700px] max-h-[500px] bg-slate-900 border border-cyan-500/50 rounded-sm shadow-xl shadow-cyan-500/20 overflow-hidden"
            onClick={e => e.stopPropagation()}>
            <div className="flex items-center justify-between px-4 py-3 bg-slate-800/80 border-b border-cyan-600/30">
              <span className="text-sm font-mono font-bold text-cyan-300 tracking-wider">{slashDialogResult.cmd}</span>
              <button onClick={() => setSlashDialogResult(null)}
                className="text-cyan-500/60 hover:text-cyan-300 text-sm font-mono px-2 py-1 hover:bg-cyan-500/10 rounded transition-colors">
                Close
              </button>
            </div>
            <div className="p-4 overflow-auto max-h-[400px]">
              <pre className="text-xs font-mono text-cyan-200/80 whitespace-pre-wrap leading-relaxed">
                {slashDialogResult.result || "(no output)"}
              </pre>
            </div>
          </div>
        </div>
      )}

      {/* Side decorations */}
      <div className="fixed top-1/2 left-4 -translate-y-1/2 flex flex-col gap-2 opacity-40 z-0">
        {Array.from({ length: 8 }).map((_, i) => (
          <div key={i} className="w-1 bg-cyan-500/60" style={{ height: `${12 + Math.sin(i * 0.8) * 8}px` }} />
        ))}
      </div>
      <div className="fixed top-1/2 right-4 -translate-y-1/2 flex flex-col gap-2 opacity-40 z-0">
        {Array.from({ length: 8 }).map((_, i) => (
          <div key={i} className="w-1 bg-cyan-500/60" style={{ height: `${12 + Math.cos(i * 0.8) * 8}px` }} />
        ))}
      </div>
    </div>
  )
}

"use client"

import { useState, useRef, useCallback, useEffect } from "react"
import { ContextRing } from "./context-ring"

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

interface Position {
  x: number
  y: number
}

interface Size {
  width: number
  height: number
}

interface TaskFolderProps {
  task: TaskData
  stackedTasks?: TaskData[]
  isSelected: boolean
  isMinimized?: boolean
  onClick: () => void
  onStackItemClick?: (taskId: string) => void
  onStackItemDragOut?: (taskId: string, position: Position) => void
  initialPosition: Position
  initialSize: Size
  onPositionChange?: (pos: Position) => void
  onSizeChange?: (size: Size) => void
  onDrag?: (currentPosition: Position) => void
  onDragEnd?: (finalPosition: Position) => void
  zIndex: number
  onBringToFront: () => void
  onClose?: () => void
  onMinimize?: () => void
  onExpand?: () => void
  minimizedIndex?: number
  isDragTarget?: boolean
  folderId: string
  onDoubleClick?: (taskId: string) => void
  onSlashCommand?: (target: string, cmd: string) => void
}

export function TaskFolder({
  task,
  stackedTasks = [],
  isSelected,
  isMinimized = false,
  onClick,
  onStackItemClick,
  onStackItemDragOut,
  initialPosition,
  initialSize,
  onPositionChange,
  onSizeChange,
  onDrag,
  onDragEnd,
  zIndex,
  onBringToFront,
  onClose,
  onMinimize,
  onExpand,
  minimizedIndex = 0,
  isDragTarget = false,
  folderId,
  onDoubleClick,
  onSlashCommand,
}: TaskFolderProps) {
  const [isHovered, setIsHovered] = useState(false)
  const [position, setPosition] = useState(initialPosition)
  const [size, setSize] = useState(initialSize)
  const [isDragging, setIsDragging] = useState(false)
  const [isResizing, setIsResizing] = useState(false)
  const [draggingStackedTab, setDraggingStackedTab] = useState<string | null>(null)
  const [stackedTabDragPos, setStackedTabDragPos] = useState<Position | null>(null)
  const [contextMenu, setContextMenu] = useState<{ x: number; y: number; taskId: string } | null>(null)
  const dragOffset = useRef({ x: 0, y: 0 })
  const folderRef = useRef<HTMLDivElement>(null)

  const contextPercent = Math.round((task.contextUsed / task.contextTotal) * 100)

  const getStatusColor = (status: TaskData["status"]) => ({
    Idle: "bg-emerald-500",
    Waiting: "bg-amber-500",
    Processing: "bg-cyan-400",
    Approval: "bg-amber-500",
  }[status])

  const getStatusTextColor = (status: TaskData["status"]) => ({
    Idle: "text-emerald-400",
    Waiting: "text-amber-400",
    Processing: "text-cyan-300",
    Approval: "text-amber-400",
  }[status])

  const statusColor = getStatusColor(task.status)
  const statusTextColor = getStatusTextColor(task.status)
  const statusLabel = task.status === "Approval" ? "Approval" : task.status

  const mouseDownTime = useRef(0)
  const mouseDownPos = useRef({ x: 0, y: 0 })

  const handleMouseDown = useCallback((e: React.MouseEvent) => {
    if (isMinimized) return
    if ((e.target as HTMLElement).closest('.resize-handle')) return
    if ((e.target as HTMLElement).closest('.stacked-tab')) return
    if ((e.target as HTMLElement).closest('.window-controls')) return
    if ((e.target as HTMLElement).closest('.front-tab') && stackedTasks.length > 0) return
    e.preventDefault()
    onBringToFront()
    mouseDownTime.current = Date.now()
    mouseDownPos.current = { x: e.clientX, y: e.clientY }
    setIsDragging(true)
    dragOffset.current = {
      x: e.clientX - position.x,
      y: e.clientY - position.y
    }
  }, [position, onBringToFront, isMinimized, stackedTasks.length])

  const handleResizeMouseDown = useCallback((e: React.MouseEvent) => {
    if (isMinimized) return
    e.preventDefault()
    e.stopPropagation()
    onBringToFront()
    setIsResizing(true)
    dragOffset.current = { x: e.clientX, y: e.clientY }
  }, [onBringToFront, isMinimized])

  const handleStackedTabMouseDown = useCallback((e: React.MouseEvent, taskId: string) => {
    e.preventDefault()
    e.stopPropagation()
    setDraggingStackedTab(taskId)
    setStackedTabDragPos({ x: e.clientX - 80, y: e.clientY - 12 })
    dragOffset.current = { x: 80, y: 12 }
  }, [])

  const handleFrontTabMouseDown = useCallback((e: React.MouseEvent) => {
    if (stackedTasks.length === 0) return
    e.preventDefault()
    e.stopPropagation()
    setDraggingStackedTab(task.id)
    setStackedTabDragPos({ x: e.clientX - 80, y: e.clientY - 12 })
    dragOffset.current = { x: 80, y: 12 }
  }, [stackedTasks.length, task.id])

  // Double-click handler for attach — only if user didn't drag
  const handleDoubleClick = useCallback((e: React.MouseEvent) => {
    e.stopPropagation()
    e.preventDefault()
    const elapsed = Date.now() - mouseDownTime.current
    const dx = Math.abs(e.clientX - mouseDownPos.current.x)
    const dy = Math.abs(e.clientY - mouseDownPos.current.y)
    // Only attach if user didn't drag (small movement threshold)
    if (dx < 10 && dy < 10) {
      onDoubleClick?.(task.id)
    }
  }, [task.id, onDoubleClick])

  // Right-click context menu
  const handleContextMenu = useCallback((e: React.MouseEvent) => {
    e.preventDefault()
    e.stopPropagation()
    setContextMenu({ x: e.clientX, y: e.clientY, taskId: task.id })
  }, [task.id])

  // Close context menu on outside click
  useEffect(() => {
    if (!contextMenu) return
    const handleClick = () => setContextMenu(null)
    document.addEventListener("click", handleClick)
    return () => document.removeEventListener("click", handleClick)
  }, [contextMenu])

  useEffect(() => {
    if (!isDragging && !isResizing && !draggingStackedTab) return

    const handleMouseMove = (e: MouseEvent) => {
      if (isDragging) {
        const newPos = {
          x: e.clientX - dragOffset.current.x,
          y: e.clientY - dragOffset.current.y
        }
        setPosition(newPos)
        onPositionChange?.(newPos)
        onDrag?.(newPos)
      } else if (isResizing) {
        const deltaX = e.clientX - dragOffset.current.x
        const deltaY = e.clientY - dragOffset.current.y
        const newSize = {
          width: Math.max(280, size.width + deltaX),
          height: Math.max(200, size.height + deltaY)
        }
        setSize(newSize)
        onSizeChange?.(newSize)
        dragOffset.current = { x: e.clientX, y: e.clientY }
      } else if (draggingStackedTab) {
        setStackedTabDragPos({
          x: e.clientX - dragOffset.current.x,
          y: e.clientY - dragOffset.current.y
        })
      }
    }

    const handleMouseUp = (e: MouseEvent) => {
      if (isDragging) {
        const finalPos = {
          x: e.clientX - dragOffset.current.x,
          y: e.clientY - dragOffset.current.y
        }
        onDragEnd?.(finalPos)
      }
      if (draggingStackedTab && stackedTabDragPos) {
        const dragDistance = Math.sqrt(
          Math.pow(stackedTabDragPos.x - (position.x + 20), 2) +
          Math.pow(stackedTabDragPos.y - (position.y - 20), 2)
        )
        if (dragDistance > 80) {
          onStackItemDragOut?.(draggingStackedTab, stackedTabDragPos)
        } else {
          onStackItemClick?.(draggingStackedTab)
        }
      }
      setIsDragging(false)
      setIsResizing(false)
      setDraggingStackedTab(null)
      setStackedTabDragPos(null)
    }

    window.addEventListener("mousemove", handleMouseMove)
    window.addEventListener("mouseup", handleMouseUp)
    return () => {
      window.removeEventListener("mousemove", handleMouseMove)
      window.removeEventListener("mouseup", handleMouseUp)
    }
  }, [isDragging, isResizing, draggingStackedTab, stackedTabDragPos, size, position, onPositionChange, onSizeChange, onDrag, onDragEnd, onStackItemClick, onStackItemDragOut])

  useEffect(() => {
    if (!isDragging) setPosition(initialPosition)
  }, [initialPosition, isDragging])

  const ringSize = Math.min(size.width, size.height) * 0.35

  const renderStackLayers = () => {
    if (stackedTasks.length === 0 || isMinimized) return null
    const layers = []
    for (let i = stackedTasks.length - 1; i >= 0; i--) {
      const stackTask = stackedTasks[i]
      if (draggingStackedTab === stackTask.id) continue
      const layerIndex = stackedTasks.length - i
      const offset = layerIndex * 20
      const tabOpacity = Math.max(0.15, 0.5 - (layerIndex - 1) * 0.15)
      const borderOpacity = Math.max(0.15, 0.35 - (layerIndex - 1) * 0.1)
      const stackStatusColor = getStatusColor(stackTask.status).replace('bg-', '')
      const stackStatusDarkColor = {
        "emerald-500": "bg-emerald-700/60",
        "amber-500": "bg-amber-700/60",
        "cyan-400": "bg-cyan-600/60"
      }[stackStatusColor] || "bg-slate-700/60"
      const stackStatusTextColor = {
        "emerald-500": "text-emerald-500/70",
        "amber-500": "text-amber-500/70",
        "cyan-400": "text-cyan-400/70"
      }[stackStatusColor] || "text-slate-400/70"
      const stackStatusLabel = stackTask.status === "Approval" ? "Approval" : stackTask.status

      layers.push(
        <div
          key={stackTask.id}
          className="absolute inset-0 bg-slate-900/50 rounded-sm"
          style={{
            transform: `translate(${offset}px, ${-offset}px)`,
            zIndex: -layerIndex,
            border: `1px solid rgba(34, 211, 238, ${borderOpacity})`
          }}
        >
          <div
            className="stacked-tab flex gap-1 ml-2 absolute -top-3.5 left-0 cursor-grab active:cursor-grabbing hover:brightness-125 transition-all"
            onMouseDown={(e) => handleStackedTabMouseDown(e, stackTask.id)}
          >
            <div
              className="h-3.5 px-2 flex items-center gap-1 rounded-t-sm border-t border-l border-r border-cyan-700/30"
              style={{ backgroundColor: `rgba(6, 78, 59, ${tabOpacity})` }}
            >
              <div className={`w-1.5 h-1.5 rounded-full ${stackStatusDarkColor}`} />
              <span className={`text-[8px] font-mono ${stackStatusTextColor} uppercase tracking-wider`}>
                {stackStatusLabel}
              </span>
            </div>
            <div
              className="h-3.5 px-2 flex items-center rounded-t-sm border-t border-l border-r border-cyan-700/30"
              style={{ backgroundColor: `rgba(8, 145, 178, ${tabOpacity})` }}
            >
              <span className="text-[8px] font-mono text-cyan-300/60 tracking-wider">
                {stackTask.session}:{stackTask.pane}
              </span>
            </div>
          </div>
        </div>
      )
    }
    return layers
  }

  const renderDraggingTab = () => {
    if (!draggingStackedTab || !stackedTabDragPos) return null
    const dragTask = draggingStackedTab === task.id
      ? task
      : stackedTasks.find(t => t.id === draggingStackedTab)
    if (!dragTask) return null
    const dragStatusColor = getStatusColor(dragTask.status)
    const dragStatusTextColor = getStatusTextColor(dragTask.status)
    const dragStatusLabel = dragTask.status === "Approval" ? "Approval" : dragTask.status

    return (
      <div
        className="fixed z-[9999] pointer-events-none opacity-90"
        style={{ left: stackedTabDragPos.x, top: stackedTabDragPos.y }}
      >
        <div className="flex gap-1">
          <div
            className="h-5 px-2.5 flex items-center gap-1.5 rounded-t-sm border border-cyan-400/60 backdrop-blur-md shadow-lg shadow-cyan-500/20"
            style={{ backgroundColor: `rgba(6, 78, 59, 0.9)` }}
          >
            <div className={`w-2 h-2 rounded-full ${dragStatusColor} animate-pulse`} />
            <span className={`text-[9px] font-mono ${dragStatusTextColor} uppercase tracking-wider font-medium`}>
              {dragStatusLabel}
            </span>
          </div>
          <div
            className="h-5 px-2.5 flex items-center rounded-t-sm border border-cyan-400/60 backdrop-blur-md shadow-lg shadow-cyan-500/20"
            style={{ backgroundColor: `rgba(8, 145, 178, 0.9)` }}
          >
            <span className="text-[9px] font-mono text-cyan-100 tracking-wider font-medium">
              {dragTask.session}:{dragTask.pane}
            </span>
          </div>
        </div>
        <div className="w-40 h-24 bg-slate-900/90 border border-cyan-400/50 rounded-sm mt-[-2px] shadow-lg shadow-cyan-500/20">
          <div className="p-2 text-[8px] font-mono text-cyan-400/70 truncate">
            {dragTask.activity}
          </div>
        </div>
      </div>
    )
  }

  // Context menu component
  const renderContextMenu = () => {
    if (!contextMenu) return null
    return (
      <div
        className="fixed z-[9999] bg-slate-900/95 border border-cyan-500/40 rounded-sm shadow-xl shadow-cyan-500/20 backdrop-blur-md min-w-[200px] py-1 overflow-hidden"
        style={{ left: contextMenu.x, top: contextMenu.y }}
        onClick={e => e.stopPropagation()}
      >
        <button
          onClick={() => { onDoubleClick?.(task.id); setContextMenu(null) }}
          className="w-full px-3 py-2 text-left text-xs font-mono text-cyan-200 hover:bg-cyan-500/20 transition-colors"
        >
          Attach (open terminal)
        </button>
        <div className="h-px bg-cyan-700/30 mx-2" />
        <button
          onClick={async () => {
            const { eel: eelBridge } = await import("@/lib/eel-bridge")
            await eelBridge.breakPane(task.pane_id)
            setContextMenu(null)
          }}
          className="w-full px-3 py-2 text-left text-xs font-mono text-cyan-200 hover:bg-cyan-500/20 transition-colors"
        >
          Break to new window
        </button>
        <button
          onClick={async () => {
            const { eel: eelBridge } = await import("@/lib/eel-bridge")
            await eelBridge.swapPane(task.target, "U")
            setContextMenu(null)
          }}
          className="w-full px-3 py-2 text-left text-xs font-mono text-cyan-200 hover:bg-cyan-500/20 transition-colors"
        >
          Move Up
        </button>
        <button
          onClick={async () => {
            const { eel: eelBridge } = await import("@/lib/eel-bridge")
            await eelBridge.swapPane(task.target, "D")
            setContextMenu(null)
          }}
          className="w-full px-3 py-2 text-left text-xs font-mono text-cyan-200 hover:bg-cyan-500/20 transition-colors"
        >
          Move Down
        </button>
        {onSlashCommand && (
          <>
            <div className="h-px bg-cyan-700/30 mx-2" />
            <div className="px-3 py-1.5 text-[10px] font-mono text-cyan-500/50 uppercase tracking-widest">
              / Commands
            </div>
            {["/usage", "/status", "/compact", "/cost", "/model"].map(cmd => (
              <button
                key={cmd}
                onClick={() => { onSlashCommand(task.target, cmd); setContextMenu(null) }}
                className="w-full px-3 py-1.5 text-left text-xs font-mono text-cyan-300/80 hover:bg-cyan-500/20 transition-colors"
              >
                {cmd}
              </button>
            ))}
          </>
        )}
      </div>
    )
  }

  // Minimized view
  if (isMinimized) {
    return (
      <div
        className="fixed bottom-24 cursor-pointer z-40 transition-all duration-200 hover:translate-y-[-4px]"
        style={{ left: 24 + minimizedIndex * 180 }}
        onClick={(e) => { e.stopPropagation(); onExpand?.() }}
      >
        <div className="flex gap-1">
          <div
            className="h-6 px-3 flex items-center gap-1.5 rounded-t-sm border-t border-l border-r border-cyan-500/50 backdrop-blur-md"
            style={{ backgroundColor: `rgba(6, 78, 59, 0.9)` }}
          >
            <div className={`w-2 h-2 rounded-full ${statusColor} animate-pulse`} />
            <span className={`text-[10px] font-mono ${statusTextColor} uppercase tracking-wider font-medium`}>
              {statusLabel}
            </span>
          </div>
          <div
            className="h-6 px-3 flex items-center rounded-t-sm border-t border-l border-r border-cyan-400/60 backdrop-blur-md"
            style={{ backgroundColor: `rgba(8, 145, 178, 0.9)` }}
          >
            <span className="text-[10px] font-mono text-cyan-100 tracking-wider font-medium">
              {task.session}:{task.pane}
            </span>
          </div>
        </div>
        <div className="h-1 bg-slate-900/90 border-x border-b border-cyan-600/40 rounded-b-sm" />
      </div>
    )
  }

  return (
    <>
      <div
        ref={folderRef}
        data-folder-id={folderId}
        className={`absolute cursor-move select-none transition-shadow duration-300 ${
          isSelected ? "ring-2 ring-cyan-400/50" : ""
        } ${isDragTarget ? "ring-2 ring-emerald-400/70 ring-offset-2 ring-offset-slate-900" : ""}`}
        style={{
          left: position.x, top: position.y,
          width: size.width, height: size.height,
          zIndex: zIndex
        }}
        onMouseDown={handleMouseDown}
        onMouseEnter={() => setIsHovered(true)}
        onMouseLeave={() => setIsHovered(false)}
        onDoubleClick={handleDoubleClick}
        onContextMenu={handleContextMenu}
        onClick={(e) => { e.stopPropagation(); onClick() }}
      >
        {/* Stack layers */}
        {renderStackLayers()}

        {/* Front folder tabs */}
        <div
          className={`front-tab flex gap-1 ml-2 absolute -top-4 left-0 z-10 ${
            stackedTasks.length > 0 ? "cursor-grab active:cursor-grabbing hover:brightness-125" : "cursor-pointer hover:brightness-125"
          } ${draggingStackedTab === task.id ? "opacity-30" : ""}`}
          onMouseDown={stackedTasks.length > 0 ? handleFrontTabMouseDown : undefined}
          onClick={(e) => { e.stopPropagation(); if (!draggingStackedTab) onClick() }}
        >
          <div
            className="h-4 px-2.5 flex items-center gap-1.5 rounded-t-sm border-t border-l border-r border-cyan-500/50 backdrop-blur-md"
            style={{ backgroundColor: `rgba(6, 78, 59, 0.8)` }}
          >
            <div className={`w-2 h-2 rounded-full ${statusColor} animate-pulse`} />
            <span className={`text-[9px] font-mono ${statusTextColor} uppercase tracking-wider font-medium`}>
              {statusLabel}
            </span>
          </div>
          <div
            className="h-4 px-2.5 flex items-center rounded-t-sm border-t border-l border-r border-cyan-400/60 backdrop-blur-md"
            style={{ backgroundColor: `rgba(8, 145, 178, 0.8)` }}
          >
            <span className="text-[9px] font-mono text-cyan-100 tracking-wider font-medium">
              {task.session}:{task.pane}
            </span>
          </div>
        </div>

        {/* Main folder body */}
        <div
          className={`relative h-full bg-gradient-to-br from-slate-900/95 via-slate-900/90 to-slate-950/95
            rounded-sm overflow-hidden backdrop-blur-sm
            ${isSelected ? "shadow-lg shadow-cyan-500/30" : "hover:shadow-md hover:shadow-cyan-500/20"}
            ${isDragTarget ? "shadow-lg shadow-emerald-500/30" : ""}`}
          style={{
            border: isDragTarget
              ? "2px solid rgba(52, 211, 153, 0.8)"
              : isSelected
                ? "1px solid rgba(34, 211, 238, 0.8)"
                : "1px solid rgba(8, 145, 178, 0.4)"
          }}
        >
          {/* Top bar */}
          <div className="flex items-center justify-between px-3 py-1.5 bg-gradient-to-r from-cyan-900/30 to-slate-900/50 border-b border-cyan-600/30">
            <span className="text-xs font-mono font-bold text-cyan-300 uppercase tracking-[0.2em] drop-shadow-[0_0_3px_rgba(34,211,238,0.5)]">
              {task.model}
            </span>
            <div className="window-controls relative z-30 flex items-center gap-2 text-cyan-500/60 text-xs font-mono">
              <button onClick={(e) => { e.stopPropagation(); onMinimize?.() }}
                className="hover:text-amber-400 hover:bg-amber-400/10 px-1.5 py-0.5 rounded transition-colors" title="Minimize">_</button>
              <button onClick={(e) => { e.stopPropagation(); onExpand?.() }}
                className="hover:text-emerald-400 hover:bg-emerald-400/10 px-1.5 py-0.5 rounded transition-colors" title="Expand">◇</button>
              <button onClick={(e) => { e.stopPropagation(); onClose?.() }}
                className="hover:text-red-400 hover:bg-red-400/10 px-1.5 py-0.5 rounded transition-colors" title="Close">×</button>
            </div>
          </div>

          {/* Content area */}
          <div className="flex flex-col overflow-hidden" style={{ height: `calc(100% - 32px)` }}>
            {isSelected ? (
              <div className="flex-1 flex flex-col overflow-hidden">
                <div className="flex items-center px-3 py-1 bg-slate-950/60 border-b border-cyan-900/30">
                  <div className="flex items-center gap-2">
                    <div className="w-2 h-2 rounded-full bg-cyan-500/60 animate-pulse" />
                    <span className="text-[10px] font-mono text-cyan-400/80 uppercase tracking-wider">
                      Terminal Feed
                    </span>
                    {task.status === "Approval" && (
                      <span className="text-[10px] font-mono text-amber-400 uppercase tracking-wider ml-2 animate-pulse">
                        NEEDS APPROVAL
                      </span>
                    )}
                  </div>
                </div>
                <div className="flex-1 overflow-auto p-3 space-y-2 bg-slate-950/40 font-mono text-xs">
                  {task.terminalHistory && task.terminalHistory.length > 0 ? (
                    task.terminalHistory.map((entry, idx) => (
                      <div key={idx} className={`${
                        entry.type === "user" ? "text-emerald-400"
                          : entry.type === "system" ? "text-amber-400/70"
                          : "text-cyan-300/90"
                      }`}>
                        {entry.type === "user" && <span className="text-emerald-500/70 mr-2">{">"}</span>}
                        {entry.type === "assistant" && <span className="text-cyan-500/70 mr-2">{"$"}</span>}
                        {entry.type === "system" && <span className="text-amber-500/70 mr-2">{"#"}</span>}
                        <span className="whitespace-pre-wrap">{entry.content}</span>
                        {entry.timestamp && <span className="text-cyan-700/50 text-[9px] ml-2">{entry.timestamp}</span>}
                      </div>
                    ))
                  ) : (
                    <div className="text-cyan-600/40 italic">
                      <span className="text-cyan-500/50">$</span> {task.activity}
                    </div>
                  )}
                  {task.status === "Idle" && (
                    <div className="flex items-center gap-1 text-cyan-400/60">
                      <span>{">"}</span>
                      <span className="w-2 h-4 bg-cyan-400/60 animate-pulse" />
                    </div>
                  )}
                  {task.status === "Processing" && (
                    <div className="flex items-center gap-2 text-amber-400/80">
                      <span className="animate-spin">{"◌"}</span>
                      <span>Processing...</span>
                    </div>
                  )}
                  {task.status === "Waiting" && (
                    <div className="flex items-center gap-2 text-cyan-400/80">
                      <span className="animate-pulse">{"?"}</span>
                      <span>Awaiting input...</span>
                    </div>
                  )}
                  {task.status === "Approval" && task.prompt_desc && (
                    <div className="mt-2 p-2 bg-amber-900/20 border border-amber-500/30 rounded-sm">
                      <span className="text-[10px] font-mono text-amber-400/70 uppercase tracking-wider">Action:</span>
                      <p className="text-xs text-amber-200/80 mt-1">{task.prompt_desc}</p>
                    </div>
                  )}
                </div>
              </div>
            ) : (
              <div className="p-4 space-y-3">
                <div className="space-y-1">
                  <span className="text-[10px] font-mono text-cyan-500/60 uppercase tracking-widest">Turns</span>
                  <div className="flex items-baseline gap-1">
                    <span className="text-xl font-mono text-cyan-300 tabular-nums">{task.turns}</span>
                    <span className="text-[10px] text-cyan-600/60">cycles</span>
                  </div>
                </div>
                <div className="space-y-1 flex-1">
                  <span className="text-[10px] font-mono text-cyan-500/60 uppercase tracking-widest">Activity Log</span>
                  <div className="bg-slate-950/50 rounded-sm p-2 border border-cyan-900/30 h-auto max-h-20 overflow-auto">
                    <p className="text-xs font-mono text-cyan-400/80 leading-relaxed">{task.activity}</p>
                  </div>
                </div>
              </div>
            )}
          </div>

          {/* Scan line effect */}
          {(isSelected || isHovered) && (
            <div className="absolute inset-0 pointer-events-none overflow-hidden">
              <div className="absolute inset-x-0 h-8 bg-gradient-to-b from-cyan-400/10 to-transparent animate-scan" />
            </div>
          )}

          {/* Corner accents */}
          <div className="absolute top-0 left-0 w-5 h-5 border-t-[3px] border-l-[3px] border-cyan-400" />
          <div className="absolute top-0 right-0 w-5 h-5 border-t-[3px] border-r-[3px] border-cyan-400" />
          <div className="absolute bottom-0 left-0 w-5 h-5 border-b-[3px] border-l-[3px] border-cyan-400" />
          <div className="absolute bottom-0 right-0 w-5 h-5 border-b-[3px] border-r-[3px] border-cyan-400" />

          {/* Resize handle */}
          <div className="resize-handle absolute bottom-0 right-0 w-6 h-6 cursor-se-resize z-20"
            onMouseDown={handleResizeMouseDown}>
            <svg className="w-4 h-4 absolute bottom-1 right-1 text-cyan-500/50" viewBox="0 0 24 24" fill="currentColor">
              <path d="M22 22H20V20H22V22ZM22 18H20V16H22V18ZM18 22H16V20H18V22ZM22 14H20V12H22V14ZM18 18H16V16H18V18ZM14 22H12V20H14V22Z" />
            </svg>
          </div>
        </div>

        {/* Context Ring */}
        <div className="absolute z-10 pointer-events-none"
          style={{ bottom: -ringSize * 0.25, right: -ringSize * 0.25 }}>
          <ContextRing
            percent={contextPercent}
            used={task.contextUsed}
            total={task.contextTotal}
            size={ringSize}
            isActive={isSelected || isHovered}
          />
        </div>
      </div>

      {renderDraggingTab()}
      {renderContextMenu()}
    </>
  )
}

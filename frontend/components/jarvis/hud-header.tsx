"use client"

import { useEffect, useState, useRef } from "react"
import { Activity, Wifi, Plus, ChevronDown, Terminal, Columns, SquareSplitHorizontal } from "lucide-react"
import { HudGlobe } from "./hud-globe"
import { eel, type AgentDef } from "@/lib/eel-bridge"

interface SessionInfo {
  name: string
  windowCount: number
}

interface HudHeaderProps {
  onAddTask?: (agentCmd: string, agentLabel: string) => void
  onNewWindow?: (agentCmd: string, session: string) => void
  onSplitPane?: (agentCmd: string, session: string) => void
  paneCount?: number
  connected?: boolean
  sessions?: SessionInfo[]
}

export function HudHeader({
  onAddTask,
  onNewWindow,
  onSplitPane,
  paneCount = 0,
  connected = false,
  sessions = [],
}: HudHeaderProps) {
  const [showMenu, setShowMenu] = useState(false)
  const [agents, setAgents] = useState<AgentDef[]>([])
  const [menuMode, setMenuMode] = useState<"main" | "new-window" | "split">("main")
  const [selectedAgent, setSelectedAgent] = useState<AgentDef | null>(null)
  const menuRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    eel.getAgents().then(setAgents)
  }, [])

  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setShowMenu(false)
        setMenuMode("main")
      }
    }
    if (showMenu) {
      document.addEventListener("mousedown", handleClickOutside)
    }
    return () => document.removeEventListener("mousedown", handleClickOutside)
  }, [showMenu])

  const closeMenu = () => {
    setShowMenu(false)
    setMenuMode("main")
    setSelectedAgent(null)
  }

  return (
    <header className="relative py-4 px-6">
      <div className="absolute top-0 left-1/2 -translate-x-1/2 w-2/3 h-px bg-gradient-to-r from-transparent via-cyan-500/60 to-transparent" />

      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <HudGlobe size={50} />
          <div className="space-y-0.5">
            <h1 className="text-lg font-mono font-bold tracking-wider text-cyan-200">
              AI COMMAND CENTER
            </h1>
            <div className="flex items-center gap-2">
              <div className={`w-1.5 h-1.5 rounded-full ${connected ? "bg-emerald-400 animate-pulse" : "bg-red-400"}`} />
              <span className="text-[10px] font-mono text-cyan-500/70 tracking-widest">
                {connected ? "SYSTEM ONLINE" : "CONNECTING..."}
              </span>
            </div>
          </div>
        </div>

        <div className="flex items-center gap-6">
          <div className="flex items-center gap-2 px-3 py-1.5 bg-slate-900/50 border border-cyan-800/30 rounded-sm">
            <Terminal size={14} className="text-cyan-400" />
            <span className="text-xs font-mono text-cyan-300">{paneCount} panes</span>
          </div>
          <div className="flex items-center gap-2 px-3 py-1.5 bg-slate-900/50 border border-cyan-800/30 rounded-sm">
            <Activity size={14} className={connected ? "text-emerald-400" : "text-red-400"} />
            <span className="text-xs font-mono text-cyan-300">{connected ? "ACTIVE" : "OFFLINE"}</span>
          </div>
          <div className="flex items-center gap-2 px-3 py-1.5 bg-slate-900/50 border border-cyan-800/30 rounded-sm">
            <Wifi size={14} className="text-cyan-400" />
            <span className="text-xs font-mono text-cyan-300">SYNC</span>
          </div>
        </div>

        {/* Add Task dropdown */}
        <div className="relative" ref={menuRef}>
          <button
            onClick={(e) => {
              e.stopPropagation()
              setShowMenu(!showMenu)
              setMenuMode("main")
            }}
            className="flex items-center gap-2 px-4 py-2 bg-cyan-500/10 border border-cyan-500/50 rounded-sm
                       hover:bg-cyan-500/20 hover:border-cyan-400 hover:shadow-[0_0_15px_rgba(6,182,212,0.3)]
                       active:bg-cyan-500/30 transition-all duration-200 group"
          >
            <Plus size={16} className="text-cyan-400 group-hover:text-cyan-300" />
            <span className="text-xs font-mono font-medium text-cyan-300 uppercase tracking-wider group-hover:text-cyan-200">
              Add Task
            </span>
            <ChevronDown size={14} className={`text-cyan-400 transition-transform duration-200 ${showMenu ? "rotate-180" : ""}`} />
          </button>

          {showMenu && (
            <div className="absolute top-full right-0 mt-2 w-56 bg-slate-900/95 border border-cyan-500/40 rounded-sm
                            shadow-[0_0_20px_rgba(6,182,212,0.2)] backdrop-blur-md z-50 overflow-hidden">

              {menuMode === "main" && (
                <>
                  {/* New Session section */}
                  <div className="px-3 py-2 border-b border-cyan-500/20">
                    <span className="text-[10px] font-mono text-cyan-500/60 uppercase tracking-widest">New Session</span>
                  </div>
                  {agents.map((agent) => (
                    <button
                      key={`new-${agent.cmd}`}
                      onClick={(e) => {
                        e.stopPropagation()
                        onAddTask?.(agent.cmd, agent.label)
                        closeMenu()
                      }}
                      className="w-full px-3 py-2 flex items-center hover:bg-cyan-500/20
                                 transition-colors duration-150 group/item border-b border-cyan-500/10"
                    >
                      <div className="flex items-center gap-2">
                        <Plus size={12} className="text-cyan-400/60 group-hover/item:text-cyan-400" />
                        <span className="text-sm font-mono text-cyan-200 group-hover/item:text-cyan-100">{agent.label}</span>
                      </div>
                    </button>
                  ))}

                  {/* New Window in session */}
                  {sessions.length > 0 && (
                    <>
                      <div className="px-3 py-2 border-b border-cyan-500/20 border-t border-cyan-500/20">
                        <span className="text-[10px] font-mono text-cyan-500/60 uppercase tracking-widest">New Window</span>
                      </div>
                      {agents.map((agent) => (
                        <button
                          key={`win-${agent.cmd}`}
                          onClick={(e) => {
                            e.stopPropagation()
                            setSelectedAgent(agent)
                            setMenuMode("new-window")
                          }}
                          className="w-full px-3 py-2 flex items-center justify-between hover:bg-cyan-500/20
                                     transition-colors duration-150 group/item border-b border-cyan-500/10"
                        >
                          <div className="flex items-center gap-2">
                            <Columns size={12} className="text-cyan-400/60 group-hover/item:text-cyan-400" />
                            <span className="text-sm font-mono text-cyan-200 group-hover/item:text-cyan-100">{agent.label}</span>
                          </div>
                          <ChevronDown size={12} className="text-cyan-500/40 -rotate-90" />
                        </button>
                      ))}

                      {/* Split Pane */}
                      <div className="px-3 py-2 border-b border-cyan-500/20 border-t border-cyan-500/20">
                        <span className="text-[10px] font-mono text-cyan-500/60 uppercase tracking-widest">Split Pane</span>
                      </div>
                      {agents.map((agent) => (
                        <button
                          key={`split-${agent.cmd}`}
                          onClick={(e) => {
                            e.stopPropagation()
                            setSelectedAgent(agent)
                            setMenuMode("split")
                          }}
                          className="w-full px-3 py-2 flex items-center justify-between hover:bg-cyan-500/20
                                     transition-colors duration-150 group/item border-b border-cyan-500/10 last:border-0"
                        >
                          <div className="flex items-center gap-2">
                            <SquareSplitHorizontal size={12} className="text-cyan-400/60 group-hover/item:text-cyan-400" />
                            <span className="text-sm font-mono text-cyan-200 group-hover/item:text-cyan-100">{agent.label}</span>
                          </div>
                          <ChevronDown size={12} className="text-cyan-500/40 -rotate-90" />
                        </button>
                      ))}
                    </>
                  )}

                  {agents.length === 0 && (
                    <div className="px-3 py-2.5 text-xs font-mono text-cyan-600/50">Loading agents...</div>
                  )}
                </>
              )}

              {/* Session picker sub-menu */}
              {(menuMode === "new-window" || menuMode === "split") && selectedAgent && (
                <>
                  <div className="px-3 py-2 border-b border-cyan-500/20 flex items-center gap-2">
                    <button
                      onClick={(e) => { e.stopPropagation(); setMenuMode("main") }}
                      className="text-cyan-400 hover:text-cyan-200 text-xs font-mono"
                    >
                      ←
                    </button>
                    <span className="text-[10px] font-mono text-cyan-500/60 uppercase tracking-widest">
                      {menuMode === "new-window" ? "Window" : "Split"} → {selectedAgent.label} → Session
                    </span>
                  </div>
                  {sessions.map((sess) => (
                    <button
                      key={sess.name}
                      onClick={(e) => {
                        e.stopPropagation()
                        if (menuMode === "new-window") {
                          onNewWindow?.(selectedAgent.cmd, sess.name)
                        } else {
                          onSplitPane?.(selectedAgent.cmd, sess.name)
                        }
                        closeMenu()
                      }}
                      className="w-full px-3 py-2.5 flex items-center hover:bg-cyan-500/20
                                 transition-colors duration-150 group/item border-b border-cyan-500/10 last:border-0"
                    >
                      <div className="flex items-center gap-2">
                        <div className="w-2 h-2 rounded-full bg-cyan-400/60 group-hover/item:bg-cyan-400 transition-colors" />
                        <span className="text-sm font-mono text-cyan-200 group-hover/item:text-cyan-100">{sess.name}</span>
                      </div>
                    </button>
                  ))}
                </>
              )}
            </div>
          )}
        </div>
      </div>

      <div className="absolute bottom-0 left-0 right-0 h-px bg-gradient-to-r from-cyan-500/30 via-cyan-500/60 to-cyan-500/30" />
      <div className="absolute top-0 left-0 w-4 h-4 border-t-2 border-l-2 border-cyan-500/50" />
      <div className="absolute top-0 right-0 w-4 h-4 border-t-2 border-r-2 border-cyan-500/50" />
    </header>
  )
}

"use client"

import { useEffect, useState, useRef } from "react"
import { Activity, Cpu, Wifi, Plus, ChevronDown } from "lucide-react"
import { HudGlobe } from "./hud-globe"

const MODEL_OPTIONS = [
  { id: "claude-sonnet", name: "Claude Sonnet" },
  { id: "claude-opus", name: "Claude Opus" },
  { id: "gemini-pro", name: "Gemini Pro" },
  { id: "gemini-flash", name: "Gemini Flash" },
  { id: "codex-cli", name: "Codex CLI" },
]

interface HudHeaderProps {
  onAddTask?: (model: string) => void
}

export function HudHeader({ onAddTask }: HudHeaderProps) {
  const [showModelMenu, setShowModelMenu] = useState(false)
  const menuRef = useRef<HTMLDivElement>(null)

  // Close menu when clicking outside
  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setShowModelMenu(false)
      }
    }
    if (showModelMenu) {
      document.addEventListener("mousedown", handleClickOutside)
    }
    return () => document.removeEventListener("mousedown", handleClickOutside)
  }, [showModelMenu])

  return (
    <header className="relative py-4 px-6">
      {/* Top decorative line */}
      <div className="absolute top-0 left-1/2 -translate-x-1/2 w-2/3 h-px bg-gradient-to-r from-transparent via-cyan-500/60 to-transparent" />
      
      <div className="flex items-center justify-between">
        {/* Left section - Logo/Title */}
        <div className="flex items-center gap-3">
          {/* Globe logo */}
          <HudGlobe size={50} />
          
          <div className="space-y-0.5">
            <h1 className="text-lg font-mono font-bold tracking-wider text-cyan-200">
              AI COMMAND CENTER
            </h1>
            <div className="flex items-center gap-2">
              <div className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
              <span className="text-[10px] font-mono text-cyan-500/70 tracking-widest">
                SYSTEM ONLINE
              </span>
            </div>
          </div>
        </div>

        {/* Center section - Status indicators */}
        <div className="flex items-center gap-6">
          <div className="flex items-center gap-2 px-3 py-1.5 bg-slate-900/50 border border-cyan-800/30 rounded-sm">
            <Cpu size={14} className="text-cyan-400" />
            <span className="text-xs font-mono text-cyan-300">98%</span>
          </div>
          <div className="flex items-center gap-2 px-3 py-1.5 bg-slate-900/50 border border-cyan-800/30 rounded-sm">
            <Activity size={14} className="text-emerald-400" />
            <span className="text-xs font-mono text-cyan-300">ACTIVE</span>
          </div>
          <div className="flex items-center gap-2 px-3 py-1.5 bg-slate-900/50 border border-cyan-800/30 rounded-sm">
            <Wifi size={14} className="text-cyan-400" />
            <span className="text-xs font-mono text-cyan-300">SYNC</span>
          </div>
        </div>

        {/* Right section - Add Task button with dropdown */}
        <div className="relative" ref={menuRef}>
          <button
            onClick={(e) => {
              e.stopPropagation()
              setShowModelMenu(!showModelMenu)
            }}
            className="flex items-center gap-2 px-4 py-2 bg-cyan-500/10 border border-cyan-500/50 rounded-sm 
                       hover:bg-cyan-500/20 hover:border-cyan-400 hover:shadow-[0_0_15px_rgba(6,182,212,0.3)]
                       active:bg-cyan-500/30 transition-all duration-200 group"
          >
            <Plus size={16} className="text-cyan-400 group-hover:text-cyan-300" />
            <span className="text-xs font-mono font-medium text-cyan-300 uppercase tracking-wider group-hover:text-cyan-200">
              Add Task
            </span>
            <ChevronDown size={14} className={`text-cyan-400 transition-transform duration-200 ${showModelMenu ? "rotate-180" : ""}`} />
          </button>

          {/* Dropdown menu */}
          {showModelMenu && (
            <div className="absolute top-full right-0 mt-2 w-48 bg-slate-900/95 border border-cyan-500/40 rounded-sm 
                            shadow-[0_0_20px_rgba(6,182,212,0.2)] backdrop-blur-md z-50 overflow-hidden">
              <div className="px-3 py-2 border-b border-cyan-500/20">
                <span className="text-[10px] font-mono text-cyan-500/60 uppercase tracking-widest">Select Model</span>
              </div>
              {MODEL_OPTIONS.map((model) => (
                <button
                  key={model.id}
                  onClick={(e) => {
                    e.stopPropagation()
                    onAddTask?.(model.name)
                    setShowModelMenu(false)
                  }}
                  className="w-full px-3 py-2.5 flex items-center hover:bg-cyan-500/20 
                             transition-colors duration-150 group/item border-b border-cyan-500/10 last:border-0"
                >
                  <div className="flex items-center gap-2">
                    <div className="w-2 h-2 rounded-full bg-cyan-400/60 group-hover/item:bg-cyan-400 transition-colors" />
                    <span className="text-sm font-mono text-cyan-200 group-hover/item:text-cyan-100">{model.name}</span>
                  </div>
                </button>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Bottom decorative line */}
      <div className="absolute bottom-0 left-0 right-0 h-px bg-gradient-to-r from-cyan-500/30 via-cyan-500/60 to-cyan-500/30" />
      
      {/* Corner decorations */}
      <div className="absolute top-0 left-0 w-4 h-4 border-t-2 border-l-2 border-cyan-500/50" />
      <div className="absolute top-0 right-0 w-4 h-4 border-t-2 border-r-2 border-cyan-500/50" />
    </header>
  )
}

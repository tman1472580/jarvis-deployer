"use client"

import { useState, useRef, useEffect } from "react"
import { Send, Zap, XCircle, Wand2, ChevronDown } from "lucide-react"
import type { SkillDef } from "@/lib/eel-bridge"

interface PromptBarProps {
  selectedTask: string | null
  agentType?: "claude" | "gemini" | "codex" | "devin"
  onSend: (message: string) => void
  promptOptions?: [string, string][]
  promptDesc?: string
  taskStatus?: string
  onSendOption?: (num: string) => void
  onSendEscape?: () => void
  skills?: SkillDef[]
  onRunSkill?: (skillSlug: string, userPrompt: string) => void
}

export function PromptBar({
  selectedTask,
  agentType = "claude",
  onSend,
  promptOptions,
  promptDesc,
  taskStatus,
  onSendOption,
  onSendEscape,
  skills = [],
  onRunSkill,
}: PromptBarProps) {
  const [message, setMessage] = useState("")
  const [isFocused, setIsFocused] = useState(false)
  const [showSkills, setShowSkills] = useState(false)
  const [pendingSkill, setPendingSkill] = useState<SkillDef | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const skillsRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (selectedTask && inputRef.current) {
      inputRef.current.focus()
    }
  }, [selectedTask])

  // Close skill dropdown on outside click
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (skillsRef.current && !skillsRef.current.contains(e.target as Node)) {
        setShowSkills(false)
      }
    }
    document.addEventListener("mousedown", handler)
    return () => document.removeEventListener("mousedown", handler)
  }, [])

  const handleSend = () => {
    if (!selectedTask) return
    if (pendingSkill) {
      // Send skill with the typed message as user request
      onRunSkill?.(pendingSkill.slug, message.trim())
      setPendingSkill(null)
      setMessage("")
    } else if (message.trim()) {
      onSend(message)
      setMessage("")
    }
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
    if (e.key === "Escape" && pendingSkill) {
      setPendingSkill(null)
      setMessage("")
    }
  }

  const handleSelectSkill = (skill: SkillDef) => {
    setShowSkills(false)
    setPendingSkill(skill)
    setMessage("")
    setTimeout(() => inputRef.current?.focus(), 50)
  }

  const agentLabel = agentType === "gemini" ? "Gemini" : agentType === "codex" ? "Codex" : agentType === "devin" ? "Devin" : "Claude"
  const agentColor = agentType === "gemini" ? "text-blue-400" : agentType === "codex" ? "text-purple-400" : agentType === "devin" ? "text-emerald-400" : "text-cyan-400"
  const hasApproval = taskStatus === "Approval" && promptOptions && promptOptions.length > 0

  return (
    <div className="relative">
      {/* Decorative top line */}
      <div className="h-px bg-gradient-to-r from-transparent via-cyan-500/50 to-transparent mb-3" />

      {/* Pending skill banner */}
      {pendingSkill && (
        <div className="mb-2 px-2 flex items-center gap-2">
          <Wand2 size={12} className="text-violet-400 shrink-0" />
          <span className="text-[10px] font-mono text-violet-300 uppercase tracking-wider">
            Skill: {pendingSkill.name}
          </span>
          <span className="text-[10px] font-mono text-violet-500/60">— type your request below, then send</span>
          <button
            onClick={() => { setPendingSkill(null); setMessage("") }}
            className="ml-auto text-violet-500/60 hover:text-violet-300 text-[10px] font-mono"
          >
            ✕ cancel
          </button>
        </div>
      )}

      {/* Approval section */}
      {hasApproval && (
        <div className="mb-2 px-2">
          {promptDesc && (
            <div className="text-[10px] font-mono text-amber-400/70 mb-2 uppercase tracking-wider">
              {promptDesc}
            </div>
          )}
          <div className="flex items-center gap-2 flex-wrap">
            {promptOptions!.map(([num, label]) => (
              <button
                key={num}
                onClick={() => onSendOption?.(num)}
                className="px-3 py-1.5 text-xs font-mono border border-amber-500/40 bg-amber-500/10
                           text-amber-200 hover:bg-amber-500/25 hover:border-amber-400/60
                           rounded-sm transition-all duration-200"
              >
                {num}. {label}
              </button>
            ))}
            <button
              onClick={() => onSendEscape?.()}
              className="px-3 py-1.5 text-xs font-mono border border-red-500/40 bg-red-500/10
                         text-red-300 hover:bg-red-500/25 hover:border-red-400/60
                         rounded-sm transition-all duration-200 flex items-center gap-1.5"
            >
              <XCircle size={12} />
              Esc
            </button>
          </div>
        </div>
      )}

      <div className={`relative flex items-center gap-3 p-3
        bg-gradient-to-r from-slate-900/95 via-slate-900/90 to-slate-900/95
        border rounded-sm backdrop-blur-sm transition-all duration-300
        ${isFocused
          ? "border-cyan-400/70 shadow-lg shadow-cyan-500/20"
          : "border-cyan-700/40 hover:border-cyan-600/50"
        }`}
      >
        {/* Left icon */}
        <div className={`flex items-center justify-center w-10 h-10 rounded-sm
          border transition-colors duration-300
          ${selectedTask
            ? "border-cyan-500/60 bg-cyan-950/50"
            : "border-cyan-800/40 bg-slate-950/50"
          }`}
        >
          <Zap
            size={18}
            className={`transition-colors duration-300 ${
              selectedTask ? "text-cyan-400" : "text-cyan-700"
            }`}
          />
        </div>

        {/* Input area */}
        <div className="flex-1 relative">
          {selectedTask && (
            <div className="absolute -top-1 left-0 flex items-center gap-2">
              <span className="text-[9px] font-mono text-cyan-500/70 tracking-wider uppercase">
                Target: {selectedTask}
              </span>
              <span className={`text-[9px] font-mono uppercase tracking-wider ${agentColor}`}>
                [{agentLabel}]
              </span>
            </div>
          )}

          <input
            ref={inputRef}
            type="text"
            value={message}
            onChange={(e) => setMessage(e.target.value)}
            onKeyDown={handleKeyDown}
            onFocus={() => setIsFocused(true)}
            onBlur={() => setIsFocused(false)}
            placeholder={selectedTask ? "Enter command..." : "Select a task session first..."}
            disabled={!selectedTask}
            className={`w-full bg-transparent border-none outline-none
              text-sm font-mono placeholder:text-cyan-700/50
              ${selectedTask ? "text-cyan-100" : "text-cyan-700"}
              ${selectedTask ? "pt-2" : ""}
            `}
          />
        </div>

        {/* Skills button */}
        {skills.length > 0 && selectedTask && (
          <div className="relative" ref={skillsRef}>
            <button
              onClick={() => setShowSkills(v => !v)}
              className={`flex items-center gap-1 px-2 h-10 rounded-sm border transition-all duration-200
                ${showSkills || pendingSkill
                  ? "border-violet-400/60 bg-violet-500/20 text-violet-300"
                  : "border-violet-700/40 bg-violet-950/30 text-violet-600 hover:border-violet-500/50 hover:text-violet-400"
                }`}
              title="Apply a skill"
            >
              <Wand2 size={14} />
              <span className="text-[10px] font-mono hidden sm:inline">Skills</span>
              <ChevronDown size={10} className={`transition-transform ${showSkills ? "rotate-180" : ""}`} />
            </button>

            {showSkills && (
              <div className="absolute bottom-full right-0 mb-2 w-72 bg-slate-900 border border-violet-500/40 rounded-sm shadow-xl shadow-violet-500/10 z-50 overflow-hidden">
                <div className="px-3 py-2 bg-slate-800/80 border-b border-violet-600/20">
                  <span className="text-[10px] font-mono text-violet-300 uppercase tracking-wider">
                    Apply skill → {agentLabel}
                  </span>
                </div>
                <div className="max-h-64 overflow-y-auto">
                  {skills.map(skill => (
                    <button
                      key={skill.slug}
                      onClick={() => handleSelectSkill(skill)}
                      className="w-full text-left px-3 py-2.5 hover:bg-violet-500/10 border-b border-violet-800/20 last:border-0 transition-colors group"
                    >
                      <div className="text-xs font-mono text-violet-200 group-hover:text-violet-100">
                        {skill.name}
                      </div>
                      {skill.description && (
                        <div className="text-[10px] font-mono text-violet-500/70 mt-0.5 line-clamp-2">
                          {skill.description}
                        </div>
                      )}
                    </button>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}

        {/* Send button */}
        <button
          onClick={handleSend}
          disabled={(!message.trim() && !pendingSkill) || !selectedTask}
          className={`flex items-center justify-center w-10 h-10 rounded-sm
            border transition-all duration-300 group
            ${(message.trim() || pendingSkill) && selectedTask
              ? pendingSkill
                ? "border-violet-400/60 bg-violet-500/20 hover:bg-violet-500/30 cursor-pointer"
                : "border-cyan-400/60 bg-cyan-500/20 hover:bg-cyan-500/30 cursor-pointer"
              : "border-cyan-800/30 bg-slate-950/30 cursor-not-allowed"
            }`}
        >
          <Send
            size={16}
            className={`transition-all duration-300 ${
              (message.trim() || pendingSkill) && selectedTask
                ? pendingSkill
                  ? "text-violet-300 group-hover:text-violet-100 group-hover:translate-x-0.5 group-hover:-translate-y-0.5"
                  : "text-cyan-300 group-hover:text-cyan-100 group-hover:translate-x-0.5 group-hover:-translate-y-0.5"
                : "text-cyan-800"
            }`}
          />
        </button>

        {/* Corner accents */}
        <div className="absolute top-0 left-0 w-2 h-2 border-t border-l border-cyan-500/50" />
        <div className="absolute top-0 right-0 w-2 h-2 border-t border-r border-cyan-500/50" />
        <div className="absolute bottom-0 left-0 w-2 h-2 border-b border-l border-cyan-500/50" />
        <div className="absolute bottom-0 right-0 w-2 h-2 border-b border-r border-cyan-500/50" />

        {/* Glow effect */}
        {isFocused && (
          <div className="absolute inset-0 rounded-sm pointer-events-none animate-pulse-glow"
            style={{ boxShadow: "0 0 30px oklch(0.7 0.15 195 / 0.15)" }}
          />
        )}
      </div>

      {/* Bottom decorative elements */}
      <div className="flex justify-between items-center mt-2 px-2">
        <div className="flex items-center gap-2">
          <div className="w-1 h-1 rounded-full bg-cyan-500/60" />
          <span className="text-[9px] font-mono text-cyan-600/50 tracking-wider">JARVIS INTERFACE v2.0</span>
        </div>
        <div className="flex items-center gap-3">
          <span className="text-[9px] font-mono text-cyan-600/40">ENTER TO SEND</span>
          <div className="flex gap-0.5">
            {Array.from({ length: 5 }).map((_, i) => (
              <div key={i} className={`w-1 h-2 ${i < 4 ? "bg-cyan-500/60" : "bg-cyan-800/40"}`} />
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}

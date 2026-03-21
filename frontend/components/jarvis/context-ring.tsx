"use client"

import { useState, useEffect } from "react"

interface ContextRingProps {
  percent: number
  used: number
  total: number
  size?: number
  isActive?: boolean
}

// Pre-computed angles to avoid hydration mismatch
const OUTER_TICKS = Array.from({ length: 60 }, (_, i) => {
  const angle = (i * 6 * Math.PI) / 180
  return {
    cos: Math.cos(angle),
    sin: Math.sin(angle),
    isMajor: i % 5 === 0,
    isMid: i % 5 === 2 || i % 5 === 3
  }
})

const SEGMENT_ARCS = Array.from({ length: 8 }, (_, i) => ({
  startAngle: i * 45 + 5,
  endAngle: i * 45 + 38
}))

const INNER_SEGMENTS = Array.from({ length: 12 }, (_, i) => ({
  startAngle: i * 30 + 3,
  endAngle: i * 30 + 25
}))

const CORE_ARCS = Array.from({ length: 4 }, (_, i) => ({
  startAngle: i * 90 + 10,
  endAngle: i * 90 + 70
}))

function polarToCartesian(cx: number, cy: number, r: number, angleDeg: number) {
  const angleRad = ((angleDeg - 90) * Math.PI) / 180
  return {
    x: cx + r * Math.cos(angleRad),
    y: cy + r * Math.sin(angleRad)
  }
}

function describeArc(cx: number, cy: number, r: number, startAngle: number, endAngle: number) {
  const start = polarToCartesian(cx, cy, r, endAngle)
  const end = polarToCartesian(cx, cy, r, startAngle)
  const largeArcFlag = endAngle - startAngle <= 180 ? "0" : "1"
  return `M ${start.x} ${start.y} A ${r} ${r} 0 ${largeArcFlag} 0 ${end.x} ${end.y}`
}

export function ContextRing({ percent, used, total, size = 120, isActive = false }: ContextRingProps) {
  const [mounted, setMounted] = useState(false)
  
  useEffect(() => {
    setMounted(true)
  }, [])

  const center = size / 2
  const outerRadius = size / 2 - 2
  const ring1Radius = outerRadius - 6
  const ring2Radius = outerRadius - 14
  const ring3Radius = outerRadius - 22
  const ring4Radius = outerRadius - 30
  const coreRadius = outerRadius - 38

  // Progress arc calculation
  const progressAngle = (percent / 100) * 360
  
  // Color based on percentage: green -> yellow as it approaches 100%
  const getProgressColor = (pct: number) => {
    if (pct < 30) return { start: "#22c55e", mid: "#22c55e", end: "#16a34a" } // green
    if (pct < 50) return { start: "#22c55e", mid: "#84cc16", end: "#65a30d" } // green to lime
    if (pct < 70) return { start: "#84cc16", mid: "#a3e635", end: "#65a30d" } // lime
    if (pct < 85) return { start: "#eab308", mid: "#facc15", end: "#ca8a04" } // yellow
    return { start: "#f59e0b", mid: "#fbbf24", end: "#d97706" } // amber/orange warning
  }
  
  const progressColors = getProgressColor(percent)
  
  // Text color based on percentage
  const getTextColor = (pct: number) => {
    if (pct < 30) return "text-emerald-400"
    if (pct < 50) return "text-lime-400"
    if (pct < 70) return "text-lime-300"
    if (pct < 85) return "text-yellow-400"
    return "text-amber-400"
  }

  return (
    <div className="relative" style={{ width: size, height: size }}>
      {mounted && (
        <>
          {/* Outermost tick marks layer */}
          <svg 
            className="absolute inset-0 animate-rotate-slow"
            width={size} 
            height={size}
          >
            {OUTER_TICKS.map((tick, i) => {
              const innerR = tick.isMajor ? outerRadius - 8 : tick.isMid ? outerRadius - 5 : outerRadius - 3
              const outerR = outerRadius
              const x1 = center + innerR * tick.cos
              const y1 = center + innerR * tick.sin
              const x2 = center + outerR * tick.cos
              const y2 = center + outerR * tick.sin
              return (
                <line
                  key={i}
                  x1={x1}
                  y1={y1}
                  x2={x2}
                  y2={y2}
                  stroke="currentColor"
                  strokeWidth={tick.isMajor ? 2 : 1}
                  className={tick.isMajor ? "text-cyan-400/80" : "text-cyan-600/40"}
                />
              )
            })}
          </svg>

          {/* Ring 1: Segmented outer arcs */}
          <svg 
            className="absolute inset-0 animate-rotate-reverse"
            width={size} 
            height={size}
          >
            {SEGMENT_ARCS.map((arc, i) => (
              <path
                key={i}
                d={describeArc(center, center, ring1Radius, arc.startAngle, arc.endAngle)}
                fill="none"
                stroke="currentColor"
                strokeWidth={4}
                className="text-cyan-500/60"
                strokeLinecap="round"
              />
            ))}
          </svg>

          {/* Ring 2: Thin segmented ring */}
          <svg 
            className="absolute inset-0"
            width={size} 
            height={size}
          >
            {INNER_SEGMENTS.map((arc, i) => (
              <path
                key={i}
                d={describeArc(center, center, ring2Radius, arc.startAngle, arc.endAngle)}
                fill="none"
                stroke="currentColor"
                strokeWidth={2}
                className="text-cyan-400/40"
              />
            ))}
          </svg>

          {/* Ring 3: Progress ring (solid background) */}
          <svg 
            className="absolute inset-0"
            width={size} 
            height={size}
          >
            <circle
              cx={center}
              cy={center}
              r={ring3Radius}
              fill="none"
              stroke="currentColor"
              strokeWidth={6}
              className="text-cyan-900/40"
            />
          </svg>

          {/* Ring 3: Progress ring (active progress) */}
          <svg 
            className="absolute inset-0"
            width={size} 
            height={size}
          >
            {progressAngle > 0 && (
              <path
                d={describeArc(center, center, ring3Radius, 0, Math.min(progressAngle, 359.9))}
                fill="none"
                stroke={`url(#progressGradient-${percent})`}
                strokeWidth={6}
                strokeLinecap="round"
                className="drop-shadow-[0_0_4px_rgba(6,182,212,0.6)]"
              />
            )}
            <defs>
              <linearGradient id={`progressGradient-${percent}`} x1="0%" y1="0%" x2="100%" y2="100%">
                <stop offset="0%" stopColor={progressColors.start} />
                <stop offset="50%" stopColor={progressColors.mid} />
                <stop offset="100%" stopColor={progressColors.end} />
              </linearGradient>
            </defs>
          </svg>

          {/* Ring 4: Inner decorative ring with gaps */}
          <svg 
            className="absolute inset-0 animate-rotate-slow"
            width={size} 
            height={size}
          >
            {CORE_ARCS.map((arc, i) => (
              <path
                key={i}
                d={describeArc(center, center, ring4Radius, arc.startAngle, arc.endAngle)}
                fill="none"
                stroke="currentColor"
                strokeWidth={3}
                className="text-cyan-300/50"
                strokeLinecap="round"
              />
            ))}
          </svg>

          {/* Core circle */}
          <svg 
            className="absolute inset-0"
            width={size} 
            height={size}
          >
            <circle
              cx={center}
              cy={center}
              r={coreRadius}
              fill="none"
              stroke="currentColor"
              strokeWidth={2}
              className="text-cyan-500/60"
            />
            <circle
              cx={center}
              cy={center}
              r={coreRadius - 6}
              fill="currentColor"
              className="text-cyan-950/80"
            />
            <circle
              cx={center}
              cy={center}
              r={4}
              fill="currentColor"
              className="text-cyan-400/60"
            />
          </svg>

          {/* Small rectangular segments around outer edge */}
          <svg 
            className="absolute inset-0 animate-rotate-reverse"
            width={size} 
            height={size}
          >
            {Array.from({ length: 16 }, (_, i) => {
              const angle = (i * 22.5 * Math.PI) / 180
              const r = ring1Radius + 2
              const x = center + r * Math.cos(angle) - 2
              const y = center + r * Math.sin(angle) - 1
              return (
                <rect
                  key={i}
                  x={x}
                  y={y}
                  width={4}
                  height={2}
                  rx={0.5}
                  fill="currentColor"
                  className={i % 4 === 0 ? "text-cyan-400/80" : "text-cyan-600/40"}
                  transform={`rotate(${i * 22.5}, ${center}, ${center})`}
                />
              )
            })}
          </svg>
        </>
      )}

      {/* Center content */}
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <div className={`text-lg font-mono font-bold tabular-nums ${getTextColor(percent)}`}>
          {percent}%
        </div>
        <div className="text-[8px] font-mono text-cyan-500/60 tracking-wider uppercase">
          CXT
        </div>
      </div>

      {/* Glow effect when active */}
      {isActive && (
        <div 
          className="absolute inset-0 rounded-full animate-pulse-glow pointer-events-none"
          style={{
            boxShadow: "0 0 25px rgba(6,182,212,0.4), inset 0 0 15px rgba(6,182,212,0.15)"
          }}
        />
      )}
    </div>
  )
}

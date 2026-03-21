"use client"

import { useEffect, useState } from "react"

interface Particle {
  id: number
  left: number
  top: number
  delay: number
  duration: number
}

export function HudBackground() {
  const [mounted, setMounted] = useState(false)
  const [particles, setParticles] = useState<Particle[]>([])

  useEffect(() => {
    setMounted(true)
    // Generate particles only on client side to avoid hydration mismatch
    const newParticles = Array.from({ length: 20 }).map((_, i) => ({
      id: i,
      left: Math.random() * 100,
      top: Math.random() * 100,
      delay: Math.random() * 3,
      duration: 2 + Math.random() * 2
    }))
    setParticles(newParticles)
  }, [])

  return (
    <div className="fixed inset-0 pointer-events-none overflow-hidden">
      {/* Base gradient */}
      <div className="absolute inset-0 bg-gradient-to-br from-slate-950 via-slate-900 to-slate-950" />
      
      {/* Grid pattern */}
      <svg className="absolute inset-0 w-full h-full opacity-20">
        <defs>
          <pattern 
            id="grid" 
            width="50" 
            height="50" 
            patternUnits="userSpaceOnUse"
          >
            <path 
              d="M 50 0 L 0 0 0 50" 
              fill="none" 
              stroke="currentColor" 
              strokeWidth="0.5"
              className="text-cyan-500"
            />
          </pattern>
          <pattern 
            id="grid-large" 
            width="200" 
            height="200" 
            patternUnits="userSpaceOnUse"
          >
            <path 
              d="M 200 0 L 0 0 0 200" 
              fill="none" 
              stroke="currentColor" 
              strokeWidth="1"
              className="text-cyan-400"
            />
          </pattern>
        </defs>
        <rect width="100%" height="100%" fill="url(#grid)" />
        <rect width="100%" height="100%" fill="url(#grid-large)" />
      </svg>

      {/* Radial glow in center */}
      <div 
        className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[800px] h-[800px] rounded-full opacity-30"
        style={{
          background: "radial-gradient(circle, oklch(0.5 0.12 195 / 0.15) 0%, transparent 70%)"
        }}
      />

      {/* Corner vignette */}
      <div 
        className="absolute inset-0"
        style={{
          background: "radial-gradient(ellipse at center, transparent 40%, oklch(0.08 0.02 240 / 0.8) 100%)"
        }}
      />

      {/* Floating particles - only rendered after mount */}
      {mounted && particles.map((particle) => (
        <div
          key={particle.id}
          className="absolute w-1 h-1 rounded-full bg-cyan-400/30 animate-pulse"
          style={{
            left: `${particle.left}%`,
            top: `${particle.top}%`,
            animationDelay: `${particle.delay}s`,
            animationDuration: `${particle.duration}s`
          }}
        />
      ))}

      {/* Scan lines overlay */}
      <div 
        className="absolute inset-0 opacity-5"
        style={{
          backgroundImage: "repeating-linear-gradient(0deg, transparent, transparent 2px, oklch(0.7 0.15 195) 2px, oklch(0.7 0.15 195) 4px)",
          backgroundSize: "100% 4px"
        }}
      />
    </div>
  )
}

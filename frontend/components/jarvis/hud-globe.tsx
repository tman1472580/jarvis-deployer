"use client"

import { useEffect, useState } from "react"

interface HudGlobeProps {
  size?: number
}

export function HudGlobe({ size = 120 }: HudGlobeProps) {
  const [mounted, setMounted] = useState(false)
  const [rotation, setRotation] = useState(0)
  const [axisRotation, setAxisRotation] = useState(0)

  useEffect(() => {
    setMounted(true)
    const interval = setInterval(() => {
      setRotation(prev => (prev + 1) % 360)
      setAxisRotation(prev => (prev + 0.3) % 360)
    }, 50)
    return () => clearInterval(interval)
  }, [])

  const center = size / 2
  const globeRadius = size * 0.32
  
  // Tilt angle for diagonal axis (in radians)
  const tiltAngle = 23.5 * Math.PI / 180 // Earth-like tilt
  const axisAngleRad = axisRotation * Math.PI / 180
  
  // Generate dots on sphere surface with diagonal axis rotation
  const generateSphereDots = () => {
    const dots: { x: number; y: number; opacity: number; size: number }[] = []
    const latLines = 14
    const lonLines = 28
    
    for (let lat = -80; lat <= 80; lat += 180 / latLines) {
      const latRad = (lat * Math.PI) / 180
      const adjustedLon = lonLines * Math.cos(latRad)
      
      for (let lon = 0; lon < 360; lon += 360 / Math.max(8, adjustedLon)) {
        const lonRad = ((lon + rotation) * Math.PI) / 180
        
        // Base 3D coordinates
        let x = globeRadius * Math.cos(latRad) * Math.sin(lonRad)
        let y = globeRadius * Math.sin(latRad)
        let z = globeRadius * Math.cos(latRad) * Math.cos(lonRad)
        
        // Apply tilt around X axis
        const y1 = y * Math.cos(tiltAngle) - z * Math.sin(tiltAngle)
        const z1 = y * Math.sin(tiltAngle) + z * Math.cos(tiltAngle)
        y = y1
        z = z1
        
        // Apply axis rotation around Y axis
        const x2 = x * Math.cos(axisAngleRad) + z * Math.sin(axisAngleRad)
        const z2 = -x * Math.sin(axisAngleRad) + z * Math.cos(axisAngleRad)
        x = x2
        z = z2
        
        // Only show front-facing dots
        if (z > -globeRadius * 0.2) {
          const opacity = 0.25 + (z / globeRadius) * 0.75
          const dotSize = 0.4 + (z / globeRadius) * 0.4
          dots.push({
            x: center + x,
            y: center - y,
            opacity: Math.max(0.15, opacity),
            size: Math.max(0.3, dotSize)
          })
        }
      }
    }
    return dots
  }

  // Generate longitude lines with diagonal rotation
  const generateLonLines = () => {
    const lines: { path: string; opacity: number }[] = []
    for (let lon = 0; lon < 180; lon += 30) {
      const lonRad = ((lon + rotation) * Math.PI) / 180
      const points: string[] = []
      let avgZ = 0
      let count = 0
      
      for (let lat = -90; lat <= 90; lat += 5) {
        const latRad = (lat * Math.PI) / 180
        
        let x = globeRadius * Math.cos(latRad) * Math.sin(lonRad)
        let y = globeRadius * Math.sin(latRad)
        let z = globeRadius * Math.cos(latRad) * Math.cos(lonRad)
        
        // Apply tilt
        const y1 = y * Math.cos(tiltAngle) - z * Math.sin(tiltAngle)
        const z1 = y * Math.sin(tiltAngle) + z * Math.cos(tiltAngle)
        y = y1
        z = z1
        
        // Apply axis rotation
        const x2 = x * Math.cos(axisAngleRad) + z * Math.sin(axisAngleRad)
        const z2 = -x * Math.sin(axisAngleRad) + z * Math.cos(axisAngleRad)
        x = x2
        z = z2
        
        if (z > -globeRadius * 0.05) {
          points.push(`${center + x},${center - y}`)
          avgZ += z
          count++
        }
      }
      if (points.length > 1) {
        lines.push({
          path: `M ${points.join(" L ")}`,
          opacity: count > 0 ? 0.1 + (avgZ / count / globeRadius) * 0.2 : 0.1
        })
      }
    }
    return lines
  }

  if (!mounted) {
    return <div style={{ width: size, height: size }} />
  }

  const dots = generateSphereDots()
  const lonLines = generateLonLines()

  return (
    <div className="relative" style={{ width: size, height: size }}>
      <svg
        width={size}
        height={size}
        viewBox={`0 0 ${size} ${size}`}
        className="overflow-visible"
      >
        {/* Outermost orbit ring - tilted */}
        <ellipse
          cx={center}
          cy={center}
          rx={globeRadius + 18}
          ry={globeRadius * 0.35}
          fill="none"
          stroke="rgba(34, 211, 238, 0.25)"
          strokeWidth={1.5}
          style={{
            transform: `rotate(${-15 + axisRotation * 0.2}deg)`,
            transformOrigin: `${center}px ${center}px`
          }}
        />
        
        {/* Second orbit ring - opposite tilt */}
        <ellipse
          cx={center}
          cy={center}
          rx={globeRadius + 14}
          ry={globeRadius * 0.4}
          fill="none"
          stroke="rgba(34, 211, 238, 0.2)"
          strokeWidth={1}
          strokeDasharray="3 3"
          style={{
            transform: `rotate(${25 - axisRotation * 0.3}deg)`,
            transformOrigin: `${center}px ${center}px`
          }}
        />
        
        {/* Third orbit ring - vertical-ish */}
        <ellipse
          cx={center}
          cy={center}
          rx={globeRadius * 0.3}
          ry={globeRadius + 10}
          fill="none"
          stroke="rgba(34, 211, 238, 0.15)"
          strokeWidth={1}
          style={{
            transform: `rotate(${axisRotation * 0.5}deg)`,
            transformOrigin: `${center}px ${center}px`
          }}
        />
        
        {/* Fourth orbit ring - diagonal */}
        <ellipse
          cx={center}
          cy={center}
          rx={globeRadius + 6}
          ry={globeRadius * 0.5}
          fill="none"
          stroke="rgba(34, 211, 238, 0.3)"
          strokeWidth={2}
          strokeDasharray={`${globeRadius * 0.5} ${globeRadius * 0.3}`}
          strokeDashoffset={rotation * 0.8}
          style={{
            transform: `rotate(${-35}deg)`,
            transformOrigin: `${center}px ${center}px`
          }}
        />

        {/* Globe outline */}
        <circle
          cx={center}
          cy={center}
          r={globeRadius}
          fill="none"
          stroke="rgba(34, 211, 238, 0.35)"
          strokeWidth={1}
        />
        
        {/* Inner glow */}
        <circle
          cx={center}
          cy={center}
          r={globeRadius - 1}
          fill="url(#globeGradient)"
        />
        
        {/* Longitude lines */}
        {lonLines.map((line, i) => (
          <path
            key={`lon-${i}`}
            d={line.path}
            fill="none"
            stroke={`rgba(34, 211, 238, ${line.opacity})`}
            strokeWidth={0.5}
          />
        ))}
        
        {/* Dots on sphere - smaller */}
        {dots.map((dot, i) => (
          <circle
            key={i}
            cx={dot.x}
            cy={dot.y}
            r={dot.size}
            fill={`rgba(34, 211, 238, ${dot.opacity})`}
          />
        ))}
        
        {/* Moving satellite dot on orbit */}
        <circle
          cx={center + (globeRadius + 14) * Math.cos(rotation * 0.05)}
          cy={center + (globeRadius * 0.4) * Math.sin(rotation * 0.05)}
          r={2}
          fill="rgba(34, 211, 238, 0.9)"
          style={{
            transform: `rotate(${25 - axisRotation * 0.3}deg)`,
            transformOrigin: `${center}px ${center}px`
          }}
        />
        
        {/* Gradient definition */}
        <defs>
          <radialGradient id="globeGradient" cx="35%" cy="35%">
            <stop offset="0%" stopColor="rgba(34, 211, 238, 0.08)" />
            <stop offset="100%" stopColor="rgba(15, 23, 42, 0.9)" />
          </radialGradient>
        </defs>
      </svg>
      
      {/* Center glow dot */}
      <div 
        className="absolute w-1.5 h-1.5 bg-cyan-400 rounded-full"
        style={{ 
          left: center - 3, 
          top: center - 3,
          boxShadow: "0 0 8px rgba(34, 211, 238, 0.8)"
        }}
      />
    </div>
  )
}

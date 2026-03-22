"use client"

import { useState, useEffect, useCallback, useRef } from "react"
import { eel, type PaneData, type UsageStats } from "@/lib/eel-bridge"

const STATE_POLL_MS = 3000
const USAGE_POLL_MS = 120000

export function useEelState() {
  const [panes, setPanes] = useState<PaneData[]>([])
  const [usageStats, setUsageStats] = useState<UsageStats | null>(null)
  const [connected, setConnected] = useState(false)
  const mountedRef = useRef(true)

  const fetchState = useCallback(async () => {
    const data = await eel.getFullState()
    if (mountedRef.current) {
      setPanes(Array.isArray(data) ? data : [])
      setConnected(eel.isReady())
    }
  }, [])

  const fetchUsage = useCallback(async () => {
    const data = await eel.getUsageStats()
    if (mountedRef.current) {
      setUsageStats(data)
    }
  }, [])

  const refresh = useCallback(async () => {
    await fetchState()
    await fetchUsage()
  }, [fetchState, fetchUsage])

  useEffect(() => {
    mountedRef.current = true

    // Initial fetch
    fetchState()
    fetchUsage()

    // Polling intervals
    const stateInterval = setInterval(fetchState, STATE_POLL_MS)
    const usageInterval = setInterval(fetchUsage, USAGE_POLL_MS)

    return () => {
      mountedRef.current = false
      clearInterval(stateInterval)
      clearInterval(usageInterval)
    }
  }, [fetchState, fetchUsage])

  return { panes, usageStats, connected, refresh }
}

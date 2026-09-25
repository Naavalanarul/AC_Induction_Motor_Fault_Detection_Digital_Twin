import { useEffect, useRef, useState } from 'react'
import { loadSession } from '../api/client'
import type { Frame } from '../api/types'

export type StreamStatus = 'connecting' | 'open' | 'closed'

/** Live frames for one motor over WebSocket, with exponential-backoff reconnect. */
export function useMotorStream(motorId: number | null, historyLen = 120) {
  const [frame, setFrame] = useState<Frame | null>(null)
  const [trend, setTrend] = useState<{ t: number; rpm: number; temp: number; severity: number; load: number }[]>([])
  const [status, setStatus] = useState<StreamStatus>('connecting')
  const retry = useRef(0)

  useEffect(() => {
    if (motorId == null) return
    let ws: WebSocket | null = null
    let timer: ReturnType<typeof setTimeout> | undefined
    let stopped = false

    const connect = () => {
      const token = loadSession()?.access_token
      if (!token) return
      setStatus('connecting')
      const proto = location.protocol === 'https:' ? 'wss' : 'ws'
      ws = new WebSocket(`${proto}://${location.host}/api/v1/ws/motors/${motorId}/stream?token=${encodeURIComponent(token)}`)
      ws.onopen = () => {
        retry.current = 0
        setStatus('open')
      }
      ws.onmessage = (ev) => {
        const f = JSON.parse(ev.data) as Frame
        // spectra/scalogram are only sent when they change: keep the previous ones otherwise
        setFrame((prev) => ({
          ...f,
          spectra: f.spectra ?? prev?.spectra ?? {},
          scalogram: f.scalogram !== undefined ? f.scalogram : (prev?.scalogram ?? null),
        }))
        setTrend((prev) => {
          const next = [
            ...prev,
            {
              t: f.t,
              rpm: f.mechanics.rpm,
              temp: f.sensors.temp?.value ?? NaN,
              severity: f.supervisory.smoothed_severity,
              load: f.supervisory.load_cmd,
            },
          ]
          return next.length > historyLen ? next.slice(next.length - historyLen) : next
        })
      }
      ws.onclose = () => {
        setStatus('closed')
        if (stopped) return
        const delay = Math.min(10000, 500 * 2 ** retry.current++)
        timer = setTimeout(connect, delay)
      }
    }
    connect()
    return () => {
      stopped = true
      clearTimeout(timer)
      ws?.close()
      setFrame(null)
      setTrend([])
    }
  }, [motorId, historyLen])

  return { frame, trend, status }
}

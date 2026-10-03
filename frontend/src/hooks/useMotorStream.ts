import { useCallback, useEffect, useRef, useState } from 'react'
import { getValidToken, notifyAuthLost, refresh } from '../api/client'
import type { Frame } from '../api/types'

export type StreamStatus = 'connecting' | 'open' | 'closed'

/** Live frames for one motor over WebSocket, with exponential-backoff reconnect and proactive auth refresh. */
export function useMotorStream(motorId: number | null, historyLen = 120, onFrame?: (frame: Frame) => void) {
  const [frame, setFrame] = useState<Frame | null>(null)
  const [trend, setTrend] = useState<{ t: number; rpm: number; temp: number; severity: number; load: number }[]>([])
  const [status, setStatus] = useState<StreamStatus>('connecting')
  const retry = useRef(0)
  const [nonce, setNonce] = useState(0)
  const onFrameRef = useRef(onFrame)
  useEffect(() => {
    onFrameRef.current = onFrame
  }, [onFrame])

  const reconnect = useCallback(() => {
    retry.current = 0
    setNonce((n) => n + 1)
  }, [])

  useEffect(() => {
    if (motorId == null) return
    let ws: WebSocket | null = null
    let timer: ReturnType<typeof setTimeout> | undefined
    let stopped = false

    const connect = async () => {
      if (stopped) return
      setStatus('connecting')

      // Ensure we have a valid, non-expired access token
      let token = await getValidToken()
      if (!token) {
        const refreshed = await refresh()
        if (refreshed) {
          token = await getValidToken()
        }
      }

      if (!token) {
        setStatus('closed')
        notifyAuthLost()
        return
      }

      if (stopped) return

      const proto = location.protocol === 'https:' ? 'wss' : 'ws'
      ws = new WebSocket(`${proto}://${location.host}/api/v1/ws/motors/${motorId}/stream`, ['bearer', token])

      ws.onopen = () => {
        retry.current = 0
        setStatus('open')
      }

      ws.onmessage = (ev) => {
        try {
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
                rpm: f.mechanics?.rpm ?? 0,
                temp: f.sensors?.temp?.value ?? f.sensors?.thermal?.value ?? NaN,
                severity: f.supervisory?.smoothed_severity ?? 0,
                load: f.supervisory?.load_cmd ?? 1,
              },
            ]
            return next.length > historyLen ? next.slice(next.length - historyLen) : next
          })
          onFrameRef.current?.(f)
        } catch (e) {
          console.error('Failed to parse telemetry frame:', e)
        }
      }

      ws.onclose = async (ev) => {
        setStatus('closed')
        if (stopped) return

        // If closed because token was rejected/expired (4401 / 4403 / 1008)
        if (ev.code === 4401 || ev.code === 4403 || ev.code === 1008) {
          const ok = await refresh()
          if (!ok) {
            notifyAuthLost()
            return
          }
        }

        const delay = Math.min(10000, 500 * 2 ** retry.current++)
        timer = setTimeout(connect, delay)
      }

      ws.onerror = () => {
        // ws.onclose will follow
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
  }, [motorId, historyLen, nonce])

  return { frame, trend, status, reconnect }
}

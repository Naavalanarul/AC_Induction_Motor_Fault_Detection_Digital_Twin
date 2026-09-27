import React, { useState } from 'react'
import { api } from '../api/client'

export interface TrippedMotorInfo {
  id: number
  name: string
  reason_code?: string
  acknowledged?: boolean
}

export interface TripBannerProps {
  trippedMotors: TrippedMotorInfo[]
  onAcknowledged?: (motorId: number) => void
}

export const TripBanner: React.FC<TripBannerProps> = ({ trippedMotors, onAcknowledged }) => {
  const [loadingIds, setLoadingIds] = useState<Record<number, boolean>>({})
  const [errorMsg, setErrorMsg] = useState<string | null>(null)

  // Filter to active, unacknowledged trips
  const activeTrips = trippedMotors.filter((m) => !m.acknowledged)

  if (activeTrips.length === 0) {
    return null
  }

  const handleAcknowledge = async (motorId: number) => {
    setLoadingIds((prev) => ({ ...prev, [motorId]: true }))
    setErrorMsg(null)
    try {
      await api(`/motors/${motorId}/supervisory/override`, {
        method: 'POST',
        body: JSON.stringify({ action: 'ack' }),
      })
      onAcknowledged?.(motorId)
    } catch (err: unknown) {
      setErrorMsg(err instanceof Error ? err.message : 'Failed to acknowledge trip')
    } finally {
      setLoadingIds((prev) => ({ ...prev, [motorId]: false }))
    }
  }

  return (
    <div
      role="alert"
      aria-live="assertive"
      className="sticky top-0 z-50 w-full border-b border-rose-500/50 bg-rose-950/90 backdrop-blur-md px-4 py-3 text-white shadow-xl shadow-rose-950/40"
    >
      <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <span className="relative flex h-3 w-3">
            <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-rose-400 opacity-75"></span>
            <span className="relative inline-flex h-3 w-3 rounded-full bg-rose-500"></span>
          </span>
          <div className="flex flex-col sm:flex-row sm:items-center sm:gap-2">
            <span className="font-mono text-sm font-bold uppercase tracking-wider text-rose-300">
              EMERGENCY TRIP ACTIVE:
            </span>
            <span className="text-sm font-medium text-neutral-200">
              {activeTrips.map((m) => `${m.name} [${m.reason_code || 'TRIP'}]`).join(', ')}
            </span>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-3">
          {errorMsg && (
            <span className="text-xs text-rose-300 font-mono">
              Error: {errorMsg}
            </span>
          )}
          {activeTrips.map((m) => (
            <button
              key={m.id}
              onClick={() => handleAcknowledge(m.id)}
              disabled={loadingIds[m.id]}
              className="inline-flex items-center gap-1.5 rounded bg-rose-600 px-3 py-1.5 text-xs font-semibold text-white shadow-sm transition hover:bg-rose-500 focus:outline-none focus:ring-2 focus:ring-rose-400 focus:ring-offset-2 focus:ring-offset-rose-950 disabled:opacity-50"
            >
              {loadingIds[m.id] ? 'Acknowledging...' : `Acknowledge ${m.name}`}
            </button>
          ))}
        </div>
      </div>
    </div>
  )
}

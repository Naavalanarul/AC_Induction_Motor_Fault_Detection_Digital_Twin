import React, { useState } from 'react'
import { api, resetTrip } from '../api/client'
import { label } from '../api/types'

export interface TrippedMotorInfo {
  id: number
  name: string
  reason_code?: string
  acknowledged?: boolean
  latched_fault?: string | null
  latched_severity?: number | null
}

export interface TripBannerProps {
  trippedMotors: TrippedMotorInfo[]
  onAcknowledged?: (motorId: number) => void
  onReset?: (motorId: number) => void
}

/**
 * Persistent banner for every latched trip. A trip stays latched -- and the motor stays stopped --
 * until an operator resets it; acknowledging only silences the alarm, and clearing the injected
 * fault does not restart the motor. The banner therefore stays visible after acknowledgement and
 * offers Reset, showing the backend's reason when a reset is refused (cooldown, temperature,
 * fault still at trip level, lockout).
 */
export const TripBanner: React.FC<TripBannerProps> = ({ trippedMotors, onAcknowledged, onReset }) => {
  const [loadingIds, setLoadingIds] = useState<Record<number, boolean>>({})
  const [errorMsg, setErrorMsg] = useState<string | null>(null)

  if (trippedMotors.length === 0) {
    return null
  }

  const run = async (motorId: number, fn: () => Promise<unknown>, done?: (id: number) => void, what = 'action') => {
    setLoadingIds((prev) => ({ ...prev, [motorId]: true }))
    setErrorMsg(null)
    try {
      await fn()
      done?.(motorId)
    } catch (err: unknown) {
      setErrorMsg(`${what} refused: ${err instanceof Error ? err.message : 'request failed'}`)
    } finally {
      setLoadingIds((prev) => ({ ...prev, [motorId]: false }))
    }
  }

  const acknowledge = (motorId: number) =>
    run(
      motorId,
      () => api(`/motors/${motorId}/supervisory/override`, { method: 'POST', body: JSON.stringify({ action: 'ack' }) }),
      onAcknowledged,
      'Acknowledge',
    )

  const reset = (motorId: number) => run(motorId, () => resetTrip(motorId), onReset ?? onAcknowledged, 'Reset')

  return (
    <div
      role="alert"
      aria-live="assertive"
      className="sticky top-0 z-50 w-full border-b border-[var(--critical)]/25 bg-[#0d0708]/95 backdrop-blur-md px-4 py-3 text-[var(--ink)] shadow-lg shadow-black/60"
    >
      <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <span className="relative flex h-3 w-3">
            <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-[var(--critical)] opacity-60"></span>
            <span className="relative inline-flex h-3 w-3 rounded-full bg-[var(--critical)]"></span>
          </span>
          <div className="flex flex-col">
            <div className="flex flex-col sm:flex-row sm:items-center sm:gap-2">
              <span className="font-mono text-sm font-bold uppercase tracking-wider text-[var(--critical)]">
                EMERGENCY TRIP ACTIVE:
              </span>
              <span className="text-sm font-medium text-[var(--ink-2)]">
                {trippedMotors
                  .map((m) => {
                    const fault = m.latched_fault
                      ? ` — latched ${label(m.latched_fault)}${
                          m.latched_severity != null ? ` (sev ${m.latched_severity.toFixed(2)})` : ''
                        }`
                      : ''
                    return `${m.name} [${m.reason_code || 'TRIP'}]${fault}${m.acknowledged ? ' · acknowledged' : ''}`
                  })
                  .join(', ')}
              </span>
            </div>
            <span className="text-xs text-[var(--muted)]">
              The motor stays stopped until the trip is reset. Clearing the fault alone does not restart it.
            </span>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-3">
          {errorMsg && <span className="text-xs text-[var(--critical)] font-mono">{errorMsg}</span>}
          {trippedMotors.map((m) => (
            <span key={m.id} className="flex gap-2">
              {!m.acknowledged && (
                <button
                  onClick={() => acknowledge(m.id)}
                  disabled={loadingIds[m.id]}
                  className="inline-flex items-center gap-1.5 rounded bg-[var(--critical)] hover:opacity-90 px-3 py-1.5 text-xs font-semibold text-[#000000] shadow-sm transition focus:outline-none disabled:opacity-50"
                >
                  {loadingIds[m.id] ? 'Working...' : `Acknowledge ${m.name}`}
                </button>
              )}
              <button
                onClick={() => reset(m.id)}
                disabled={loadingIds[m.id]}
                className="inline-flex items-center gap-1.5 rounded border border-[var(--critical)] px-3 py-1.5 text-xs font-semibold text-[var(--ink)] hover:bg-[var(--critical)]/15 transition focus:outline-none disabled:opacity-50"
              >
                {`Reset trip ${m.name}`}
              </button>
            </span>
          ))}
        </div>
      </div>
    </div>
  )
}

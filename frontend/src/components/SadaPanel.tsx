import { useState } from 'react'
import { api, newIdempotencyKey } from '../api/client'
import type { Supervisory } from '../api/types'
import { StatusBadge } from './StatusBadge'

export function SadaPanel({ motorId, sup, canOperate }: { motorId: number; sup: Supervisory; canOperate: boolean }) {
  const [manual, setManual] = useState(0.6)
  const [msg, setMsg] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const send = async (action: string, load?: number) => {
    setMsg(null)
    setBusy(true)
    try {
      await api(`/motors/${motorId}/supervisory/override`, {
        method: 'POST',
        headers: { 'Idempotency-Key': newIdempotencyKey() },
        body: JSON.stringify({ action, load }),
      })
      setMsg(`${action.replace('_', ' ')} sent successfully`)
    } catch (e) {
      setMsg((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const loadPercent = Math.round(sup.load_cmd * 100)

  return (
    <section className="card flex flex-col justify-between" aria-labelledby="sada-h">
      <div>
        <header className="flex items-center justify-between pb-3 border-b border-[var(--border)]">
          <h2 id="sada-h" className="text-xs font-semibold uppercase tracking-wider text-[var(--muted)] flex items-center gap-2">
            <span className="inline-block w-1.5 h-1.5 rounded-full bg-[var(--ink-2)]" />
            SADA Supervisory Core
          </h2>
          <span className="text-[11px] num px-2 py-0.5 rounded bg-[var(--surface-raised)] border border-[var(--border)] text-[var(--muted)]">
            {sup.trip ? 'TRIP LATCHED' : sup.state}
          </span>
        </header>

        {/* State Banner */}
        <div className="mt-3 p-3 rounded-lg bg-[var(--surface-raised)] border border-[var(--border)] flex items-center justify-between gap-3">
          <div className="flex items-center gap-2.5">
            <StatusBadge state={sup.state} />
            <div className="flex flex-col">
              <span className="text-[10px] uppercase font-medium text-[var(--muted)]">Trigger Reason</span>
              <span className="text-xs num font-medium text-[var(--ink)]" data-testid="reason">
                {sup.reason_code}
              </span>
            </div>
          </div>
          {sup.trip && (
            <span className="px-2 py-0.5 rounded bg-rose-500/10 text-rose-400 border border-rose-500/20 text-xs font-medium num">
              DE-ENERGIZED
            </span>
          )}
        </div>

        {/* Supervisory Metrics List */}
        <dl className="grid grid-cols-2 gap-2 mt-3 text-xs tabular">
          <div className="p-2.5 rounded-md bg-[var(--surface-raised)] border border-[var(--border)]">
            <dt className="text-[var(--muted)] text-[11px]">Load Command</dt>
            <dd className="text-base font-bold text-[var(--ink)] num mt-0.5" data-testid="load-cmd">
              {loadPercent}%{sup.manual_override ? ' (manual)' : ''}
            </dd>
          </div>

          <div className="p-2.5 rounded-md bg-[var(--surface-raised)] border border-[var(--border)] hover:border-[var(--border-hover)] transition-colors">
            <dt className="text-[var(--muted)] text-[11px]">Smoothed Severity</dt>
            <dd className="text-base font-bold text-[var(--ink)] num mt-0.5">
              {sup.smoothed_severity.toFixed(2)}
            </dd>
          </div>

          <div className="p-2.5 rounded-md bg-[var(--surface-raised)] border border-[var(--border)] hover:border-[var(--border-hover)] transition-colors">
            <dt className="text-[var(--muted)] text-[11px]">Process Load</dt>
            <dd className="text-base font-bold text-[var(--ink)] num mt-0.5">
              {sup.base_load_nm.toFixed(1)} N·m
            </dd>
          </div>

          <div className="p-2.5 rounded-md bg-[var(--surface-raised)] border border-[var(--border)] hover:border-[var(--border-hover)] transition-colors">
            <dt className="text-[var(--muted)] text-[11px]">Trip State</dt>
            <dd className="text-base font-bold text-[var(--ink)] num mt-0.5">
              {sup.trip ? 'Yes (latched)' : 'No'}
            </dd>
          </div>
        </dl>
      </div>

      {/* Operator Actions Deck */}
      {canOperate ? (
        <div className="mt-4 pt-3 border-t border-[var(--border)] flex flex-col gap-2.5">
          <div className="flex flex-wrap items-center gap-2">
            <button
              className="btn flex-1 text-xs transition-colors"
              onClick={() => send('ack')}
              disabled={sup.acknowledged || busy}
            >
              Acknowledge
            </button>
            <button
              className="btn flex-1 text-xs bg-rose-500/10 hover:bg-rose-500/20 text-rose-300 border-rose-500/20 disabled:opacity-40 transition-colors"
              onClick={() => send('reset')}
              disabled={!sup.trip || busy}
            >
              Reset trip
            </button>
          </div>

          <div className="flex items-center gap-2 bg-[var(--surface-raised)] p-2 rounded-md border border-[var(--border)]">
            <label className="text-xs text-[var(--ink-2)] flex items-center gap-2 flex-1">
              <span className="text-[11px] text-[var(--muted)] whitespace-nowrap">Manual load:</span>
              <input
                type="range"
                min={0}
                max={1}
                step={0.05}
                value={manual}
                aria-label="manual load"
                className="flex-1 cursor-pointer"
                onChange={(e) => setManual(Number(e.target.value))}
              />
              <span className="tabular num text-xs w-9 text-right text-[var(--ink)]">
                {Math.round(manual * 100)}%
              </span>
            </label>
            <button className="btn btn-primary text-xs py-1 px-3" onClick={() => send('set_load', manual)} disabled={busy}>
              Set
            </button>
            {sup.manual_override && (
              <button className="btn text-xs py-1 px-2.5" onClick={() => send('release_load')} disabled={busy}>
                Release
              </button>
            )}
          </div>
        </div>
      ) : (
        <div className="mt-3 text-[11px] text-[var(--muted)] italic text-center">
          Operator privileges required for supervisory overrides
        </div>
      )}

      {msg && (
        <p className="text-xs text-amber-400 mt-2 p-1.5 rounded bg-amber-500/10 border border-amber-500/20" role="status">
          {msg}
        </p>
      )}
    </section>
  )
}

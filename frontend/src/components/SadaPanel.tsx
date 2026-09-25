import { useState } from 'react'
import { api, newIdempotencyKey } from '../api/client'
import type { Supervisory } from '../api/types'
import { StatusBadge } from './StatusBadge'

export function SadaPanel({ motorId, sup, canOperate }: { motorId: number; sup: Supervisory; canOperate: boolean }) {
  const [manual, setManual] = useState(0.6)
  const [msg, setMsg] = useState<string | null>(null)

  const send = async (action: string, load?: number) => {
    setMsg(null)
    try {
      await api(`/motors/${motorId}/supervisory/override`, {
        method: 'POST',
        headers: { 'Idempotency-Key': newIdempotencyKey() },
        body: JSON.stringify({ action, load }),
      })
      setMsg(`${action.replace('_', ' ')} sent`)
    } catch (e) {
      setMsg((e as Error).message)
    }
  }

  return (
    <section className="card" aria-labelledby="sada-h">
      <h2 id="sada-h" className="text-sm font-semibold muted uppercase tracking-wide">SADA supervisory</h2>
      <div className="mt-2 flex items-center gap-3">
        <StatusBadge state={sup.state} />
        <span className="text-xs tabular muted" data-testid="reason">{sup.reason_code}</span>
      </div>
      <dl className="grid grid-cols-2 gap-y-1 mt-3 text-sm tabular">
        <dt className="muted">Load command</dt>
        <dd data-testid="load-cmd">{Math.round(sup.load_cmd * 100)}%{sup.manual_override ? ' (manual)' : ''}</dd>
        <dt className="muted">Smoothed severity</dt>
        <dd>{sup.smoothed_severity.toFixed(2)}</dd>
        <dt className="muted">Process load</dt>
        <dd>{sup.base_load_nm.toFixed(1)} N·m</dd>
        <dt className="muted">Trip</dt>
        <dd>{sup.trip ? 'Yes (latched)' : 'No'}</dd>
      </dl>
      {canOperate && (
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <button className="btn" onClick={() => send('ack')} disabled={sup.acknowledged}>Acknowledge</button>
          <button className="btn" onClick={() => send('reset')} disabled={!sup.trip}>Reset trip</button>
          <label className="text-xs muted flex items-center gap-1">
            Manual load
            <input type="range" min={0} max={1} step={0.05} value={manual} aria-label="manual load"
              onChange={(e) => setManual(Number(e.target.value))} />
            <span className="tabular w-8">{Math.round(manual * 100)}%</span>
          </label>
          <button className="btn" onClick={() => send('set_load', manual)}>Set</button>
          {sup.manual_override && <button className="btn" onClick={() => send('release_load')}>Release</button>}
        </div>
      )}
      {msg && <p className="text-xs muted mt-2" role="status">{msg}</p>}
    </section>
  )
}

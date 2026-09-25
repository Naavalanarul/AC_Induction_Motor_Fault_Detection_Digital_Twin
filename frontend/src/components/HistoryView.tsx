import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { api } from '../api/client'
import type { DiagnosisRow, HistoryEvent, Page } from '../api/types'
import { label } from '../api/types'

const DIAG_TYPES = ['', 'healthy', 'broken_rotor_bar', 'interturn_short', 'eccentricity', 'bearing_inner', 'bearing_outer',
  'bearing_ball', 'unbalance', 'misalignment', 'overheating', 'supply_anomaly']

function toIso(local: string) {
  return local ? new Date(local).toISOString().replace('Z', '') : ''
}

export function HistoryView({ motorId }: { motorId: number }) {
  const [start, setStart] = useState('')
  const [end, setEnd] = useState('')
  const [faultType, setFaultType] = useState('')
  const [offset, setOffset] = useState(0)
  const limit = 25
  const qs = new URLSearchParams()
  if (start) qs.set('start', toIso(start))
  if (end) qs.set('end', toIso(end))

  const events = useQuery({
    queryKey: ['history', motorId, start, end],
    queryFn: () => api<HistoryEvent[]>(`/motors/${motorId}/history?${qs}`),
    refetchInterval: 5000,
  })
  const dq = new URLSearchParams(qs)
  if (faultType) dq.set('fault_type', faultType)
  dq.set('limit', String(limit))
  dq.set('offset', String(offset))
  const diags = useQuery({
    queryKey: ['diagnoses', motorId, start, end, faultType, offset],
    queryFn: () => api<Page<DiagnosisRow>>(`/motors/${motorId}/diagnoses?${dq}`),
    refetchInterval: 5000,
  })

  return (
    <div className="grid gap-3">
      <div className="card flex flex-wrap items-end gap-3 text-sm">
        <label className="grid gap-1"><span className="muted text-xs">From (UTC)</span>
          <input className="input" type="datetime-local" value={start} onChange={(e) => { setStart(e.target.value); setOffset(0) }} /></label>
        <label className="grid gap-1"><span className="muted text-xs">To (UTC)</span>
          <input className="input" type="datetime-local" value={end} onChange={(e) => { setEnd(e.target.value); setOffset(0) }} /></label>
        <label className="grid gap-1"><span className="muted text-xs">Diagnosis type</span>
          <select className="input" value={faultType} onChange={(e) => { setFaultType(e.target.value); setOffset(0) }}>
            {DIAG_TYPES.map((d) => <option key={d} value={d}>{d ? label(d) : 'all'}</option>)}
          </select></label>
      </div>
      <div className="grid gap-3 lg:grid-cols-2">
        <section className="card">
          <h2 className="text-sm font-semibold mb-2">Fault &amp; supervisory timeline</h2>
          {events.isError && <p className="text-sm" role="alert">{(events.error as Error).message}</p>}
          <ol className="text-sm grid gap-1 max-h-[480px] overflow-auto">
            {(events.data ?? []).map((e, i) => (
              <li key={i} className="grid grid-cols-[150px_1fr] gap-2" style={{ borderTop: '1px solid var(--grid)', paddingTop: 4 }}>
                <span className="tabular muted text-xs">{new Date(e.ts + 'Z').toLocaleString()}</span>
                <span>{describe(e)}</span>
              </li>
            ))}
            {events.data?.length === 0 && <li className="muted">No events</li>}
          </ol>
        </section>
        <section className="card">
          <h2 className="text-sm font-semibold mb-2">Persisted diagnoses ({diags.data?.total ?? 0})</h2>
          <table className="w-full text-xs tabular">
            <thead><tr className="muted text-left"><th className="font-normal">Time</th><th className="font-normal">Fault</th>
              <th className="font-normal text-right">Conf.</th><th className="font-normal text-right">Sev.</th></tr></thead>
            <tbody>
              {(diags.data?.items ?? []).map((d) => (
                <tr key={d.id} style={{ borderTop: '1px solid var(--grid)' }}>
                  <td className="py-0.5">{new Date(d.ts + 'Z').toLocaleTimeString()}</td>
                  <td className="capitalize">{label(d.fault_type)}</td>
                  <td className="text-right">{d.confidence.toFixed(2)}</td>
                  <td className="text-right">{d.severity_score.toFixed(2)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="flex gap-2 mt-2 items-center text-xs">
            <button className="btn" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - limit))}>Newer</button>
            <button className="btn" disabled={!diags.data || offset + limit >= diags.data.total} onClick={() => setOffset(offset + limit)}>Older</button>
            <span className="muted">{offset + 1}–{Math.min(offset + limit, diags.data?.total ?? 0)}</span>
          </div>
        </section>
      </div>
    </div>
  )
}

function describe(e: HistoryEvent) {
  const d = e.data as Record<string, string | number | boolean>
  if (e.kind === 'supervisory') return `SADA ${d.state} · load ${Math.round(Number(d.load_cmd) * 100)}% · ${d.reason_code}${d.actor !== 'sada' ? ` (by ${d.actor})` : ''}`
  const what = `${label(String(d.fault_type))} (sev ${Number(d.severity).toFixed(2)})`
  return e.kind === 'fault_injected' ? `Fault injected: ${what}${d.created_by ? ` by ${d.created_by}` : ''}` : `Fault cleared: ${what}`
}

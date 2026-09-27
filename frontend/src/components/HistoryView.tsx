import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { api } from '../api/client'
import type { DiagnosisRow, HistoryEvent, Page } from '../api/types'
import { label } from '../api/types'

const DIAG_TYPES = [
  '',
  'healthy',
  'broken_rotor_bar',
  'interturn_short',
  'eccentricity',
  'bearing_inner',
  'bearing_outer',
  'bearing_ball',
  'unbalance',
  'misalignment',
  'overheating',
  'supply_anomaly',
  'indeterminate',
]

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
    <div className="grid gap-4">
      {/* Filter Control Bar */}
      <div className="card flex flex-wrap items-center gap-4 text-xs bg-[var(--surface-raised)] border border-[var(--border)]">
        <div className="flex items-center gap-2">
          <span className="text-[11px] font-semibold uppercase tracking-wider text-[var(--muted)]">Filters:</span>
        </div>
        <label className="flex items-center gap-2">
          <span className="text-[var(--muted)]">From (UTC)</span>
          <input
            className="input text-xs py-1"
            type="datetime-local"
            value={start}
            onChange={(e) => {
              setStart(e.target.value)
              setOffset(0)
            }}
          />
        </label>
        <label className="flex items-center gap-2">
          <span className="text-[var(--muted)]">To (UTC)</span>
          <input
            className="input text-xs py-1"
            type="datetime-local"
            value={end}
            onChange={(e) => {
              setEnd(e.target.value)
              setOffset(0)
            }}
          />
        </label>
        <label className="flex items-center gap-2">
          <span className="text-[var(--muted)]">Diagnosis type</span>
          <select
            className="input text-xs py-1 min-w-[140px]"
            value={faultType}
            onChange={(e) => {
              setFaultType(e.target.value)
              setOffset(0)
            }}
          >
            {DIAG_TYPES.map((d) => (
              <option key={d} value={d}>
                {d ? label(d) : 'All Verdicts'}
              </option>
            ))}
          </select>
        </label>
        {(start || end || faultType) && (
          <button
            className="btn text-xs py-1 px-2.5 text-[var(--muted)] hover:text-[var(--foreground)]"
            onClick={() => {
              setStart('')
              setEnd('')
              setFaultType('')
              setOffset(0)
            }}
          >
            Reset
          </button>
        )}
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        {/* Timeline Panel */}
        <section className="card flex flex-col justify-between" aria-label="Fault & supervisory timeline">
          <div>
            <header className="flex items-center justify-between pb-3 border-b border-[var(--border)] mb-3">
              <h2 className="text-xs font-semibold uppercase tracking-wider text-[var(--muted)] flex items-center gap-2">
                <span className="inline-block w-2 h-2 rounded-full bg-cyan-400" />
                Fault &amp; Supervisory Timeline
              </h2>
              <span className="text-[11px] font-mono num text-[var(--muted)]">{events.data?.length ?? 0} Events</span>
            </header>
            {events.isError && <p className="text-xs text-rose-400 p-2 rounded bg-rose-500/10" role="alert">{(events.error as Error).message}</p>}
            <ol className="text-xs grid gap-2 max-h-[500px] overflow-auto pr-1">
              {(events.data ?? []).map((e, i) => (
                <li
                  key={i}
                  className="p-2.5 rounded-lg bg-[var(--surface-raised)] border border-[var(--border)] flex items-start gap-3 hover:border-[var(--border-hover)] transition-colors"
                >
                  <span className="tabular font-mono num text-[11px] text-[var(--accent)] whitespace-nowrap pt-0.5">
                    {new Date(e.ts + 'Z').toLocaleTimeString()}
                  </span>
                  <span className="text-[var(--foreground)] flex-1 leading-relaxed">{describe(e)}</span>
                </li>
              ))}
              {events.data?.length === 0 && (
                <li className="text-[var(--muted)] text-xs py-8 text-center italic">No supervisory or fault events recorded</li>
              )}
            </ol>
          </div>
        </section>

        {/* Persisted Diagnoses Panel */}
        <section className="card flex flex-col justify-between" aria-label="Persisted diagnoses">
          <div>
            <header className="flex items-center justify-between pb-3 border-b border-[var(--border)] mb-3">
              <h2 className="text-xs font-semibold uppercase tracking-wider text-[var(--muted)] flex items-center gap-2">
                <span className="inline-block w-2 h-2 rounded-full bg-emerald-400" />
                Persisted Diagnoses ({diags.data?.total ?? 0})
              </h2>
              <span className="text-[11px] font-mono num text-[var(--muted)]">
                {offset + 1}–{Math.min(offset + limit, diags.data?.total ?? 0)} of {diags.data?.total ?? 0}
              </span>
            </header>

            <div className="overflow-hidden rounded-lg border border-[var(--border)] bg-[var(--surface-raised)]">
              <table className="w-full text-xs tabular">
                <thead>
                  <tr className="bg-[var(--surface)] text-[var(--muted)] text-left border-b border-[var(--border)]">
                    <th className="font-medium px-3 py-2">Time</th>
                    <th className="font-medium px-2 py-2">Fault</th>
                    <th className="font-medium px-2 py-2 text-right">Conf.</th>
                    <th className="font-medium px-3 py-2 text-right">Sev.</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-[var(--border)]">
                  {(diags.data?.items ?? []).map((d) => {
                    const isIndeterminate = d.fault_type === 'indeterminate'
                    return (
                      <tr
                        key={d.id}
                        className={isIndeterminate ? 'bg-amber-50 dark:bg-amber-950/40' : 'hover:bg-[var(--surface-hover)] transition-colors'}
                      >
                        <td className="px-3 py-1.5 font-mono num text-[11px] text-[var(--muted)]">
                          {new Date(d.ts + 'Z').toLocaleTimeString()}
                        </td>
                        <td className={isIndeterminate ? 'text-amber-600 dark:text-amber-400 font-medium px-2 py-1.5' : 'capitalize px-2 py-1.5 text-[var(--foreground)]'}>
                          {isIndeterminate ? indeterminateLabel(d) : label(d.fault_type)}
                        </td>
                        <td className="px-2 py-1.5 text-right font-mono num text-[var(--foreground)]">
                          {d.confidence.toFixed(2)}
                        </td>
                        <td className="px-3 py-1.5 text-right font-mono num text-[var(--foreground)]">
                          {d.severity_score.toFixed(2)}
                        </td>
                      </tr>
                    )
                  })}
                  {(!diags.data?.items || diags.data.items.length === 0) && (
                    <tr>
                      <td colSpan={4} className="py-8 text-center text-[var(--muted)] text-xs italic">
                        No diagnoses matching filters
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>

          <div className="flex gap-2 mt-3 items-center justify-between text-xs pt-2 border-t border-[var(--border)]">
            <div className="flex gap-2">
              <button
                className="btn text-xs py-1 px-3"
                disabled={offset === 0}
                onClick={() => setOffset(Math.max(0, offset - limit))}
              >
                ← Newer
              </button>
              <button
                className="btn text-xs py-1 px-3"
                disabled={!diags.data || offset + limit >= diags.data.total}
                onClick={() => setOffset(offset + limit)}
              >
                Older →
              </button>
            </div>
            <span className="text-[11px] text-[var(--muted)] font-mono num">Page size: {limit}</span>
          </div>
        </section>
      </div>
    </div>
  )
}

function indeterminateLabel(d: DiagnosisRow): string {
  const override = d.per_sensor_scores_json?.['sada_override'] as Record<string, unknown> | undefined
  const latched = override?.['sada_latched_fault'] as string | undefined
  const suffix = latched ? ` (last known: ${label(latched)})` : ''
  return `⏸ monitoring paused — motor stopped${suffix}`
}

function describe(e: HistoryEvent) {
  const d = e.data as Record<string, string | number | boolean>
  if (e.kind === 'supervisory') {
    return `SADA ${d.state} · load ${Math.round(Number(d.load_cmd) * 100)}% · ${d.reason_code}${
      d.actor !== 'sada' ? ` (by ${d.actor})` : ''
    }`
  }
  const what = `${label(String(d.fault_type))} (sev ${Number(d.severity).toFixed(2)})`
  return e.kind === 'fault_injected'
    ? `Fault injected: ${what}${d.created_by ? ` by ${d.created_by}` : ''}`
    : `Fault cleared: ${what}`
}

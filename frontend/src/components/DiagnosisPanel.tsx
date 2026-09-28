import { Activity } from 'lucide-react'
import type { Diagnosis } from '../api/types'
import { label } from '../api/types'

const SOURCES: [string, string][] = [
  ['electrical_residual', 'Electrical (DT residual)'],
  ['ml_classifier', 'Vibration / acoustic'],
  ['thermal', 'Thermal'],
  ['supply', 'Supply'],
]

function Meter({ value, name, color = 'var(--series-1)' }: { value: number; name: string; color?: string }) {
  const pct = Math.round(value * 100)
  return (
    <div className="flex items-center gap-3">
      <div
        className="h-1.5 flex-1 rounded-full overflow-hidden bg-white/10 dark:bg-zinc-800/80"
        role="meter"
        aria-label={name}
        aria-valuenow={pct}
        aria-valuemin={0}
        aria-valuemax={100}
      >
        <div
          className="h-full rounded-full transition-all duration-300 ease-out"
          style={{
            width: `${pct}%`,
            background: color,
          }}
        />
      </div>
      <span className="tabular num text-xs font-medium w-10 text-right text-[var(--ink-2)]">{pct}%</span>
    </div>
  )
}

export function DiagnosisPanel({ diagnosis, mlBackend }: { diagnosis: Diagnosis; mlBackend: string }) {
  const healthy = diagnosis.fault_type === 'healthy'
  const indeterminate = diagnosis.fault_type === 'indeterminate'

  const verdictColor = healthy
    ? 'text-emerald-400'
    : indeterminate
    ? 'text-amber-400'
    : 'text-rose-400'

  const verdictBadgeBg = healthy
    ? 'bg-emerald-500/5 border-emerald-500/20'
    : indeterminate
    ? 'bg-amber-500/5 border-amber-500/20'
    : 'bg-rose-500/5 border-rose-500/20'

  return (
    <section className="card flex flex-col justify-between" aria-labelledby="diag-h">
      <div>
        <header className="flex items-center justify-between pb-3 border-b border-[var(--border)]">
          <div className="flex items-center gap-2">
            <span className="w-7 h-7 rounded-md bg-[var(--surface-raised)] border border-[var(--border)] flex items-center justify-center text-[var(--accent)]">
              <Activity size={14} />
            </span>
            <div>
              <span className="eyebrow block" style={{ fontSize: 9 }}>AI PREDICTIVE CLASSIFIER</span>
              <h2 id="diag-h" className="text-xs font-semibold uppercase tracking-wider text-[var(--ink)]">
                Fused Fault Diagnostics
              </h2>
            </div>
          </div>
          <span className="text-[11px] num px-2 py-0.5 rounded bg-[var(--surface-raised)] border border-[var(--border)] text-[var(--muted)]">
            v{diagnosis.schema_version}
          </span>
        </header>

        {/* Hero Verdict Display */}
        <div className={`mt-3 p-3.5 rounded-lg border ${verdictBadgeBg} flex items-center justify-between gap-3 transition-colors`}>
          <div>
            <div className="text-[10px] uppercase tracking-wider text-[var(--muted)] font-medium">Fused Condition</div>
            <div className={`text-xl font-bold capitalize mt-0.5 ${verdictColor}`} data-testid="fused-fault">
              {label(diagnosis.fault_type)}
            </div>
          </div>
          <div className="text-right">
            <span className="text-xs num text-[var(--muted)] block">t = {diagnosis.t.toFixed(1)}s</span>
            <span className={`text-[10px] px-2 py-0.5 rounded font-medium uppercase ${verdictColor} bg-white/5`}>
              {healthy ? 'Optimal' : indeterminate ? 'Paused' : 'Fault Detected'}
            </span>
          </div>
        </div>

        {/* Dual Confidence & Severity Meters */}
        <div className="grid grid-cols-[80px_1fr] gap-y-2.5 mt-4 items-center text-xs">
          <span className="text-[var(--muted)] font-medium">Confidence</span>
          <Meter value={diagnosis.confidence} name="diagnosis confidence" color="var(--series-1)" />

          <span className="text-[var(--muted)] font-medium">Severity</span>
          <Meter
            value={healthy ? 0 : diagnosis.severity}
            name="diagnosis severity"
            color={diagnosis.severity > 0.7 ? 'var(--critical)' : diagnosis.severity > 0.3 ? 'var(--warning)' : 'var(--good)'}
          />
        </div>

        {/* Per-Channel Status Breakdown Table */}
        <div className="mt-4 overflow-hidden rounded-md border border-[var(--border)] bg-[var(--surface-raised)]">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-[var(--border)] text-[var(--muted)] text-left">
                <th className="font-medium px-3 py-1.5">Channel</th>
                <th className="font-medium px-2 py-1.5">Verdict</th>
                <th className="font-medium px-2 py-1.5 text-right">Conf.</th>
                <th className="font-medium px-3 py-1.5 text-right">Sev.</th>
              </tr>
            </thead>
            <tbody className="tabular divide-y divide-[var(--border-subtle)]">
              {SOURCES.map(([key, name]) => {
                const v = diagnosis.per_sensor_scores[key]
                const isAvail = v?.available
                const chFault = v ? v.fault_type : 'unknown'
                const isChHealthy = chFault === 'healthy'

                return (
                  <tr key={key} className="hover:bg-white/[0.02] transition-colors">
                    <td className="px-3 py-1.5 text-[var(--ink)]">
                      {name}
                      {key === 'ml_classifier' && (
                        <span className="text-[10px] text-[var(--muted)] ml-1 font-mono">
                          ({mlBackend === 'conv_bilstm' ? 'Conv-BiLSTM' : 'rules'})
                        </span>
                      )}
                    </td>
                    <td className="px-2 py-1.5">
                      {v ? (
                        isAvail ? (
                          <span
                            className={`inline-block px-1.5 py-0.2 rounded text-[11px] font-medium capitalize ${
                              isChHealthy ? 'text-emerald-400 bg-emerald-500/10' : 'text-amber-400 bg-amber-500/10'
                            }`}
                          >
                            {label(v.fault_type)}
                          </span>
                        ) : (
                          <span className="text-[var(--muted)] italic">unavailable</span>
                        )
                      ) : (
                        '—'
                      )}
                    </td>
                    <td className="px-2 py-1.5 text-right num text-[var(--ink-2)]">
                      {isAvail && typeof v?.confidence === 'number' ? v.confidence.toFixed(2) : '—'}
                    </td>
                    <td className="px-3 py-1.5 text-right num text-[var(--ink-2)]">
                      {isAvail && typeof v?.severity === 'number' ? v.severity.toFixed(2) : '—'}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </div>

      {diagnosis.secondary && diagnosis.secondary.length > 0 && (
        <p className="mt-3 pt-2.5 border-t border-[var(--border)] text-xs text-[var(--muted)]">
          Also considered:{' '}
          {diagnosis.secondary
            .map((item: unknown) => {
              const s = item as Record<string, unknown>
              const fault = (s.fault_type as string) || (s.sada_latched_fault as string)
              if (!fault) return null
              const conf =
                typeof s.confidence === 'number'
                  ? s.confidence.toFixed(2)
                  : typeof s.sada_latched_severity === 'number'
                  ? `latched sev ${s.sada_latched_severity.toFixed(2)}`
                  : null
              return `${label(fault)}${conf ? ` (${conf})` : ''}`
            })
            .filter(Boolean)
            .join(', ')}
        </p>
      )}
    </section>
  )
}

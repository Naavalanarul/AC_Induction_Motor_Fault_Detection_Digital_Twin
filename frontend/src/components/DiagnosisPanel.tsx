import type { Diagnosis } from '../api/types'
import { label } from '../api/types'

const SOURCES: [string, string][] = [
  ['electrical_residual', 'Electrical (DT residual)'],
  ['ml_classifier', 'Vibration / acoustic'],
  ['thermal', 'Thermal'],
  ['supply', 'Supply'],
]

function Meter({ value, name }: { value: number; name: string }) {
  return (
    <div className="flex items-center gap-2">
      <div className="h-1.5 flex-1 rounded-full" style={{ background: 'var(--grid)' }} role="meter" aria-label={name}
        aria-valuenow={Math.round(value * 100)} aria-valuemin={0} aria-valuemax={100}>
        <div className="h-1.5 rounded-full" style={{ width: `${Math.round(value * 100)}%`, background: 'var(--series-1)' }} />
      </div>
      <span className="tabular text-xs w-9 text-right">{Math.round(value * 100)}%</span>
    </div>
  )
}

export function DiagnosisPanel({ diagnosis, mlBackend }: { diagnosis: Diagnosis; mlBackend: string }) {
  const healthy = diagnosis.fault_type === 'healthy'
  return (
    <section className="card" aria-labelledby="diag-h">
      <h2 id="diag-h" className="text-sm font-semibold muted uppercase tracking-wide">Overall diagnosis</h2>
      <div className="mt-2 text-2xl font-semibold capitalize" data-testid="fused-fault">{label(diagnosis.fault_type)}</div>
      <div className="grid grid-cols-[90px_1fr] gap-y-1 mt-2 text-sm">
        <span className="muted">Confidence</span>
        <Meter value={diagnosis.confidence} name="diagnosis confidence" />
        <span className="muted">Severity</span>
        <Meter value={healthy ? 0 : diagnosis.severity} name="diagnosis severity" />
      </div>
      <table className="w-full mt-3 text-xs">
        <thead>
          <tr className="muted text-left">
            <th className="font-normal py-1">Channel</th>
            <th className="font-normal">Verdict</th>
            <th className="font-normal text-right">Conf.</th>
            <th className="font-normal text-right">Sev.</th>
          </tr>
        </thead>
        <tbody className="tabular">
          {SOURCES.map(([key, name]) => {
            const v = diagnosis.per_sensor_scores[key]
            return (
              <tr key={key} style={{ borderTop: '1px solid var(--grid)' }}>
                <td className="py-1">
                  {name}
                  {key === 'ml_classifier' && <span className="muted"> ({mlBackend === 'conv_bilstm' ? 'Conv-BiLSTM' : 'rules'})</span>}
                </td>
                <td className="capitalize">{v ? (v.available ? label(v.fault_type) : 'unavailable') : '—'}</td>
                <td className="text-right">{v?.available ? v.confidence.toFixed(2) : '—'}</td>
                <td className="text-right">{v?.available ? v.severity.toFixed(2) : '—'}</td>
              </tr>
            )
          })}
        </tbody>
      </table>
      {diagnosis.secondary.length > 0 && (
        <p className="text-xs muted mt-2">
          Also considered: {diagnosis.secondary.map((s) => `${label(s.fault_type)} (${s.confidence.toFixed(2)})`).join(', ')}
        </p>
      )}
    </section>
  )
}

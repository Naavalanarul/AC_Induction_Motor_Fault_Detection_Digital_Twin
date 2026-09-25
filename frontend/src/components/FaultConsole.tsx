import { useState } from 'react'
import { api, newIdempotencyKey } from '../api/client'
import { FAULT_TYPES, label, type ActiveFault, type FaultType } from '../api/types'

function paramsFor(ft: FaultType, p: { phase: string; ecc: string; volt: string; count: number }) {
  switch (ft) {
    case 'interturn_short':
      return { phase: p.phase }
    case 'eccentricity':
      return { type: p.ecc }
    case 'voltage_anomaly':
      return { type: p.volt }
    case 'broken_rotor_bar':
      return { count: p.count }
    default:
      return {}
  }
}

export function FaultConsole({ motorId, faults, canOperate }: { motorId: number; faults: ActiveFault[]; canOperate: boolean }) {
  const [ft, setFt] = useState<FaultType>('bearing_outer')
  const [severity, setSeverity] = useState(0.5)
  const [p, setP] = useState({ phase: 'a', ecc: 'dynamic', volt: 'sag', count: 2 })
  const [msg, setMsg] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const inject = async () => {
    setBusy(true)
    setMsg(null)
    try {
      const sev = ft === 'broken_rotor_bar' ? p.count / 8 : severity
      await api(`/motors/${motorId}/faults`, {
        method: 'POST',
        headers: { 'Idempotency-Key': newIdempotencyKey() },
        body: JSON.stringify({ fault_type: ft, severity: sev, params: paramsFor(ft, p) }),
      })
      setMsg(`Injected ${label(ft)}`)
    } catch (e) {
      setMsg((e as Error).message)
    } finally {
      setBusy(false)
    }
  }
  const clear = async (id: number) => {
    try {
      await api(`/motors/${motorId}/faults/${id}`, { method: 'DELETE' })
    } catch (e) {
      setMsg((e as Error).message)
    }
  }

  return (
    <section className="card" aria-labelledby="fault-h">
      <h2 id="fault-h" className="text-sm font-semibold muted uppercase tracking-wide">Fault injection</h2>
      {canOperate ? (
        <div className="mt-2 grid gap-2 text-sm">
          <label className="flex items-center gap-2">
            <span className="muted w-16">Type</span>
            <select className="input flex-1" value={ft} onChange={(e) => setFt(e.target.value as FaultType)} aria-label="fault type">
              {FAULT_TYPES.map((f) => (
                <option key={f} value={f}>{label(f)}</option>
              ))}
            </select>
          </label>
          {ft === 'broken_rotor_bar' ? (
            <label className="flex items-center gap-2">
              <span className="muted w-16">Bars</span>
              <input className="input w-20" type="number" min={1} max={8} value={p.count} aria-label="broken bars"
                onChange={(e) => setP({ ...p, count: Math.max(1, Math.min(8, Number(e.target.value))) })} />
            </label>
          ) : (
            <label className="flex items-center gap-2">
              <span className="muted w-16">Severity</span>
              <input className="flex-1" type="range" min={0.05} max={1} step={0.05} value={severity} aria-label="fault severity"
                onChange={(e) => setSeverity(Number(e.target.value))} />
              <span className="tabular w-10 text-right">{severity.toFixed(2)}</span>
            </label>
          )}
          {ft === 'interturn_short' && (
            <label className="flex items-center gap-2">
              <span className="muted w-16">Phase</span>
              <select className="input" value={p.phase} onChange={(e) => setP({ ...p, phase: e.target.value })} aria-label="phase">
                {['a', 'b', 'c'].map((x) => <option key={x}>{x}</option>)}
              </select>
            </label>
          )}
          {ft === 'eccentricity' && (
            <label className="flex items-center gap-2">
              <span className="muted w-16">Kind</span>
              <select className="input" value={p.ecc} onChange={(e) => setP({ ...p, ecc: e.target.value })} aria-label="eccentricity type">
                <option>dynamic</option>
                <option>static</option>
              </select>
            </label>
          )}
          {ft === 'voltage_anomaly' && (
            <label className="flex items-center gap-2">
              <span className="muted w-16">Kind</span>
              <select className="input" value={p.volt} onChange={(e) => setP({ ...p, volt: e.target.value })} aria-label="voltage anomaly type">
                <option>sag</option>
                <option>imbalance</option>
                <option>harmonic</option>
              </select>
            </label>
          )}
          <button className="btn btn-primary justify-self-start" onClick={inject} disabled={busy}>Inject fault</button>
        </div>
      ) : (
        <p className="text-sm muted mt-2">Operator role required to inject faults.</p>
      )}
      <h3 className="text-xs muted mt-3 mb-1">Active faults (ground truth)</h3>
      {faults.length === 0 ? (
        <p className="text-sm muted">None</p>
      ) : (
        <ul className="text-sm grid gap-1">
          {faults.map((f) => (
            <li key={f.id} className="flex items-center justify-between gap-2">
              <span className="capitalize">
                {label(f.fault_type)} <span className="muted tabular">sev {f.severity.toFixed(2)}
                  {Object.keys(f.params).length ? ` ${JSON.stringify(f.params)}` : ''}</span>
              </span>
              {canOperate && <button className="btn" onClick={() => clear(f.id)} aria-label={`clear fault ${f.id}`}>Clear</button>}
            </li>
          ))}
        </ul>
      )}
      {msg && <p className="text-xs muted mt-2" role="status">{msg}</p>}
    </section>
  )
}

import { useState } from 'react'
import { Zap } from 'lucide-react'
import { api, newIdempotencyKey, resetTrip } from '../api/client'
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

// Default severity: 0.3 lands in WATCH for every fault type. Diagnosed severity tracks injected
// severity, and SADA thresholds are WATCH 0.3 / DERATE 0.5 / TRIP 0.8, so the old 0.5 default
// put the motor straight into DERATE.
export const DEFAULT_FAULT_SEVERITY = 0.3

export function FaultConsole({
  motorId,
  faults,
  canOperate,
  tripped = false,
  tripReason,
}: {
  motorId: number
  faults: ActiveFault[]
  canOperate: boolean
  tripped?: boolean
  tripReason?: string | null
}) {
  const [ft, setFt] = useState<FaultType>('bearing_outer')
  const [severity, setSeverity] = useState(DEFAULT_FAULT_SEVERITY)
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
      if (tripped) setMsg('Fault cleared. The motor stays tripped (latched) until you reset the trip.')
    } catch (e) {
      setMsg((e as Error).message)
    }
  }

  const reset = async () => {
    setBusy(true)
    setMsg(null)
    try {
      await resetTrip(motorId)
      setMsg('Trip reset: motor restarting')
    } catch (e) {
      setMsg(`Reset refused: ${(e as Error).message}`)
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="card flex flex-col justify-between" aria-labelledby="fault-h">
      <div>
        <header className="flex items-center justify-between pb-3 border-b border-[var(--border)]">
          <div className="flex items-center gap-2">
            <span className="w-7 h-7 rounded-md bg-[var(--surface-raised)] border border-[var(--border)] flex items-center justify-center text-rose-400">
              <Zap size={14} />
            </span>
            <div>
              <span className="eyebrow block" style={{ fontSize: 9 }}>SIMULATION BENCH</span>
              <h2 id="fault-h" className="text-xs font-semibold uppercase tracking-wider text-[var(--ink)]">
                Fault Injection Bench
              </h2>
            </div>
          </div>
          <span className="text-[11px] num px-2 py-0.5 rounded bg-[var(--surface-raised)] border border-[var(--border)] text-[var(--muted)]">
            {faults.length} Active
          </span>
        </header>

        {tripped && (
          <div
            className="mt-3 p-2.5 rounded-md border border-rose-500/30 bg-rose-500/10 text-xs text-rose-200 grid gap-2"
            role="alert"
            data-testid="fault-console-trip"
          >
            <span>
              <strong>Motor tripped{tripReason ? ` (${tripReason})` : ''}.</strong> It stays stopped until the trip is
              reset — clearing faults does not restart it, and faults injected now cannot be diagnosed while the motor
              is de-energised.
            </span>
            {canOperate && (
              <button className="btn justify-self-start text-[11px] py-0.5 px-2" onClick={reset} disabled={busy}>
                Reset trip
              </button>
            )}
          </div>
        )}

        {canOperate ? (
          <div className="mt-3 grid gap-2.5 text-xs">
            <label className="flex items-center gap-2">
              <span className="text-[var(--muted)] font-medium w-16">Type</span>
              <select
                className="input flex-1 bg-[var(--surface-raised)]"
                value={ft}
                onChange={(e) => setFt(e.target.value as FaultType)}
                aria-label="fault type"
              >
                {FAULT_TYPES.map((f) => (
                  <option key={f} value={f}>
                    {label(f)}
                  </option>
                ))}
              </select>
            </label>

            {ft === 'broken_rotor_bar' ? (
              <label className="flex items-center gap-2">
                <span className="text-[var(--muted)] font-medium w-16">Bars</span>
                <input
                  className="input w-24 num bg-[var(--surface-raised)]"
                  type="number"
                  min={1}
                  max={8}
                  value={p.count}
                  aria-label="broken bars"
                  onChange={(e) => setP({ ...p, count: Math.max(1, Math.min(8, Number(e.target.value))) })}
                />
                <span className="text-[var(--muted)] text-[11px] num">(1–8 bars)</span>
              </label>
            ) : (
              <label className="flex items-center gap-2">
                <span className="text-[var(--muted)] font-medium w-16">Severity</span>
                <input
                  className="flex-1 cursor-pointer"
                  type="range"
                  min={0.05}
                  max={1}
                  step={0.05}
                  value={severity}
                  aria-label="fault severity"
                  onChange={(e) => setSeverity(Number(e.target.value))}
                />
                <span className="tabular num text-xs w-10 text-right text-[var(--ink)]">
                  {severity.toFixed(2)}
                </span>
              </label>
            )}

            {ft === 'interturn_short' && (
              <label className="flex items-center gap-2">
                <span className="text-[var(--muted)] font-medium w-16">Phase</span>
                <select
                  className="input w-24 bg-[var(--surface-raised)]"
                  value={p.phase}
                  onChange={(e) => setP({ ...p, phase: e.target.value })}
                  aria-label="phase"
                >
                  {['a', 'b', 'c'].map((x) => (
                    <option key={x} value={x}>Phase {x.toUpperCase()}</option>
                  ))}
                </select>
              </label>
            )}

            {ft === 'eccentricity' && (
              <label className="flex items-center gap-2">
                <span className="text-[var(--muted)] font-medium w-16">Kind</span>
                <select
                  className="input flex-1 bg-[var(--surface-raised)]"
                  value={p.ecc}
                  onChange={(e) => setP({ ...p, ecc: e.target.value })}
                  aria-label="eccentricity type"
                >
                  <option value="dynamic">Dynamic Eccentricity</option>
                  <option value="static">Static Eccentricity</option>
                </select>
              </label>
            )}

            {ft === 'voltage_anomaly' && (
              <>
                <label className="flex items-center gap-2">
                  <span className="text-[var(--muted)] font-medium w-16">Kind</span>
                  <select
                    className="input flex-1 bg-[var(--surface-raised)]"
                    value={p.volt}
                    onChange={(e) => setP({ ...p, volt: e.target.value })}
                    aria-label="voltage anomaly type"
                  >
                    <option value="sag">Voltage Sag</option>
                    <option value="imbalance">Phase Imbalance</option>
                    <option value="harmonic">Harmonic Distortion</option>
                  </select>
                </label>
                {p.volt === 'harmonic' && (
                  <p className="text-[11px] text-[var(--muted)] bg-[var(--surface-raised)] p-2 rounded border border-[var(--border)] leading-relaxed">
                    Harmonic note: Severity 0.5 injects ~6% THD. Per EN 50160, THD &le; 8% is nominal and not flagged by design. Severity &ge; 0.70 is required to trigger a supply anomaly.
                  </p>
                )}
              </>
            )}

            <button
              className="btn btn-primary justify-self-start mt-1 px-4 py-1.5 text-xs font-medium"
              onClick={inject}
              disabled={busy}
            >
              Inject fault
            </button>
          </div>
        ) : (
          <div className="mt-3 p-3 rounded-md bg-[var(--surface-raised)] border border-[var(--border)] text-xs text-[var(--muted)]">
            Operator role required to inject faults into simulation.
          </div>
        )}

        {/* Active Ground-Truth Faults */}
        <div className="mt-4 pt-3 border-t border-[var(--border)]">
          <h3 className="text-xs font-semibold uppercase tracking-wider text-[var(--muted)] mb-2">
            Active faults (ground truth)
          </h3>
          {faults.length === 0 ? (
            <div className="p-3 rounded-md bg-[var(--surface-raised)] border border-dashed border-[var(--border)] text-center text-xs text-[var(--muted)]">
              No faults active — motor running nominal
            </div>
          ) : (
            <ul className="text-xs grid gap-1.5">
              {faults.map((f) => (
                <li
                  key={f.id}
                  className="flex items-center justify-between gap-2 p-2 rounded-md bg-[var(--surface-raised)] border border-rose-500/20"
                >
                  <div className="flex flex-col min-w-0">
                    <span className="capitalize font-medium text-rose-400 truncate">
                      {label(f.fault_type)}
                    </span>
                    <span className="text-[11px] text-[var(--muted)] tabular num">
                      sev {f.severity.toFixed(2)}
                      {Object.keys(f.params).length ? ` · ${JSON.stringify(f.params)}` : ''}
                    </span>
                  </div>
                  {canOperate && (
                    <button
                      className="btn text-[11px] py-0.5 px-2 bg-rose-500/10 hover:bg-rose-500/20 text-rose-300 border-rose-500/20"
                      onClick={() => clear(f.id)}
                      aria-label={`clear fault ${f.id}`}
                    >
                      Clear
                    </button>
                  )}
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>

      {msg && (
        <p className="text-xs text-rose-300 mt-3 p-2 rounded bg-rose-500/10 border border-rose-500/20" role="status">
          {msg}
        </p>
      )}
    </section>
  )
}

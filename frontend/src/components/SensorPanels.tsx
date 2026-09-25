import type { ReactNode } from 'react'
import { api } from '../api/client'
import type { Frame, SensorEntry, SensorRow } from '../api/types'
import { SpectrumChart } from './charts/SpectrumChart'
import { Scalogram } from './charts/Scalogram'
import { TrendChart } from './charts/TrendChart'
import { WaveChart, type Series } from './charts/WaveChart'

const PHASE_COLORS = ['var(--series-1)', 'var(--series-2)', 'var(--series-3)']

function three(entry: SensorEntry | undefined, keys: string[], names: string[]): Series[] {
  return keys.map((k, i) => ({ key: k, label: names[i], color: PHASE_COLORS[i], data: entry?.wave?.[k] ?? [] }))
}

function SensorCard({
  title, entry, row, canAdmin, onModeChanged, children, extra,
}: {
  title: string; entry?: SensorEntry; row?: SensorRow; canAdmin: boolean; onModeChanged: () => void
  children: ReactNode; extra?: ReactNode
}) {
  const stale = entry && entry.status !== 'ok'
  const toggle = async () => {
    if (!row) return
    await api(`/motors/${row.motor_id}/sensors/${row.id}`, {
      method: 'PATCH',
      body: JSON.stringify({ mode: row.mode === 'simulated' ? 'hardware' : 'simulated' }),
    })
    onModeChanged()
  }
  return (
    <section className="card min-w-0" aria-label={`${title} sensor`}>
      <header className="flex items-center justify-between gap-2">
        <h3 className="text-sm font-semibold whitespace-nowrap">{title}</h3>
        <div className="flex items-center gap-2 text-xs">
          <span className="muted">{entry?.mode ?? row?.mode}</span>
          {stale && <span style={{ color: 'var(--critical)' }}>● {entry?.status}</span>}
          {canAdmin && row && (
            <button className="btn" onClick={toggle} title="Switch between simulated and hardware implementation">
              {row.mode === 'simulated' ? '→ hardware' : '→ simulated'}
            </button>
          )}
        </div>
      </header>
      <div className="text-xs tabular muted mb-1 min-h-4">{extra}</div>
      {stale ? <p className="text-sm muted py-8 text-center">No data (sensor {entry?.status}; hardware driver not connected)</p> : children}
    </section>
  )
}

const fmt = (r?: Record<string, number>, unit = '') =>
  r ? Object.entries(r).map(([k, v]) => `${k} ${v.toFixed(2)}${unit}`).join(' · ') : ''

export function SensorPanels({
  frame, sensors, trend, canAdmin, onModeChanged,
}: {
  frame: Frame; sensors: SensorRow[]; canAdmin: boolean; onModeChanged: () => void
  trend: { t: number; rpm: number; temp: number }[]
}) {
  const row = (t: string) => sensors.find((s) => s.type === t)
  const s = frame.sensors
  const rpm = frame.mechanics.rpm
  const slip = Math.max(0, (50 - (2 * rpm) / 60) / 50)
  const sb = 2 * slip * 50
  const currentMarkers = [{ f: 50, label: 'f' }, ...(sb > 0.5 ? [{ f: 50 - sb }, { f: 50 + sb }] : [])]
  const common = { canAdmin, onModeChanged }

  return (
    <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
      <SensorCard title="Current (3-phase)" entry={s.current} row={row('current')} {...common}
        extra={<span>RMS {fmt(s.current?.rms, ' A')}</span>}>
        <WaveChart series={three(s.current, ['a', 'b', 'c'], ['Phase a', 'Phase b', 'Phase c'])} dtMs={1} unit="A" />
        <p className="text-xs muted mt-1">Phase-a spectrum (2 s window) ; dashed lines: f and (1±2s)f rotor-bar sidebands</p>
        <SpectrumChart spectrum={frame.spectra.current_a} markers={currentMarkers} label="Current a" />
      </SensorCard>

      <SensorCard title="Voltage (3-phase)" entry={s.voltage} row={row('voltage')} {...common}
        extra={<span>RMS {fmt(s.voltage?.rms, ' V')}</span>}>
        <WaveChart series={three(s.voltage, ['a', 'b', 'c'], ['Phase a', 'Phase b', 'Phase c'])} dtMs={1} unit="V" />
        <SupplyStats frame={frame} />
      </SensorCard>

      <SensorCard title="Vibration (tri-axial)" entry={s.vibration} row={row('vibration')} {...common}
        extra={<span>RMS {fmt(s.vibration?.rms)} m/s²</span>}>
        <WaveChart series={three(s.vibration, ['x', 'y', 'z'], ['x (radial)', 'y (radial, load zone)', 'z (axial)'])}
          dtMs={(1000 / 12800) * 5} unit="m/s²" />
        <p className="text-xs muted mt-1">y-axis spectrum (Welch, 0.5 s)</p>
        <SpectrumChart spectrum={frame.spectra.vibration_y} label="Vibration y" height={110} />
        <p className="text-xs muted mt-1">y-axis scalogram (CWT, Morlet)</p>
        <Scalogram data={frame.scalogram} height={110} />
      </SensorCard>

      <SensorCard title="Acoustic" entry={s.acoustic} row={row('acoustic')} {...common}
        extra={<span>RMS {s.acoustic?.rms?.p?.toFixed(4)} Pa</span>}>
        <WaveChart series={[{ key: 'p', label: 'Sound pressure', color: 'var(--series-1)', data: s.acoustic?.wave?.p ?? [] }]}
          dtMs={(1000 / 12800) * 5} unit="Pa" />
        <SpectrumChart spectrum={frame.spectra.acoustic} label="Acoustic" />
      </SensorCard>

      <SensorCard title="Winding temperature" entry={s.temp} row={row('temp')} {...common}
        extra={<span>{s.temp?.value?.toFixed(1)} °C</span>}>
        <TrendChart data={trend} dataKey="temp" unit="°C" label="Temperature" height={150} />
      </SensorCard>

      <SensorCard title="Shaft speed (encoder)" entry={s.speed} row={row('speed')} {...common}
        extra={<span>{s.speed?.value?.toFixed(0)} rpm · slip {(slip * 100).toFixed(1)}%</span>}>
        <TrendChart data={trend} dataKey="rpm" unit="rpm" label="Speed" height={150} />
        <p className="text-xs muted tabular mt-1">
          Torque {frame.mechanics.torque_nm.toFixed(2)} N·m · load {frame.mechanics.load_nm.toFixed(2)} N·m
        </p>
      </SensorCard>
    </div>
  )
}

function SupplyStats({ frame }: { frame: Frame }) {
  const d = frame.diagnosis.per_sensor_scores.supply?.details as { vuf?: number; thd?: number; v_pos_pu?: number } | undefined
  if (!d?.vuf && d?.vuf !== 0) return <p className="text-xs muted mt-2">Supply analysis unavailable</p>
  return (
    <dl className="grid grid-cols-3 gap-2 mt-2 text-center tabular">
      <div><dt className="text-xs muted">Unbalance (VUF)</dt><dd className="text-lg">{(d.vuf! * 100).toFixed(2)}%</dd></div>
      <div><dt className="text-xs muted">THD</dt><dd className="text-lg">{((d.thd ?? 0) * 100).toFixed(2)}%</dd></div>
      <div><dt className="text-xs muted">V+ (pu)</dt><dd className="text-lg">{(d.v_pos_pu ?? 0).toFixed(3)}</dd></div>
    </dl>
  )
}

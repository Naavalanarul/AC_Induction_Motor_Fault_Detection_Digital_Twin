import type { ReactNode } from 'react'
import { Activity, Mic, RotateCw, Thermometer, Waves, Zap } from 'lucide-react'
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
  title, icon, entry, row, canAdmin, onModeChanged, children, extra,
}: {
  title: string; icon: ReactNode; entry?: SensorEntry; row?: SensorRow; canAdmin: boolean; onModeChanged: () => void
  children: ReactNode; extra?: ReactNode
}) {
  const stale = entry && entry.status !== 'ok'
  const isHardware = (entry?.mode ?? row?.mode) === 'hardware'

  const toggle = async () => {
    if (!row) return
    const nextMode = row.mode === 'simulated' ? 'hardware' : 'simulated'
    if (nextMode === 'hardware') {
      const ok = window.confirm(
        `Switch ${title} channel to HARDWARE mode?\n\nWarning: If physical hardware drivers are unconfigured or disconnected, this channel will report STALE data and may trigger protective watchdog derate or trip.`
      )
      if (!ok) return
    }
    await api(`/motors/${row.motor_id}/sensors/${row.id}`, {
      method: 'PATCH',
      body: JSON.stringify({ mode: nextMode, confirm_hardware: true }),
    })
    onModeChanged()
  }

  return (
    <section className="card min-w-0 flex flex-col justify-between" aria-label={`${title} sensor`}>
      <div>
        <header className="flex items-center justify-between gap-2 pb-2.5 border-b border-[var(--border)]">
          <div className="flex items-center gap-2.5 min-w-0">
            <span className="sensor-icon">
              {icon}
            </span>
            <div className="flex items-center gap-1.5 min-w-0">
              <span
                className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${
                  stale ? 'bg-rose-500' : 'bg-emerald-400'
                }`}
              />
              <h3 className="text-xs font-semibold uppercase tracking-wider text-[var(--ink)] truncate">{title}</h3>
            </div>
          </div>
          <div className="flex items-center gap-2 text-xs">
            {stale && <span className="text-rose-400 num text-[11px]">● {entry?.status}</span>}
            <div className="sensor-source-toggle" aria-label={`${title} data source`}>
              <button
                type="button"
                className={`sensor-source-button ${!isHardware ? 'is-active' : ''}`}
                onClick={canAdmin && isHardware ? toggle : undefined}
                disabled={!canAdmin || !isHardware}
                title={canAdmin ? 'Switch to simulated mode' : 'Simulated mode'}
              >
                Simulated
              </button>
              <button
                type="button"
                className={`sensor-source-button ${isHardware ? 'is-active' : ''}`}
                onClick={canAdmin && !isHardware ? toggle : undefined}
                disabled={!canAdmin || isHardware}
                title={canAdmin ? 'Switch to hardware mode' : 'Hardware mode'}
              >
                Hardware
              </button>
            </div>
          </div>
        </header>

        <div className="text-xs tabular num text-[var(--ink-2)] my-2 font-medium min-h-4">{extra}</div>

        {stale ? (
          <div className="p-8 text-center rounded-md bg-[var(--surface-raised)] border border-dashed border-[var(--border)] my-2">
            <p className="text-xs text-rose-400 font-medium">No data (sensor {entry?.status}; hardware driver not connected)</p>
            <p className="text-[11px] text-[var(--muted)] mt-1">Circuit breaker active: reading degraded to stale</p>
          </div>
        ) : (
          children
        )}
      </div>
    </section>
  )
}

const fmt = (r?: Record<string, number>, unit = '') =>
  r ? Object.entries(r).map(([k, v]) => `${k.toUpperCase()} ${v.toFixed(2)}${unit}`).join(' · ') : ''

export function SensorPanels({
  frame, sensors, trend, canAdmin, onModeChanged,
}: {
  frame: Frame; sensors: SensorRow[]; canAdmin: boolean; onModeChanged: () => void
  trend: { t: number; rpm: number; temp: number }[]
}) {
  const row = (t: string) => sensors.find((s) => s.type === t)
  const s = frame.sensors
  const rpm = frame.mechanics.rpm
  const slip = Math.max(0.001, (50 - (2 * rpm) / 60) / 50)
  const sb = 2 * slip * 50
  const fr = rpm / 60.0
  const mcsaData = frame.spectra?.mcsa as {
    peaks?: { freq_hz: number; magnitude_db: number; label: string; harmonic_k?: number }[]
    brb_fault_detected?: boolean
    worst_brb_sideband_db?: number
    eccentricity_detected?: boolean
  } | undefined

  // Automated MCSA peak markers overlay: f_BRB = f_s * (1 +/- 2ks) for k in {1,2,3} and f_ecc = f_s +/- f_r
  const currentMarkers = [
    { f: 50, label: 'fs' },
    ...(sb > 0.4
      ? [
          { f: Math.round((50 - sb) * 10) / 10, label: '-2sf' },
          { f: Math.round((50 + sb) * 10) / 10, label: '+2sf' },
          { f: Math.round((50 - 2 * sb) * 10) / 10, label: '-4sf' },
          { f: Math.round((50 + 2 * sb) * 10) / 10, label: '+4sf' },
        ]
      : []),
    ...(fr > 10.0
      ? [
          { f: Math.round((50 - fr) * 10) / 10, label: 'fs-fr' },
          { f: Math.round((50 + fr) * 10) / 10, label: 'fs+fr' },
        ]
      : []),
  ]
  const common = { canAdmin, onModeChanged }

  return (
    <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
      <SensorCard
        title="Current (3-phase)"
        icon={<Activity size={15} />}
        entry={s.current}
        row={row('current')}
        {...common}
        extra={<span>RMS {fmt(s.current?.rms, ' A')}</span>}
      >
        <WaveChart series={three(s.current, ['a', 'b', 'c'], ['Phase a', 'Phase b', 'Phase c'])} dtMs={1} unit="A" />
        <div className="flex items-center justify-between text-[11px] text-[var(--muted)] mt-2 num">
          <span>MCSA Spectrum (Hann, 5 kHz) · f_BRB=(1±2ks)fs markers</span>
          {mcsaData?.brb_fault_detected && (
            <span className="text-rose-400 font-bold bg-rose-500/10 px-1.5 py-0.5 rounded border border-rose-500/30 text-[10px]">
              BRB Sideband {mcsaData.worst_brb_sideband_db?.toFixed(1)} dBc
            </span>
          )}
        </div>
        <SpectrumChart spectrum={frame.spectra.current_a} markers={currentMarkers} label="Current a" />
      </SensorCard>

      <SensorCard
        title="Voltage (3-phase)"
        icon={<Zap size={15} />}
        entry={s.voltage}
        row={row('voltage')}
        {...common}
        extra={<span>RMS {fmt(s.voltage?.rms, ' V')}</span>}
      >
        <WaveChart series={three(s.voltage, ['a', 'b', 'c'], ['Phase a', 'Phase b', 'Phase c'])} dtMs={1} unit="V" />
        <SupplyStats frame={frame} />
      </SensorCard>

      <SensorCard
        title="Vibration (tri-axial)"
        icon={<Waves size={15} />}
        entry={s.vibration}
        row={row('vibration')}
        {...common}
        extra={<span>RMS {fmt(s.vibration?.rms)} m/s²</span>}
      >
        <WaveChart
          series={three(s.vibration, ['x', 'y', 'z'], ['x (radial)', 'y (radial, load zone)', 'z (axial)'])}
          dtMs={(1000 / 12800) * 5}
          unit="m/s²"
        />
        <p className="text-[11px] text-[var(--muted)] mt-2 num">y-axis spectrum (Welch, 0.5 s)</p>
        <SpectrumChart spectrum={frame.spectra.vibration_y} label="Vibration y" height={110} />
        <p className="text-[11px] text-[var(--muted)] mt-2 num">y-axis scalogram (CWT, Morlet)</p>
        <Scalogram data={frame.scalogram} height={110} />
      </SensorCard>

      <SensorCard
        title="Acoustic"
        icon={<Mic size={15} />}
        entry={s.acoustic}
        row={row('acoustic')}
        {...common}
        extra={<span>RMS {s.acoustic?.rms?.p?.toFixed(4)} Pa</span>}
      >
        <WaveChart
          series={[{ key: 'p', label: 'Sound pressure', color: 'var(--series-1)', data: s.acoustic?.wave?.p ?? [] }]}
          dtMs={(1000 / 12800) * 5}
          unit="Pa"
        />
        <SpectrumChart spectrum={frame.spectra.acoustic} label="Acoustic" />
      </SensorCard>

      <SensorCard
        title="Winding temperature"
        icon={<Thermometer size={15} />}
        entry={s.temp}
        row={row('temp')}
        {...common}
        extra={<span>{s.temp?.value?.toFixed(1)} °C</span>}
      >
        <TrendChart data={trend} dataKey="temp" unit="°C" label="Temperature" height={150} color="var(--series-2)" />
      </SensorCard>

      <SensorCard
        title="Shaft speed (encoder)"
        icon={<RotateCw size={15} />}
        entry={s.speed}
        row={row('speed')}
        {...common}
        extra={<span>{s.speed?.value?.toFixed(0)} rpm · slip {(slip * 100).toFixed(1)}%</span>}
      >
        <TrendChart data={trend} dataKey="rpm" unit="rpm" label="Speed" height={150} color="var(--series-3)" />
        <p className="text-[11px] text-[var(--muted)] num mt-2">
          Torque {frame.mechanics.torque_nm.toFixed(2)} N·m · load {frame.mechanics.load_nm.toFixed(2)} N·m
        </p>
      </SensorCard>
    </div>
  )
}

function SupplyStats({ frame }: { frame: Frame }) {
  const d = frame.diagnosis.per_sensor_scores.supply?.details as { vuf?: number; thd?: number; v_pos_pu?: number } | undefined
  if (!d?.vuf && d?.vuf !== 0) return <p className="text-xs text-[var(--muted)] mt-2 italic">Supply analysis unavailable</p>
  return (
    <dl className="grid grid-cols-3 gap-2 mt-3 p-2 rounded-md bg-[var(--surface-raised)] border border-[var(--border)] text-center tabular">
      <div>
        <dt className="text-[10px] text-[var(--muted)] uppercase font-medium">Unbalance (VUF)</dt>
        <dd className="text-base num font-bold text-[var(--ink)] mt-0.5">{(d.vuf! * 100).toFixed(2)}%</dd>
      </div>
      <div>
        <dt className="text-[10px] text-[var(--muted)] uppercase font-medium">THD</dt>
        <dd className="text-base num font-bold text-[var(--ink)] mt-0.5">{((d.thd ?? 0) * 100).toFixed(2)}%</dd>
      </div>
      <div>
        <dt className="text-[10px] text-[var(--muted)] uppercase font-medium">V+ (pu)</dt>
        <dd className="text-base num font-bold text-[var(--ink)] mt-0.5">{(d.v_pos_pu ?? 0).toFixed(3)}</dd>
      </div>
    </dl>
  )
}

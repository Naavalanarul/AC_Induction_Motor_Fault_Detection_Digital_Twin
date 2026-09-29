import { useQuery } from '@tanstack/react-query'
import React from 'react'
import { api } from '../api/client'
import type { DiagnosisRow, Frame, Motor, Page, Prognosis, Recommendation } from '../api/types'
import { HealthGauge } from './HealthGauge'

export interface HealthMaintenanceTabProps {
  motor: Motor
  frame?: Frame | null
}

const formatSeconds = (sec: number | null | undefined): string => {
  if (sec === null || sec === undefined) return 'Indefinite'
  if (sec <= 0) return 'Exceeded'
  if (sec < 60) return `${sec.toFixed(0)} s`
  const mins = Math.floor(sec / 60)
  const remSec = Math.round(sec % 60)
  return `${mins}m ${remSec}s`
}

export const HealthMaintenanceTab: React.FC<HealthMaintenanceTabProps> = ({ motor, frame }) => {
  const mhi = frame?.health_index ?? frame?.diagnosis?.health_index ?? 100
  const zone = frame?.zone ?? frame?.diagnosis?.zone ?? 'A'
  const errorCode = frame?.error_code ?? frame?.diagnosis?.error_code ?? 'SYS-OK-A'

  const progQuery = useQuery({
    queryKey: ['prognosis', motor.id],
    queryFn: () => api<Prognosis>(`/motors/${motor.id}/prognosis`),
    refetchInterval: 5000,
  })

  const recQuery = useQuery({
    queryKey: ['recommendation', motor.id],
    queryFn: () => api<Recommendation>(`/motors/${motor.id}/recommendation`),
    refetchInterval: 5000,
  })

  const histQuery = useQuery({
    queryKey: ['diagnoses', motor.id],
    queryFn: () => api<Page<DiagnosisRow>>(`/motors/${motor.id}/diagnoses?limit=10`),
    refetchInterval: 5000,
  })

  const prognosis = progQuery.data ?? null
  const recommendation = recQuery.data ?? null
  const history = histQuery.data?.items ?? []
  const loading = progQuery.isLoading || recQuery.isLoading
  const error = progQuery.error?.message || recQuery.error?.message || histQuery.error?.message || null

  const handleRefresh = () => {
    progQuery.refetch()
    recQuery.refetch()
    histQuery.refetch()
  }

  const urgencyStyles: Record<string, string> = {
    routine: 'bg-emerald-500/10 text-emerald-400 border-emerald-500/30',
    planned: 'bg-amber-500/10 text-amber-400 border-amber-500/30',
    prompt: 'bg-orange-500/10 text-orange-400 border-orange-500/30',
    immediate: 'bg-rose-500/10 text-rose-400 border-rose-500/30 animate-pulse',
  }

  return (
    <div className="space-y-6">
      {/* Top Banner / Error */}
      {error && (
        <div className="rounded-lg border border-rose-500/30 bg-rose-950/40 p-3 text-xs text-rose-300">
          Telemetry Error: {error}
        </div>
      )}

      {/* Main Grid: MHI Overview & Prognosis Projection */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        {/* Card 1: Motor Health Index Gauge */}
        <div className="flex flex-col items-center justify-between rounded-xl border border-neutral-800 bg-neutral-900/60 p-6 text-center shadow-sm">
          <div className="w-full text-left">
            <span className="text-xs font-mono uppercase tracking-wider text-neutral-400">
              Condition Monitoring
            </span>
            <h3 className="text-base font-semibold text-neutral-100">Motor Health Index</h3>
          </div>

          <div className="my-4">
            <HealthGauge value={mhi} zone={zone} size="lg" />
          </div>

          <div className="w-full grid grid-cols-2 gap-2 border-t border-neutral-800 pt-3 text-xs">
            <div>
              <span className="text-neutral-500 block text-[11px]">Error Code</span>
              <span className="font-mono font-semibold text-neutral-200">{errorCode}</span>
            </div>
            <div>
              <span className="text-neutral-500 block text-[11px]">SADA State</span>
              <span className="font-mono font-semibold text-neutral-200">
                {frame?.supervisory?.state ?? 'NORMAL'}
              </span>
            </div>
          </div>
        </div>

        {/* Card 2: Prognosis & Threshold Projections */}
        <div className="flex flex-col justify-between rounded-xl border border-neutral-800 bg-neutral-900/60 p-6 shadow-sm lg:col-span-2">
          <div>
            <div className="flex items-center justify-between">
              <div>
                <span className="text-xs font-mono uppercase tracking-wider text-neutral-400">
                  Remaining Useful Life (RUL)
                </span>
                <h3 className="text-base font-semibold text-neutral-100">
                  Prognosis & Threshold Estimation
                </h3>
              </div>
              {prognosis && (
                <span
                  className={`rounded-full px-2.5 py-0.5 text-xs font-medium uppercase tracking-wide border ${
                    prognosis.trend === 'increasing'
                      ? 'bg-rose-500/10 text-rose-400 border-rose-500/30'
                      : prognosis.trend === 'decreasing'
                      ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/30'
                      : 'bg-neutral-800 text-neutral-300 border-neutral-700'
                  }`}
                >
                  Trend: {prognosis.trend}
                </span>
              )}
            </div>

            <p className="mt-2 text-xs text-neutral-400">
              Ordinary Least Squares polynomial projection calculated from a rolling 120-sample
              severity history at chunk boundaries.
            </p>

            <div className="mt-6 grid grid-cols-1 sm:grid-cols-3 gap-4">
              <div className="rounded-lg border border-neutral-800 bg-neutral-950/60 p-4">
                <span className="text-xs text-neutral-400 block">Current Severity</span>
                <span className="mt-1 font-mono text-2xl font-bold text-neutral-100">
                  {(prognosis?.current_severity ?? frame?.diagnosis?.severity ?? 0).toFixed(3)}
                </span>
                <span className="text-[11px] text-neutral-500 block mt-1">
                  Slope: {(prognosis?.slope_per_s ?? 0).toFixed(5)}/s
                </span>
              </div>

              <div className="rounded-lg border border-neutral-800 bg-neutral-950/60 p-4">
                <span className="text-xs text-neutral-400 block">Time to DERATE (0.5)</span>
                <span className="mt-1 font-mono text-2xl font-bold text-amber-400">
                  {formatSeconds(prognosis?.time_to_derate_s)}
                </span>
                <span className="text-[11px] text-neutral-500 block mt-1">
                  Linear projection
                </span>
              </div>

              <div className="rounded-lg border border-neutral-800 bg-neutral-950/60 p-4">
                <span className="text-xs text-neutral-400 block">Time to TRIP (0.8)</span>
                <span className="mt-1 font-mono text-2xl font-bold text-rose-400">
                  {formatSeconds(prognosis?.time_to_trip_s)}
                </span>
                <span className="text-[11px] text-neutral-500 block mt-1">
                  Emergency limit
                </span>
              </div>
            </div>
          </div>

          <div className="mt-4 flex items-center justify-between text-xs text-neutral-500 border-t border-neutral-800 pt-3">
            <span>Samples Analyzed: {prognosis?.sample_count ?? 0}</span>
            <button
              onClick={handleRefresh}
              disabled={loading}
              className="text-xs text-cyan-400 hover:text-cyan-300 font-medium"
            >
              Refresh Telemetry
            </button>
          </div>
        </div>
      </div>

      {/* 4-Node Lumped Parameter Thermal Network (LPTN) & Arrhenius Insulation Life Model */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        {/* 4-Node LPTN Card */}
        <div className="rounded-xl border border-neutral-800 bg-neutral-900/60 p-6 shadow-sm">
          <div className="flex items-center justify-between border-b border-neutral-800 pb-3">
            <div>
              <span className="text-xs font-mono uppercase tracking-wider text-neutral-400">
                Lumped Parameter Thermal Network (LPTN)
              </span>
              <h3 className="text-base font-semibold text-neutral-100">
                4-Node Coupled Thermal Model
              </h3>
            </div>
            <span className="rounded-md border border-neutral-700 bg-neutral-800/80 px-2 py-0.5 font-mono text-[11px] text-neutral-300">
              Class F (155°C Limit)
            </span>
          </div>

          <p className="mt-2 text-xs text-neutral-400">
            Heat dissipation across coupled nodes: Winding (Tw), Stator Teeth (Tt), Rotor Cage (Tr), and Bearing Housing (Tb).
          </p>

          <div className="mt-5 space-y-4">
            {/* Winding Node */}
            <div>
              <div className="flex justify-between text-xs font-mono mb-1">
                <span className="text-neutral-300 font-semibold">Stator Winding (Tw)</span>
                <span className={`font-bold ${
                  (frame?.thermal_lptn?.t_winding ?? frame?.sensors?.temp?.value ?? 45) > 130
                    ? 'text-rose-400'
                    : (frame?.thermal_lptn?.t_winding ?? frame?.sensors?.temp?.value ?? 45) > 105
                    ? 'text-amber-400'
                    : 'text-emerald-400'
                }`}>
                  {(frame?.thermal_lptn?.t_winding ?? frame?.sensors?.temp?.value ?? 45.0).toFixed(1)} °C
                </span>
              </div>
              <div className="h-2 w-full rounded-full bg-neutral-800 overflow-hidden">
                <div
                  className="h-full rounded-full transition-all duration-500"
                  style={{
                    width: `${Math.min(100, Math.max(5, ((frame?.thermal_lptn?.t_winding ?? frame?.sensors?.temp?.value ?? 45) / 155) * 100))}%`,
                    backgroundColor:
                      (frame?.thermal_lptn?.t_winding ?? frame?.sensors?.temp?.value ?? 45) > 130
                        ? 'var(--critical)'
                        : (frame?.thermal_lptn?.t_winding ?? frame?.sensors?.temp?.value ?? 45) > 105
                        ? 'var(--warning)'
                        : 'var(--good)',
                  }}
                />
              </div>
            </div>

            {/* Stator Teeth Node */}
            <div>
              <div className="flex justify-between text-xs font-mono mb-1">
                <span className="text-neutral-300">Stator Teeth Core (Tt)</span>
                <span className="text-neutral-200">
                  {(frame?.thermal_lptn?.t_teeth ?? 42.0).toFixed(1)} °C
                </span>
              </div>
              <div className="h-2 w-full rounded-full bg-neutral-800 overflow-hidden">
                <div
                  className="h-full rounded-full bg-cyan-500/80 transition-all duration-500"
                  style={{
                    width: `${Math.min(100, Math.max(5, ((frame?.thermal_lptn?.t_teeth ?? 42.0) / 155) * 100))}%`,
                  }}
                />
              </div>
            </div>

            {/* Rotor Cage Node */}
            <div>
              <div className="flex justify-between text-xs font-mono mb-1">
                <span className="text-neutral-300">Rotor Cage (Tr)</span>
                <span className="text-neutral-200">
                  {(frame?.thermal_lptn?.t_rotor ?? 48.0).toFixed(1)} °C
                </span>
              </div>
              <div className="h-2 w-full rounded-full bg-neutral-800 overflow-hidden">
                <div
                  className="h-full rounded-full bg-amber-500/80 transition-all duration-500"
                  style={{
                    width: `${Math.min(100, Math.max(5, ((frame?.thermal_lptn?.t_rotor ?? 48.0) / 155) * 100))}%`,
                  }}
                />
              </div>
            </div>

            {/* Bearing Node */}
            <div>
              <div className="flex justify-between text-xs font-mono mb-1">
                <span className="text-neutral-300">Bearings (Tb)</span>
                <span className="text-neutral-200">
                  {(frame?.thermal_lptn?.t_bearing ?? 38.0).toFixed(1)} °C
                </span>
              </div>
              <div className="h-2 w-full rounded-full bg-neutral-800 overflow-hidden">
                <div
                  className="h-full rounded-full bg-teal-500/80 transition-all duration-500"
                  style={{
                    width: `${Math.min(100, Math.max(5, ((frame?.thermal_lptn?.t_bearing ?? 38.0) / 155) * 100))}%`,
                  }}
                />
              </div>
            </div>
          </div>

          <div className="mt-4 flex items-center justify-between border-t border-neutral-800 pt-3 text-[11px] text-neutral-400">
            <span>Ambient: {(frame?.thermal_lptn?.ambient ?? 25.0).toFixed(1)} °C</span>
            <span>Hotspot delta: {((frame?.thermal_lptn?.t_winding ?? 45.0) - (frame?.thermal_lptn?.ambient ?? 25.0)).toFixed(1)} K</span>
          </div>
        </div>

        {/* Arrhenius Thermal Life Model Card */}
        <div className="rounded-xl border border-neutral-800 bg-neutral-900/60 p-6 shadow-sm flex flex-col justify-between">
          <div>
            <div className="flex items-center justify-between border-b border-neutral-800 pb-3">
              <div>
                <span className="text-xs font-mono uppercase tracking-wider text-neutral-400">
                  Arrhenius Thermal Aging
                </span>
                <h3 className="text-base font-semibold text-neutral-100">
                  Insulation Life &amp; Degradation
                </h3>
              </div>
              <span className="rounded-md border border-neutral-700 bg-neutral-800/80 px-2 py-0.5 font-mono text-[11px] text-cyan-400">
                Life = A · exp(Ea / kB·Tw)
              </span>
            </div>

            <p className="mt-2 text-xs text-neutral-400">
              Degradation kinetics based on activation energy Ea/kB = 12,000 K with 20,000 h baseline design life at rated 155°C.
            </p>

            <div className="mt-5 grid grid-cols-2 md:grid-cols-4 gap-3">
              <div className="rounded-lg border border-neutral-800 bg-neutral-950/60 p-3">
                <span className="text-xs text-neutral-400 block">Aging Acceleration</span>
                <span className={`mt-1 font-mono text-xl font-bold block ${
                  (frame?.thermal_lptn?.aging_acceleration ?? 0.05) > 2.0
                    ? 'text-rose-400'
                    : (frame?.thermal_lptn?.aging_acceleration ?? 0.05) > 1.0
                    ? 'text-amber-400'
                    : 'text-emerald-400'
                }`}>
                  {(frame?.thermal_lptn?.aging_acceleration ?? 0.05).toFixed(3)}×
                </span>
                <span className="text-[10px] text-neutral-500 block mt-1">
                  {(frame?.thermal_lptn?.aging_acceleration ?? 0.05) <= 1.0 ? 'Slower than rated' : 'Accelerated aging!'}
                </span>
              </div>

              <div className="rounded-lg border border-neutral-800 bg-neutral-950/60 p-3">
                <span className="text-xs text-neutral-400 block">Arrhenius RUL</span>
                <span className="mt-1 font-mono text-xl font-bold text-cyan-400 block">
                  {Math.round(frame?.thermal_lptn?.rul_hours ?? 20000).toLocaleString()} h
                </span>
                <span className="text-[10px] text-neutral-500 block mt-1">
                  ≈ {Math.round((frame?.thermal_lptn?.rul_hours ?? 20000) / 24).toLocaleString()} days
                </span>
              </div>

              <div className="rounded-lg border border-neutral-800 bg-neutral-950/60 p-3">
                <div className="flex items-center justify-between">
                  <span className="text-xs text-neutral-400 block">Bearing RUL (ISO 281)</span>
                  {frame?.thermal_lptn?.iso_zone && (
                    <span className="text-[9px] font-bold px-1.5 py-0.5 rounded bg-neutral-800 text-neutral-300 border border-neutral-700">
                      Zone {frame.thermal_lptn.iso_zone}
                    </span>
                  )}
                </div>
                <span className="mt-1 font-mono text-xl font-bold text-emerald-400 block">
                  {Math.round(frame?.thermal_lptn?.bearing_rul_hours ?? 30000).toLocaleString()} h
                </span>
                <span className="text-[10px] text-neutral-500 block mt-1">
                  ≈ {Math.round((frame?.thermal_lptn?.bearing_rul_hours ?? 30000) / 24).toLocaleString()} days
                </span>
              </div>

              <div className="rounded-lg border border-neutral-800 bg-neutral-950/60 p-3">
                <span className="text-xs text-neutral-400 block">Overall Service Life</span>
                <span className="mt-1 font-mono text-xl font-bold text-amber-300 block">
                  {Math.round(frame?.thermal_lptn?.overall_rul_hours ?? frame?.thermal_lptn?.rul_hours ?? 20000).toLocaleString()} h
                </span>
                <span className="text-[10px] text-neutral-400 block mt-1 uppercase font-semibold">
                  Limit: <span className="text-amber-400">{frame?.thermal_lptn?.limiting_factor?.replace('_', ' ') ?? 'insulation'}</span>
                </span>
              </div>
            </div>
          </div>

          <div className="mt-4 border-t border-neutral-800 pt-3">
            <div className="flex justify-between text-xs font-mono text-neutral-400 mb-1">
              <span>Insulation Life Remaining</span>
              <span className="text-cyan-300 font-semibold">
                {Math.min(100, Math.round(((frame?.thermal_lptn?.rul_hours ?? 20000) / 20000) * 100))}%
              </span>
            </div>
            <div className="h-2 w-full rounded-full bg-neutral-800 overflow-hidden">
              <div
                className="h-full rounded-full bg-gradient-to-r from-emerald-500 via-cyan-400 to-emerald-400 transition-all duration-500"
                style={{
                  width: `${Math.min(100, Math.max(5, ((frame?.thermal_lptn?.rul_hours ?? 20000) / 20000) * 100))}%`,
                }}
              />
            </div>
          </div>
        </div>
      </div>


      {/* Prescriptive Maintenance Guidance */}
      {recommendation && (
        <div className="rounded-xl border border-neutral-800 bg-neutral-900/60 p-6 shadow-sm">
          <div className="flex flex-wrap items-center justify-between gap-2 border-b border-neutral-800 pb-4">
            <div className="flex items-center gap-3">
              <span
                className={`rounded border px-2 py-0.5 text-xs font-mono uppercase font-bold ${
                  urgencyStyles[recommendation.urgency] || urgencyStyles.routine
                }`}
              >
                {recommendation.urgency} Action
              </span>
              <h3 className="text-lg font-semibold text-neutral-100">
                {recommendation.title}
              </h3>
            </div>
            <span className="text-xs text-neutral-400">
              Zone: <strong className="text-neutral-200">Zone {recommendation.zone}</strong> (MHI: {recommendation.mhi.toFixed(1)})
            </span>
          </div>

          <div className="mt-4">
            <h4 className="text-xs font-mono uppercase tracking-wider text-neutral-400">
              Prescriptive Action
            </h4>
            <p className="mt-1 text-sm text-neutral-200 font-medium">
              {recommendation.action}
            </p>
          </div>

          {recommendation.checklist && recommendation.checklist.length > 0 && (
            <div className="mt-5">
              <h4 className="text-xs font-mono uppercase tracking-wider text-neutral-400 mb-2">
                Field Inspection Checklist
              </h4>
              <ul className="space-y-2">
                {recommendation.checklist.map((item, idx) => (
                  <li
                    key={idx}
                    className="flex items-start gap-2.5 rounded-lg border border-neutral-800/80 bg-neutral-950/40 p-2.5 text-xs text-neutral-300"
                  >
                    <span className="text-cyan-400 font-bold mt-0.5">✓</span>
                    <span>{item}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}

      {/* Recent Diagnostic Error Codes History */}
      <div className="rounded-xl border border-neutral-800 bg-neutral-900/60 p-6 shadow-sm">
        <h3 className="text-base font-semibold text-neutral-100 mb-3">
          Historical Diagnostics & Error Codes
        </h3>
        {history.length === 0 ? (
          <p className="text-xs text-neutral-500">No diagnoses persisted yet.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="border-b border-neutral-800 text-neutral-400 uppercase tracking-wider font-mono text-[11px]">
                <tr>
                  <th className="py-2.5 px-3">Timestamp</th>
                  <th className="py-2.5 px-3">Error Code</th>
                  <th className="py-2.5 px-3">Health Index</th>
                  <th className="py-2.5 px-3">Fault</th>
                  <th className="py-2.5 px-3">Severity</th>
                  <th className="py-2.5 px-3">Confidence</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-neutral-800/60 font-mono text-neutral-300">
                {history.map((row) => (
                  <tr key={row.id} className="hover:bg-neutral-800/30">
                    <td className="py-2 px-3 text-neutral-400">{new Date(row.ts).toLocaleTimeString()}</td>
                    <td className="py-2 px-3 font-semibold text-cyan-400">{row.error_code || '—'}</td>
                    <td className="py-2 px-3">{row.health_index != null ? row.health_index.toFixed(1) : '—'}</td>
                    <td className="py-2 px-3 capitalize font-sans">{row.fault_type.replace(/_/g, ' ')}</td>
                    <td className="py-2 px-3">{row.severity_score.toFixed(3)}</td>
                    <td className="py-2 px-3">{row.confidence.toFixed(3)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}

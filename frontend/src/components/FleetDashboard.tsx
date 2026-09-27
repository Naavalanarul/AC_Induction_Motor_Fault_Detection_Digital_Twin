import React, { useState } from 'react'
import { api } from '../api/client'
import type { Frame, Motor, Role } from '../api/types'
import { MotorCard } from './MotorCard'

export interface FleetDashboardProps {
  motors: Motor[]
  frames: Record<number, Frame>
  role?: Role
  onSelectMotor: (motorId: number) => void
  onRefreshMotors: () => Promise<void>
}

export const FleetDashboard: React.FC<FleetDashboardProps> = ({
  motors,
  frames,
  role,
  onSelectMotor,
  onRefreshMotors,
}) => {
  const [seeding, setSeeding] = useState(false)
  const [seedResult, setSeedResult] = useState<string | null>(null)
  const [seedError, setSeedError] = useState<string | null>(null)

  // Compute fleet summary stats
  const totalMotors = motors.length

  let totalMhi = 0
  let trippedCount = 0
  let derateCount = 0
  let activeFaultsCount = 0

  motors.forEach((m) => {
    const f = frames[m.id]
    const mhi = f?.health_index ?? f?.diagnosis?.health_index ?? 100
    totalMhi += mhi

    const state = f?.supervisory?.state ?? 'NORMAL'
    if (state === 'TRIP') trippedCount += 1
    if (state === 'DERATE') derateCount += 1

    const faults = f?.faults ?? []
    if (faults.length > 0 || (f?.diagnosis?.fault_type && f.diagnosis.fault_type !== 'healthy')) {
      activeFaultsCount += 1
    }
  })

  const avgMhi = totalMotors > 0 ? (totalMhi / totalMotors).toFixed(1) : '100.0'

  const handleSeedPresets = async () => {
    try {
      setSeeding(true)
      setSeedError(null)
      setSeedResult(null)
      const res = await api<{ created: string[]; skipped: string[] }>('/admin/seed-presets', {
        method: 'POST',
      })
      await onRefreshMotors()
      setSeedResult(
        `Fleet seeded: ${res.created.length} created, ${res.skipped.length} existing.`
      )
    } catch (err: unknown) {
      setSeedError(err instanceof Error ? err.message : 'Failed to seed preset motors')
    } finally {
      setSeeding(false)
    }
  }

  return (
    <div className="space-y-6">
      {/* Top Banner Feedback */}
      {seedResult && (
        <div className="rounded-lg border border-emerald-500/30 bg-emerald-950/40 p-3 text-xs text-emerald-300 flex justify-between items-center">
          <span>{seedResult}</span>
          <button onClick={() => setSeedResult(null)} className="text-emerald-400 hover:text-emerald-200">
            ✕
          </button>
        </div>
      )}
      {seedError && (
        <div className="rounded-lg border border-rose-500/30 bg-rose-950/40 p-3 text-xs text-rose-300 flex justify-between items-center">
          <span>{seedError}</span>
          <button onClick={() => setSeedError(null)} className="text-rose-400 hover:text-rose-200">
            ✕
          </button>
        </div>
      )}

      {/* 4 Summary Tiles */}
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        {/* Total Motors */}
        <div className="rounded-xl border border-neutral-800 bg-neutral-900/60 p-4">
          <span className="text-xs uppercase tracking-wider text-neutral-400 block">
            Fleet Size
          </span>
          <span className="mt-1 font-mono text-3xl font-bold text-neutral-100">
            {totalMotors}
          </span>
          <span className="text-[11px] text-neutral-500 block mt-1">
            Active Digital Twins
          </span>
        </div>

        {/* Avg MHI */}
        <div className="rounded-xl border border-neutral-800 bg-neutral-900/60 p-4">
          <span className="text-xs uppercase tracking-wider text-neutral-400 block">
            Avg Health Index
          </span>
          <span
            className={`mt-1 font-mono text-3xl font-bold ${
              Number(avgMhi) >= 85
                ? 'text-emerald-400'
                : Number(avgMhi) >= 70
                ? 'text-amber-400'
                : 'text-rose-400'
            }`}
          >
            {avgMhi}
          </span>
          <span className="text-[11px] text-neutral-500 block mt-1">
            Fleet Composite Score
          </span>
        </div>

        {/* Tripped / Derate */}
        <div className="rounded-xl border border-neutral-800 bg-neutral-900/60 p-4">
          <span className="text-xs uppercase tracking-wider text-neutral-400 block">
            Tripped / Derated
          </span>
          <span
            className={`mt-1 font-mono text-3xl font-bold ${
              trippedCount > 0 ? 'text-rose-400' : derateCount > 0 ? 'text-orange-400' : 'text-neutral-100'
            }`}
          >
            {trippedCount} / {derateCount}
          </span>
          <span className="text-[11px] text-neutral-500 block mt-1">
            SADA Protective Actions
          </span>
        </div>

        {/* Active Faults */}
        <div className="rounded-xl border border-neutral-800 bg-neutral-900/60 p-4">
          <span className="text-xs uppercase tracking-wider text-neutral-400 block">
            Degraded Motors
          </span>
          <span
            className={`mt-1 font-mono text-3xl font-bold ${
              activeFaultsCount > 0 ? 'text-amber-400' : 'text-neutral-100'
            }`}
          >
            {activeFaultsCount}
          </span>
          <span className="text-[11px] text-neutral-500 block mt-1">
            Motors with Active Faults
          </span>
        </div>
      </div>

      {/* Action Header */}
      <div className="flex flex-wrap items-center justify-between gap-4 border-b border-neutral-800 pb-3">
        <div>
          <h2 className="text-lg font-semibold text-neutral-100">Fleet Operations Grid</h2>
          <p className="text-xs text-neutral-400">
            Real-time condition monitoring, supervisory status, and health index across all assets.
          </p>
        </div>

        <div className="flex items-center gap-3">
          {role === 'admin' && (
            <button
              onClick={handleSeedPresets}
              disabled={seeding}
              className="inline-flex items-center gap-2 rounded-lg bg-cyan-600 px-3.5 py-2 text-xs font-semibold text-white shadow-sm transition hover:bg-cyan-500 focus:outline-none focus:ring-2 focus:ring-cyan-400 focus:ring-offset-2 focus:ring-offset-neutral-900 disabled:opacity-50"
            >
              {seeding ? 'Seeding Fleet...' : 'Seed 5-Motor Fleet Preset'}
            </button>
          )}
          <button
            onClick={() => onRefreshMotors()}
            className="rounded-lg border border-neutral-700 bg-neutral-800 px-3 py-2 text-xs font-medium text-neutral-200 transition hover:bg-neutral-700"
          >
            Refresh
          </button>
        </div>
      </div>

      {/* Motors Grid */}
      {motors.length === 0 ? (
        <div className="rounded-xl border border-dashed border-neutral-800 p-12 text-center">
          <p className="text-sm font-medium text-neutral-300">No motors found in the fleet.</p>
          <p className="mt-1 text-xs text-neutral-500">
            Click "Seed 5-Motor Fleet Preset" above to load standard industrial presets.
          </p>
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-5 md:grid-cols-2 lg:grid-cols-3">
          {motors.map((m) => (
            <MotorCard
              key={m.id}
              motor={m}
              frame={frames[m.id]}
              onClick={() => onSelectMotor(m.id)}
            />
          ))}
        </div>
      )}
    </div>
  )
}

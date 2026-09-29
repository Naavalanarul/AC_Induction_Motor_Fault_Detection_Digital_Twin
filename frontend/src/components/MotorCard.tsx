import React from 'react'
import type { Frame, Motor, SadaStateName } from '../api/types'
import { HealthGauge } from './HealthGauge'
import { StatusBadge } from './StatusBadge'

export interface MotorCardProps {
  motor: Motor
  frame?: Frame | null
  onClick?: () => void
  isSelected?: boolean
}

export const MotorCard: React.FC<MotorCardProps> = ({ motor, frame, onClick, isSelected }) => {
  const mhi = frame?.health_index ?? frame?.diagnosis?.health_index ?? 100
  const zone = frame?.zone ?? frame?.diagnosis?.zone ?? 'A'
  const state: SadaStateName = frame?.supervisory?.state ?? 'NORMAL'
  const errorCode = frame?.error_code ?? frame?.diagnosis?.error_code ?? 'SYS-OK-A'
  const activeFaults = frame?.faults ?? []
  const primaryFault =
    activeFaults.length > 0
      ? activeFaults[0].fault_type.replace(/_/g, ' ')
      : frame?.diagnosis?.fault_type && frame.diagnosis.fault_type !== 'healthy'
      ? frame.diagnosis.fault_type.replace(/_/g, ' ')
      : 'Healthy'

  const powerKw = (motor.rated_power / 1000).toFixed(1)
  const rpm = frame?.mechanics?.rpm
    ? Math.round(frame.mechanics.rpm)
    : Math.round((motor.rated_speed * 30) / Math.PI)

  let prognosisStatus = 'Stable'
  if (state === 'TRIP') {
    prognosisStatus = 'Emergency Trip'
  } else if (state === 'DERATE') {
    prognosisStatus = 'Under Derate'
  } else if (mhi < 70) {
    prognosisStatus = 'High Degradation'
  } else if (mhi < 85) {
    prognosisStatus = 'Inspection Advised'
  }

  return (
    <div
      role="button"
      tabIndex={0}
      aria-label={`Open digital twin for ${motor.name}`}
      onClick={onClick}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault()
          onClick?.()
        }
      }}
      className={`group relative flex flex-col justify-between overflow-hidden rounded-xl border p-5 transition-all duration-200 cursor-pointer ${
        isSelected
          ? 'border-[var(--accent)] bg-[var(--surface-raised)] shadow-lg shadow-black/20 ring-1 ring-[var(--accent)]/40'
          : 'border-[var(--border)] bg-[var(--surface)] hover:border-[var(--border-hover)] hover:bg-[var(--surface-raised)] hover:shadow-md'
      }`}
    >
      {/* Top Header */}
      <div className="flex items-start justify-between gap-3">
        <div>
          <h3 className="font-semibold text-[var(--ink)] group-hover:text-[var(--accent)] transition-colors">
            {motor.name}
          </h3>
          <p className="mt-0.5 text-xs text-[var(--muted)]">
            {powerKw} kW • {rpm} RPM • ID: {motor.id}
          </p>
        </div>
        <StatusBadge state={state} />
      </div>

      {/* Middle Gauge & Metrics */}
      <div className="my-4 flex items-center justify-between gap-4">
        <HealthGauge value={mhi} zone={zone} size="md" showLabel={false} />
        <div className="flex flex-col gap-2 text-right">
          <div>
            <span className="text-[11px] uppercase tracking-wider text-[var(--muted)] block">
              Error Code
            </span>
            <span className="font-mono text-xs font-semibold text-[var(--ink)]">
              {errorCode}
            </span>
          </div>
          <div>
            <span className="text-[11px] uppercase tracking-wider text-[var(--muted)] block">
              Fault State
            </span>
            <span
              className={`text-xs font-medium capitalize ${
                primaryFault === 'Healthy' ? 'text-[var(--good)]' : 'text-[var(--warning)]'
              }`}
            >
              {primaryFault}
            </span>
          </div>
          <div>
            <span className="text-[11px] uppercase tracking-wider text-[var(--muted)] block">
              Prognosis
            </span>
            <span
              className={`text-xs font-medium ${
                state === 'TRIP'
                  ? 'text-[var(--critical)]'
                  : state === 'DERATE'
                  ? 'text-[var(--serious)]'
                  : 'text-[var(--ink-2)]'
              }`}
            >
              {prognosisStatus}
            </span>
          </div>
        </div>
      </div>

      {/* Bottom Footer Details */}
      <div className="mt-1 flex items-center justify-between border-t border-[var(--border-subtle)] pt-3 text-xs text-[var(--muted)]">
        <span>Load: {frame?.mechanics?.load_nm?.toFixed(1) ?? motor.base_load_nm.toFixed(1)} Nm</span>
        <span className="group-hover:translate-x-0.5 transition-transform text-[var(--accent)] font-medium flex items-center gap-1">
          Inspect Twin →
        </span>
      </div>
    </div>
  )
}

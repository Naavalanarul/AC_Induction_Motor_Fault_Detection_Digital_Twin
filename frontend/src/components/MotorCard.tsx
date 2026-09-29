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
          ? 'border-cyan-500 bg-neutral-900/90 shadow-lg shadow-cyan-500/10 ring-1 ring-cyan-500/50'
          : 'border-neutral-800 bg-neutral-900/50 hover:border-neutral-700 hover:bg-neutral-900/80 hover:shadow-md'
      }`}
    >
      {/* Top Header */}
      <div className="flex items-start justify-between gap-3">
        <div>
          <h3 className="font-semibold text-neutral-100 group-hover:text-cyan-400 transition-colors">
            {motor.name}
          </h3>
          <p className="mt-0.5 text-xs text-neutral-400">
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
            <span className="text-[11px] uppercase tracking-wider text-neutral-500 block">
              Error Code
            </span>
            <span className="font-mono text-xs font-semibold text-neutral-200">
              {errorCode}
            </span>
          </div>
          <div>
            <span className="text-[11px] uppercase tracking-wider text-neutral-500 block">
              Fault State
            </span>
            <span
              className={`text-xs font-medium capitalize ${
                primaryFault === 'Healthy' ? 'text-emerald-400' : 'text-amber-400'
              }`}
            >
              {primaryFault}
            </span>
          </div>
          <div>
            <span className="text-[11px] uppercase tracking-wider text-neutral-500 block">
              Prognosis
            </span>
            <span
              className={`text-xs font-medium ${
                state === 'TRIP'
                  ? 'text-rose-400'
                  : state === 'DERATE'
                  ? 'text-orange-400'
                  : 'text-neutral-300'
              }`}
            >
              {prognosisStatus}
            </span>
          </div>
        </div>
      </div>

      {/* Bottom Footer Details */}
      <div className="mt-1 flex items-center justify-between border-t border-neutral-800/80 pt-3 text-xs text-neutral-400">
        <span>Load: {frame?.mechanics?.load_nm?.toFixed(1) ?? motor.base_load_nm.toFixed(1)} Nm</span>
        <span className="group-hover:translate-x-0.5 transition-transform text-cyan-400 font-medium flex items-center gap-1">
          Inspect Twin →
        </span>
      </div>
    </div>
  )
}

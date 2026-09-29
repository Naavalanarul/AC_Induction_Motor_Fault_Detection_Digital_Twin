import React from 'react'
import { getZoneFromMHI } from '../api/types'

export interface HealthGaugeProps {
  value: number // 0 to 100
  zone?: string // 'A' | 'B' | 'C' | 'D'
  size?: 'sm' | 'md' | 'lg'
  showLabel?: boolean
}

const getZoneColor = (zone: string) => {
  switch (zone) {
    case 'A':
      return { stroke: 'var(--good)', text: 'text-emerald-500/80', bg: 'var(--good-bg)', border: 'rgba(56, 138, 102, 0.25)' }
    case 'B':
      return { stroke: 'var(--warning)', text: 'text-amber-500/80', bg: 'var(--warning-bg)', border: 'rgba(179, 131, 50, 0.25)' }
    case 'C':
      return { stroke: 'var(--serious)', text: 'text-orange-500/80', bg: 'var(--serious-bg)', border: 'rgba(176, 98, 50, 0.25)' }
    case 'D':
    default:
      return { stroke: 'var(--critical)', text: 'text-rose-500/80', bg: 'var(--critical-bg)', border: 'rgba(173, 68, 68, 0.25)' }
  }
}

export const HealthGauge: React.FC<HealthGaugeProps> = ({
  value,
  zone: explicitZone,
  size = 'md',
  showLabel = true,
}) => {
  const clamped = Math.max(0, Math.min(100, Number.isFinite(value) ? value : 0))
  const zone = explicitZone || getZoneFromMHI(clamped)
  const colors = getZoneColor(zone)

  const dimensions = {
    sm: { dim: 64, stroke: 6, fontSize: 'text-sm', zoneSize: 'text-[9px]' },
    md: { dim: 96, stroke: 8, fontSize: 'text-xl', zoneSize: 'text-xs' },
    lg: { dim: 140, stroke: 12, fontSize: 'text-3xl', zoneSize: 'text-sm' },
  }[size]

  const radius = (dimensions.dim - dimensions.stroke) / 2
  const circumference = 2 * Math.PI * radius
  const strokeDashoffset = circumference - (clamped / 100) * circumference

  return (
    <div className="flex flex-col items-center justify-center">
      <div className="relative inline-flex items-center justify-center" style={{ width: dimensions.dim, height: dimensions.dim }}>
        <svg
          width={dimensions.dim}
          height={dimensions.dim}
          viewBox={`0 0 ${dimensions.dim} ${dimensions.dim}`}
          className="rotate-[-90deg] transition-all duration-500"
          role="img"
          aria-label={`Motor Health Index: ${clamped.toFixed(1)}%, Zone ${zone}`}
        >
          {/* Background Track */}
          <circle
            cx={dimensions.dim / 2}
            cy={dimensions.dim / 2}
            r={radius}
            fill="transparent"
            stroke="currentColor"
            strokeWidth={dimensions.stroke}
            className="text-neutral-800"
          />
          {/* Animated Value Arc */}
          <circle
            cx={dimensions.dim / 2}
            cy={dimensions.dim / 2}
            r={radius}
            fill="transparent"
            stroke={colors.stroke}
            strokeWidth={dimensions.stroke}
            strokeDasharray={circumference}
            strokeDashoffset={strokeDashoffset}
            strokeLinecap="round"
            className="transition-all duration-700 ease-out"
          />
        </svg>
        <div className="absolute inset-0 flex flex-col items-center justify-center text-center">
          <span className={`font-mono font-bold tracking-tight text-white ${dimensions.fontSize}`}>
            {clamped.toFixed(0)}
          </span>
          <span className={`font-mono font-semibold uppercase tracking-wider ${colors.text} ${dimensions.zoneSize}`}>
            Zone {zone}
          </span>
        </div>
      </div>
      {showLabel && (
        <span className="mt-1 text-[11px] font-medium tracking-wide text-neutral-400">
          Health Index
        </span>
      )}
    </div>
  )
}

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
      return { stroke: '#10b981', text: 'text-emerald-400', bg: 'bg-emerald-500/10', border: 'border-emerald-500/30' }
    case 'B':
      return { stroke: '#eab308', text: 'text-amber-400', bg: 'bg-amber-500/10', border: 'border-amber-500/30' }
    case 'C':
      return { stroke: '#f97316', text: 'text-orange-400', bg: 'bg-orange-500/10', border: 'border-orange-500/30' }
    case 'D':
    default:
      return { stroke: '#f43f5e', text: 'text-rose-400', bg: 'bg-rose-500/10', border: 'border-rose-500/30' }
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

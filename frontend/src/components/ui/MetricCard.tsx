import type { ReactNode } from 'react'
import { TiltCard } from './TiltCard'

export function MetricCard({ eyebrow, value, unit, status, tone = 'cyan', children }: {
  eyebrow: string; value: string; unit?: string; status: string;
  tone?: 'cyan' | 'green' | 'amber'; children?: ReactNode
}) {
  return (
    <TiltCard className={`metric-card metric-card--${tone}`}>
      <div className="metric-card__head">
        <span className="eyebrow">{eyebrow}</span>
        <span className="metric-card__status">{status}</span>
      </div>
      <div className="metric-card__body">
        <div>
          <span className="metric-value">{value}</span>
          {unit && <span className="metric-unit">{unit}</span>}
        </div>
        {children}
      </div>
    </TiltCard>
  )
}

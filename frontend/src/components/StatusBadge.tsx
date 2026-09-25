import type { SadaStateName } from '../api/types'

// Reserved status colors, always paired with an icon + text label (never color alone).
const STYLE: Record<SadaStateName, { color: string; icon: string; text: string }> = {
  NORMAL: { color: 'var(--good)', icon: '✓', text: 'Normal' },
  WATCH: { color: 'var(--warning)', icon: '!', text: 'Watch' },
  DERATE: { color: 'var(--serious)', icon: '▼', text: 'Derate' },
  TRIP: { color: 'var(--critical)', icon: '■', text: 'Trip' },
}

export function StatusBadge({ state }: { state: SadaStateName }) {
  const s = STYLE[state]
  return (
    <span
      className="inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-sm font-semibold"
      style={{ border: `2px solid ${s.color}`, color: 'var(--ink)' }}
      data-testid="sada-state"
    >
      <span aria-hidden style={{ color: s.color }}>{s.icon}</span>
      {s.text}
    </span>
  )
}

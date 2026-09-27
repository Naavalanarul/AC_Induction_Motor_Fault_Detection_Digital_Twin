import type { SadaStateName } from '../api/types'

// Minimalist status tokens, paired with icon + text label (never color alone).
const STYLE: Record<SadaStateName, { color: string; bg: string; icon: string; text: string; border: string }> = {
  NORMAL: { color: 'var(--good)', bg: 'var(--good-bg)', icon: '✓', text: 'Normal', border: 'rgba(16, 185, 129, 0.25)' },
  WATCH: { color: 'var(--warning)', bg: 'var(--warning-bg)', icon: '!', text: 'Watch', border: 'rgba(245, 158, 11, 0.25)' },
  DERATE: { color: 'var(--serious)', bg: 'var(--serious-bg)', icon: '▼', text: 'Derate', border: 'rgba(249, 115, 22, 0.25)' },
  TRIP: { color: 'var(--critical)', bg: 'var(--critical-bg)', icon: '■', text: 'Trip', border: 'rgba(239, 68, 68, 0.3)' },
}

export function StatusBadge({ state }: { state: SadaStateName }) {
  const s = STYLE[state]
  return (
    <span
      className="inline-flex items-center gap-1.5 rounded-md px-2.5 py-0.5 text-xs font-medium tracking-wide uppercase transition-colors"
      style={{
        border: `1px solid ${s.border}`,
        backgroundColor: s.bg,
        color: s.color,
      }}
      data-testid="sada-state"
    >
      <span aria-hidden className="text-[11px] font-bold leading-none">{s.icon}</span>
      <span>{s.text}</span>
    </span>
  )
}

import { useMemo } from 'react'
import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'

export type Series = { key: string; label: string; color: string; data: number[] }

const axisTick = { fill: 'var(--muted)', fontSize: 11 }

/** Multi-series time waveform. Series share one axis and one unit (never dual-axis). */
export function WaveChart({ series, dtMs, unit, height = 150 }: { series: Series[]; dtMs: number; unit: string; height?: number }) {
  const rows = useMemo(() => {
    const n = Math.max(0, ...series.map((s) => s.data.length))
    return Array.from({ length: n }, (_, i) => {
      const row: Record<string, number> = { t: +(i * dtMs).toFixed(2) }
      for (const s of series) row[s.key] = s.data[i]
      return row
    })
  }, [series, dtMs])
  return (
    <div style={{ height }} role="img" aria-label={`${series.map((s) => s.label).join(', ')} waveform (${unit})`}>
      <ResponsiveContainer>
        <LineChart data={rows} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
          <CartesianGrid stroke="var(--grid)" strokeWidth={0.5} vertical={false} />
          <XAxis dataKey="t" tick={axisTick} stroke="var(--axis)" unit=" ms" minTickGap={40} type="number" domain={['dataMin', 'dataMax']} />
          <YAxis tick={axisTick} stroke="var(--axis)" width={52}
            tickFormatter={(v: number) => (Math.abs(v) >= 100 ? v.toFixed(0) : v.toFixed(1))} />
          <Tooltip
            contentStyle={{ background: 'var(--surface)', border: '1px solid var(--border)', fontSize: 12 }}
            labelFormatter={(v) => `${v} ms`}
            formatter={(v) => `${Number(v).toFixed(3)} ${unit}`}
            cursor={{ stroke: 'var(--axis)' }}
          />
          {series.length > 1 && <Legend iconType="plainline" wrapperStyle={{ fontSize: 11, color: 'var(--ink-2)' }} />}
          {series.map((s) => (
            <Line key={s.key} dataKey={s.key} name={s.label} stroke={s.color} strokeWidth={1.5} dot={false} isAnimationActive={false} />
          ))}
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}

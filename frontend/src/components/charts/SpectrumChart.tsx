import { useMemo } from 'react'
import { CartesianGrid, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import type { Spectrum } from '../../api/types'

const axisTick = { fill: 'var(--muted)', fontSize: 11 }

/** Single-series magnitude spectrum in dB. Optional labelled marker lines (e.g. defect frequencies). */
export function SpectrumChart({
  spectrum,
  color = 'var(--series-1)',
  height = 140,
  markers = [],
  label,
}: {
  spectrum?: Spectrum
  color?: string
  height?: number
  markers?: { f: number; label?: string }[]
  label: string
}) {
  const rows = useMemo(() => (spectrum ? spectrum.f.map((f, i) => ({ f, db: spectrum.db[i] })) : []), [spectrum])
  if (!spectrum) return <div style={{ height }} className="muted text-xs grid place-items-center">collecting…</div>
  return (
    <div style={{ height }} role="img" aria-label={`${label} spectrum`}>
      <ResponsiveContainer>
        <LineChart data={rows} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
          <CartesianGrid stroke="var(--grid)" strokeWidth={0.5} vertical={false} />
          <XAxis dataKey="f" type="number" domain={['dataMin', 'dataMax']} tick={axisTick} stroke="var(--axis)" unit=" Hz" minTickGap={40} />
          <YAxis tick={axisTick} stroke="var(--axis)" width={44} tickFormatter={(v: number) => v.toFixed(0)}
            label={{ value: 'dB', angle: -90, position: 'insideLeft', fill: 'var(--muted)', fontSize: 10, offset: 14 }} />
          <Tooltip
            contentStyle={{ background: 'var(--surface)', border: '1px solid var(--border)', fontSize: 12 }}
            labelFormatter={(v) => `${Number(v).toFixed(1)} Hz`}
            formatter={(v) => [`${Number(v).toFixed(1)} dB`, label]}
            cursor={{ stroke: 'var(--axis)' }}
          />
          {markers.map((m) => (
            <ReferenceLine key={m.label ?? m.f} x={m.f} stroke="var(--muted)" strokeDasharray="3 3"
              label={m.label ? { value: m.label, position: 'insideTopRight', fill: 'var(--ink-2)', fontSize: 10 } : undefined} />
          ))}
          <Line dataKey="db" stroke={color} strokeWidth={1.5} dot={false} isAnimationActive={false} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}

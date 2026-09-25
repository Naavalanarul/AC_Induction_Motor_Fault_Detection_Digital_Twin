import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'

const axisTick = { fill: 'var(--muted)', fontSize: 11 }

/** One measure over simulation time. Two measures => two TrendCharts, never a second axis. */
export function TrendChart<T extends { t: number }>({
  data, dataKey, unit, label, color = 'var(--series-1)', height = 110, domain,
}: {
  data: T[]; dataKey: keyof T & string; unit: string; label: string; color?: string; height?: number
  domain?: [number | 'auto', number | 'auto']
}) {
  return (
    <div style={{ height }} role="img" aria-label={`${label} trend`}>
      <ResponsiveContainer>
        <LineChart data={data} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
          <CartesianGrid stroke="var(--grid)" strokeWidth={0.5} vertical={false} />
          <XAxis dataKey="t" type="number" domain={['dataMin', 'dataMax']} tick={axisTick} stroke="var(--axis)" unit=" s"
            tickFormatter={(v: number) => v.toFixed(0)} minTickGap={40} />
          <YAxis tick={axisTick} stroke="var(--axis)" width={52} domain={domain ?? ['auto', 'auto']}
            tickFormatter={(v: number) => (Math.abs(v) < 10 ? v.toFixed(2) : Math.abs(v) < 100 ? v.toFixed(1) : v.toFixed(0))} />
          <Tooltip
            contentStyle={{ background: 'var(--surface)', border: '1px solid var(--border)', fontSize: 12 }}
            labelFormatter={(v) => `t = ${Number(v).toFixed(1)} s`}
            formatter={(v) => [`${Number(v).toFixed(2)} ${unit}`, label]}
            cursor={{ stroke: 'var(--axis)' }}
          />
          <Line dataKey={dataKey} stroke={color} strokeWidth={2} dot={false} isAnimationActive={false} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}

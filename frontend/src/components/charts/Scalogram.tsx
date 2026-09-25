import { useEffect, useRef, useState } from 'react'

// Sequential single-hue (blue) ramp, light -> dark = low -> high magnitude.
const RAMP = ['#cde2fb', '#9ec5f4', '#6da7ec', '#3987e5', '#256abf', '#184f95', '#0d366b']

function rampColor(x: number) {
  const i = Math.min(RAMP.length - 1, Math.max(0, Math.floor(x * RAMP.length)))
  return RAMP[i]
}

/** CWT magnitude heatmap (time x frequency, log-spaced rows, low freq at bottom). */
export function Scalogram({ data, height = 150 }: { data: { freqs: number[]; values: number[][]; dt: number } | null; height?: number }) {
  const ref = useRef<HTMLCanvasElement>(null)
  const [hover, setHover] = useState<string | null>(null)

  useEffect(() => {
    const c = ref.current
    if (!c || !data || !data.values.length) return
    const ctx = c.getContext('2d')
    if (!ctx) return
    const rows = data.values.length
    const cols = data.values[0].length
    let max = 0
    for (const r of data.values) for (const v of r) max = Math.max(max, v)
    c.width = cols
    c.height = rows
    for (let y = 0; y < rows; y++) {
      for (let x = 0; x < cols; x++) {
        ctx.fillStyle = rampColor(max > 0 ? Math.sqrt(data.values[y][x] / max) : 0)
        ctx.fillRect(x, rows - 1 - y, 1, 1)
      }
    }
  }, [data])

  if (!data) return <div style={{ height }} className="muted text-xs grid place-items-center">collecting…</div>
  const rows = data.values.length
  const cols = data.values[0]?.length ?? 0
  return (
    <div>
      <canvas
        ref={ref}
        style={{ width: '100%', height, imageRendering: 'pixelated', borderRadius: 4, display: 'block' }}
        role="img"
        aria-label="Vibration scalogram (continuous wavelet transform magnitude)"
        onMouseMove={(e) => {
          const r = e.currentTarget.getBoundingClientRect()
          const x = Math.floor(((e.clientX - r.left) / r.width) * cols)
          const y = rows - 1 - Math.floor(((e.clientY - r.top) / r.height) * rows)
          const v = data.values[y]?.[x]
          if (v !== undefined) setHover(`${(x * data.dt * 1000).toFixed(0)} ms · ${data.freqs[y].toFixed(0)} Hz · |W| ${v.toFixed(3)}`)
        }}
        onMouseLeave={() => setHover(null)}
      />
      <div className="flex justify-between text-[11px] muted tabular mt-1">
        <span>{data.freqs[0]?.toFixed(0)} Hz (bottom) → {data.freqs[rows - 1]?.toFixed(0)} Hz (top)</span>
        <span>{hover ?? 'hover for values'}</span>
      </div>
    </div>
  )
}

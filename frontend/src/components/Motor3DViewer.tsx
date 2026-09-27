import { useEffect, useRef, useState } from 'react'
import type { Frame } from '../api/types'

interface Motor3DViewerProps {
  frame: Frame | null
  motorName?: string
}

type ViewMode = 'assembled' | 'cutaway' | 'exploded' | 'wireframe'

export function Motor3DViewer({ frame, motorName = 'AC Induction Motor' }: Motor3DViewerProps) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null)

  // Camera State
  const [yaw, setYaw] = useState<number>(35 * (Math.PI / 180))
  const [pitch, setPitch] = useState<number>(20 * (Math.PI / 180))
  const [zoom, setZoom] = useState<number>(1.0)
  const [isDragging, setIsDragging] = useState<boolean>(false)
  const [dragStart, setDragStart] = useState<{ x: number; y: number }>({ x: 0, y: 0 })

  // Animation & View Mode
  const [viewMode, setViewMode] = useState<ViewMode>('cutaway')
  const [speedMultiplier, setSpeedMultiplier] = useState<number>(1.0)
  const [isPaused, setIsPaused] = useState<boolean>(false)
  const [explodeOffset, setExplodeOffset] = useState<number>(0)

  // Smooth exploded view lerp without re-triggering effect loop
  useEffect(() => {
    let animId: number
    const targetOffset = viewMode === 'exploded' ? 1.0 : 0.0

    const step = () => {
      let isDone = false
      setExplodeOffset((curr) => {
        const diff = targetOffset - curr
        if (Math.abs(diff) < 0.005) {
          isDone = true
          return targetOffset
        }
        return curr + diff * 0.15
      })
      if (!isDone) {
        animId = requestAnimationFrame(step)
      }
    }

    animId = requestAnimationFrame(step)
    return () => cancelAnimationFrame(animId)
  }, [viewMode])

  // Real-time dynamic values from simulation
  const rpm = frame?.mechanics?.rpm ?? 1474
  const statorTemp = frame?.sensors?.temp?.value ?? frame?.sensors?.thermal?.value ?? 45.0
  const isTripped = frame?.supervisory?.trip ?? false
  const activeFaults = frame?.faults ?? []

  const hasInterturnShort = activeFaults.some((f) => f?.fault_type === 'interturn_short')
  const hasBrokenBar = activeFaults.some((f) => f?.fault_type === 'broken_rotor_bar')
  const hasEccentricity = activeFaults.some((f) => f?.fault_type === 'eccentricity')
  const hasBearingFault = activeFaults.some((f) => f?.fault_type && f.fault_type.startsWith('bearing'))

  // Main 3D Canvas Rendering Loop
  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return

    let animFrame: number
    let rotorAngle = 0
    let fluxAngle = 0
    let lastTime = performance.now()

    const render = (now: number) => {
      const dt = (now - lastTime) / 1000
      lastTime = now

      if (!isPaused) {
        // Rotor angular speed in rad/s
        const omegaRotor = ((rpm * 2 * Math.PI) / 60) * speedMultiplier
        rotorAngle += omegaRotor * dt

        // Synchronous electrical speed (50 Hz -> 314 rad/s electrical / 2 pairs = 157 rad/s mechanical)
        const omegaSync = 157.08 * speedMultiplier
        fluxAngle += omegaSync * dt
      }

      // Handle High-DPI canvas
      const width = canvas.clientWidth
      const height = canvas.clientHeight
      const dpr = window.devicePixelRatio || 1
      if (canvas.width !== width * dpr || canvas.height !== height * dpr) {
        canvas.width = width * dpr
        canvas.height = height * dpr
      }

      ctx.save()
      ctx.scale(dpr, dpr)
      ctx.clearRect(0, 0, width, height)

      // Background ambient vignette (minimalist obsidian)
      const bgGrad = ctx.createRadialGradient(
        width / 2,
        height / 2,
        20,
        width / 2,
        height / 2,
        Math.max(width, height) / 1.5
      )
      bgGrad.addColorStop(0, '#141418')
      bgGrad.addColorStop(1, '#09090b')
      ctx.fillStyle = bgGrad
      ctx.fillRect(0, 0, width, height)

      // Center origin
      const cx = width / 2
      const cy = height / 2 + 15
      const scale = Math.min(width, height) * 0.38 * zoom

      // 3D Point Projection Function (Euler Yaw & Pitch)
      const project = (x: number, y: number, z: number): [number, number, number] => {
        // Rotate around Y axis (Yaw)
        const cosY = Math.cos(yaw)
        const sinY = Math.sin(yaw)
        const x1 = x * cosY - z * sinY
        const z1 = x * sinY + z * cosY

        // Rotate around X axis (Pitch)
        const cosP = Math.cos(pitch)
        const sinP = Math.sin(pitch)
        const y2 = y * cosP - z1 * sinP
        const z2 = y * sinP + z1 * cosP

        // Perspective division
        const distance = 4.2
        const pz = distance / (distance + z2)
        const px = cx + x1 * scale * pz
        const py = cy - y2 * scale * pz

        return [px, py, z2]
      }

      // Eccentricity orbit displacement
      let eccOffsetX = 0
      let eccOffsetY = 0
      if (hasEccentricity) {
        const eccAmp = 0.04
        eccOffsetX = Math.cos(rotorAngle * 2) * eccAmp
        eccOffsetY = Math.sin(rotorAngle * 2) * eccAmp
      }

      // Dynamic Stator Thermal Heat Color
      const heatFactor = Math.min(1, Math.max(0, (statorTemp - 25) / 80))
      const statorColor = `rgb(${Math.round(40 + heatFactor * 180)}, ${Math.round(
        60 - heatFactor * 30
      )}, ${Math.round(90 - heatFactor * 60)})`
      const finColor = `rgb(${Math.round(55 + heatFactor * 190)}, ${Math.round(
        80 - heatFactor * 35
      )}, ${Math.round(110 - heatFactor * 80)})`

      // 1. Draw Stator Housing & Cooling Fins
      const length = 1.3
      const outerR = 0.8
      const innerR = 0.52
      const fins = 16
      const zStator = -explodeOffset * 0.7

      // Draw Cooling Fins
      if (viewMode !== 'wireframe') {
        ctx.strokeStyle = finColor
        ctx.lineWidth = 1.5
        for (let i = 0; i < fins; i++) {
          const angle = (i * 2 * Math.PI) / fins
          // Skip cutaway section if in cutaway mode
          if (viewMode === 'cutaway' && angle > 0 && angle < Math.PI * 0.5) continue

          const r1 = outerR
          const r2 = outerR + 0.12
          const [p1x, p1y] = project(Math.cos(angle) * r1, Math.sin(angle) * r1, -length / 2 + zStator)
          const [p2x, p2y] = project(Math.cos(angle) * r2, Math.sin(angle) * r2, -length / 2 + zStator)
          const [p3x, p3y] = project(Math.cos(angle) * r2, Math.sin(angle) * r2, length / 2 + zStator)
          const [p4x, p4y] = project(Math.cos(angle) * r1, Math.sin(angle) * r1, length / 2 + zStator)

          ctx.beginPath()
          ctx.moveTo(p1x, p1y)
          ctx.lineTo(p2x, p2y)
          ctx.lineTo(p3x, p3y)
          ctx.lineTo(p4x, p4y)
          ctx.stroke()
        }
      }

      // Draw Stator Cylinder Shell
      const segments = 24
      ctx.strokeStyle = viewMode === 'wireframe' ? 'rgba(56, 189, 248, 0.4)' : statorColor
      ctx.lineWidth = 2
      ctx.beginPath()
      for (let i = 0; i <= segments; i++) {
        const a = (i * 2 * Math.PI) / segments
        if (viewMode === 'cutaway' && a > 0 && a < Math.PI * 0.5) continue

        const [pBackX, pBackY] = project(Math.cos(a) * outerR, Math.sin(a) * outerR, -length / 2 + zStator)
        const [pFrontX, pFrontY] = project(Math.cos(a) * outerR, Math.sin(a) * outerR, length / 2 + zStator)

        if (i === 0) ctx.moveTo(pBackX, pBackY)
        else ctx.lineTo(pBackX, pBackY)
        ctx.lineTo(pFrontX, pFrontY)
      }
      ctx.stroke()

      // 2. Draw 3-Phase Stator Windings (12 Coils)
      const numSlots = 12
      const zWindings = -explodeOffset * 0.35

      for (let s = 0; s < numSlots; s++) {
        const slotAngle = (s * 2 * Math.PI) / numSlots
        if (viewMode === 'cutaway' && slotAngle > 0.05 && slotAngle < Math.PI * 0.48) continue

        const phase = s % 3
        const phaseShift = (phase * 2 * Math.PI) / 3
        const currentMag = Math.cos(fluxAngle + phaseShift)

        // Highlight inter-turn short fault
        const isFaultedCoil = hasInterturnShort && s === 2

        let coilColor = 'rgba(217, 119, 6, 0.6)' // standard copper
        if (isFaultedCoil) {
          const spark = Math.random() > 0.3
          coilColor = spark ? '#ef4444' : '#fbbf24'
        } else if (currentMag > 0.5) {
          coilColor = '#38bdf8'
        }

        const rSlot = innerR + 0.08
        const x = Math.cos(slotAngle) * rSlot
        const y = Math.sin(slotAngle) * rSlot

        const [w1x, w1y] = project(x, y, -length / 2 - 0.08 + zWindings)
        const [w2x, w2y] = project(x, y, length / 2 + 0.08 + zWindings)

        ctx.strokeStyle = coilColor
        ctx.lineWidth = isFaultedCoil ? 5 : 3
        ctx.beginPath()
        ctx.moveTo(w1x, w1y)
        ctx.lineTo(w2x, w2y)
        ctx.stroke()

        // Corona / spark discharge effect for interturn short
        if (isFaultedCoil) {
          ctx.fillStyle = 'rgba(239, 68, 68, 0.7)'
          ctx.beginPath()
          ctx.arc(w1x, w1y, 7 + Math.random() * 5, 0, Math.PI * 2)
          ctx.fill()
        }
      }

      // 3. Rotating Airgap Magnetic Flux Particles
      if (viewMode !== 'assembled') {
        const numParticles = 20
        const fluxR = (innerR + 0.45) / 2
        ctx.fillStyle = 'rgba(6, 182, 212, 0.85)'

        for (let p = 0; p < numParticles; p++) {
          const pAngle = fluxAngle + (p * 2 * Math.PI) / numParticles
          const px = Math.cos(pAngle) * fluxR
          const py = Math.sin(pAngle) * fluxR
          const pz = Math.sin(pAngle * 3) * 0.4

          const [flx, fly] = project(px, py, pz)
          ctx.beginPath()
          ctx.arc(flx, fly, 2.5, 0, Math.PI * 2)
          ctx.fill()
        }
      }

      // 4. Central Steel Shaft
      const shaftLen = 1.9
      const zRotor = explodeOffset * 0.5

      ctx.strokeStyle = '#94a3b8'
      ctx.lineWidth = 4
      const [sh1x, sh1y] = project(eccOffsetX, eccOffsetY, -shaftLen / 2 + zRotor)
      const [sh2x, sh2y] = project(eccOffsetX, eccOffsetY, shaftLen / 2 + zRotor)
      ctx.beginPath()
      ctx.moveTo(sh1x, sh1y)
      ctx.lineTo(sh2x, sh2y)
      ctx.stroke()

      // 5. Squirrel-Cage Rotor Core & Bars
      const rotorR = 0.43
      const numBars = 16

      // Rotor End Rings
      ctx.strokeStyle = '#f59e0b'
      ctx.lineWidth = 2.5
      ctx.beginPath()
      for (let i = 0; i <= segments; i++) {
        const a = (i * 2 * Math.PI) / segments
        const rx = Math.cos(a + rotorAngle) * rotorR + eccOffsetX
        const ry = Math.sin(a + rotorAngle) * rotorR + eccOffsetY
        const [px, py] = project(rx, ry, length / 2 - 0.1 + zRotor)
        if (i === 0) ctx.moveTo(px, py)
        else ctx.lineTo(px, py)
      }
      ctx.stroke()

      // Squirrel-Cage Bars (rotating at rotorAngle)
      for (let b = 0; b < numBars; b++) {
        const barAngle = rotorAngle + (b * 2 * Math.PI) / numBars
        const isBroken = hasBrokenBar && b === 0

        const bx = Math.cos(barAngle) * rotorR + eccOffsetX
        const by = Math.sin(barAngle) * rotorR + eccOffsetY

        const [b1x, b1y] = project(bx, by, -length / 2 + 0.1 + zRotor)
        const [b2x, b2y] = project(bx, by, length / 2 - 0.1 + zRotor)

        if (isBroken) {
          // Severed bar with electrical gap spark
          ctx.strokeStyle = '#ef4444'
          ctx.lineWidth = 3
          ctx.setLineDash([6, 6])
          ctx.beginPath()
          ctx.moveTo(b1x, b1y)
          ctx.lineTo(b2x, b2y)
          ctx.stroke()
          ctx.setLineDash([])

          // Spark particle
          ctx.fillStyle = '#f59e0b'
          ctx.beginPath()
          ctx.arc((b1x + b2x) / 2 + (Math.random() - 0.5) * 6, (b1y + b2y) / 2 + (Math.random() - 0.5) * 6, 3, 0, Math.PI * 2)
          ctx.fill()
        } else {
          ctx.strokeStyle = '#e2e8f0'
          ctx.lineWidth = 2
          ctx.beginPath()
          ctx.moveTo(b1x, b1y)
          ctx.lineTo(b2x, b2y)
          ctx.stroke()
        }
      }

      // 6. Drive-End (DE) & Non-Drive-End (NDE) Bearings
      const zBearing = explodeOffset * 0.9
      const [deX, deY] = project(eccOffsetX, eccOffsetY, length / 2 + 0.15 + zBearing)
      const [ndeX, ndeY] = project(eccOffsetX, eccOffsetY, -length / 2 - 0.15 - zBearing)

      ctx.strokeStyle = hasBearingFault ? '#ef4444' : '#38bdf8'
      ctx.lineWidth = 3
      ctx.beginPath()
      ctx.arc(deX, deY, 14, 0, Math.PI * 2)
      ctx.arc(ndeX, ndeY, 14, 0, Math.PI * 2)
      ctx.stroke()

      // Bearing shockwave pulse
      if (hasBearingFault) {
        ctx.strokeStyle = 'rgba(239, 68, 68, 0.4)'
        ctx.beginPath()
        ctx.arc(deX, deY, 22 + (Date.now() % 15) * 0.5, 0, Math.PI * 2)
        ctx.stroke()
      }

      // 7. On-Canvas HUD Telemetry Overlay
      ctx.restore()
    }

    animFrame = requestAnimationFrame(function loop(t) {
      render(t)
      animFrame = requestAnimationFrame(loop)
    })

    return () => cancelAnimationFrame(animFrame)
  }, [
    yaw,
    pitch,
    zoom,
    rpm,
    statorTemp,
    isTripped,
    hasInterturnShort,
    hasBrokenBar,
    hasEccentricity,
    hasBearingFault,
    viewMode,
    explodeOffset,
    speedMultiplier,
    isPaused,
  ])

  // Mouse / Touch Drag Orbit Handlers
  const handleMouseDown = (e: React.MouseEvent) => {
    setIsDragging(true)
    setDragStart({ x: e.clientX, y: e.clientY })
  }

  const handleMouseMove = (e: React.MouseEvent) => {
    if (!isDragging) return
    const dx = e.clientX - dragStart.x
    const dy = e.clientY - dragStart.y
    setYaw((prev) => prev + dx * 0.008)
    setPitch((prev) => Math.max(-1.4, Math.min(1.4, prev + dy * 0.008)))
    setDragStart({ x: e.clientX, y: e.clientY })
  }

  const handleMouseUp = () => {
    setIsDragging(false)
  }

  const handleResetCamera = () => {
    setYaw(35 * (Math.PI / 180))
    setPitch(20 * (Math.PI / 180))
    setZoom(1.0)
  }

  return (
    <div className="card p-5 border-[var(--border)] bg-[var(--surface)] flex flex-col gap-4">
      {/* Header with Status & 3D Tag */}
      <header className="flex flex-wrap items-center justify-between gap-3 pb-3 border-b border-[var(--border)]">
        <div>
          <div className="flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-[var(--ink-2)]" />
            <h2 className="text-sm font-semibold text-[var(--ink)] uppercase tracking-wider">
              3D Digital Twin Visualizer — {motorName}
            </h2>
          </div>
          <p className="text-xs text-[var(--muted)] mt-1">
            Real-time electromagnetic flux dynamics, rotating squirrel-cage rotor, and 3D fault signatures.
          </p>
        </div>

        {/* View Mode Switcher */}
        <div className="flex items-center gap-1 bg-[var(--surface-raised)] p-0.5 rounded-lg border border-[var(--border)]">
          {(['assembled', 'cutaway', 'exploded', 'wireframe'] as ViewMode[]).map((mode) => (
            <button
              key={mode}
              onClick={() => setViewMode(mode)}
              className={`text-xs py-1 px-2.5 rounded-md capitalize font-medium transition-colors ${
                viewMode === mode
                  ? 'btn-primary font-medium'
                  : 'bg-transparent border-transparent text-[var(--muted)] hover:text-[var(--ink)]'
              }`}
            >
              {mode}
            </button>
          ))}
        </div>
      </header>

      {/* Main 3D Canvas Viewport */}
      <div
        className="relative w-full h-[480px] rounded-lg overflow-hidden border border-[var(--border)] cursor-grab active:cursor-grabbing select-none"
        onMouseDown={handleMouseDown}
        onMouseMove={handleMouseMove}
        onMouseUp={handleMouseUp}
        onMouseLeave={handleMouseUp}
      >
        <canvas ref={canvasRef} className="w-full h-full block" />

        {/* Top-Left Live Telemetry HUD Overlay */}
        <div className="absolute top-3 left-3 flex flex-col gap-1.5 p-3 rounded-md bg-[var(--surface)]/90 backdrop-blur-md border border-[var(--border)] text-xs num text-[var(--ink-2)]">
          <div className="flex items-center gap-2">
            <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" />
            <span className="font-bold text-[var(--ink)]">{rpm.toFixed(0)} RPM</span>
            <span className="text-[var(--muted)]">({((rpm * 2 * Math.PI) / 60).toFixed(1)} rad/s)</span>
          </div>
          <div className="flex items-center justify-between gap-4 text-[11px]">
            <span className="text-[var(--muted)]">Housing Temp:</span>
            <span className={`font-semibold ${statorTemp > 75 ? 'text-rose-400' : 'text-[var(--ink)]'}`}>
              {statorTemp.toFixed(1)} °C
            </span>
          </div>
          <div className="flex items-center justify-between gap-4 text-[11px]">
            <span className="text-[var(--muted)]">Synch Speed:</span>
            <span className="text-[var(--ink)] font-semibold">1500 RPM (50 Hz)</span>
          </div>
          <div className="flex items-center justify-between gap-4 text-[11px]">
            <span className="text-[var(--muted)]">Slip Velocity:</span>
            <span className="text-[var(--ink)] font-semibold">{(1500 - rpm).toFixed(0)} RPM</span>
          </div>
        </div>

        {/* Top-Right Active 3D Fault Alerts */}
        <div className="absolute top-3 right-3 flex flex-col gap-1.5 items-end">
          {hasInterturnShort && (
            <div className="px-2.5 py-1 rounded bg-rose-950/80 border border-rose-500/40 text-rose-300 text-xs num flex items-center gap-2">
              <span className="w-1.5 h-1.5 rounded-full bg-rose-500" />
              <span>ST-SHORT: Stator Coil Corona Flash</span>
            </div>
          )}
          {hasBrokenBar && (
            <div className="px-2.5 py-1 rounded bg-amber-950/80 border border-amber-500/40 text-amber-300 text-xs num flex items-center gap-2">
              <span className="w-1.5 h-1.5 rounded-full bg-amber-500" />
              <span>ROTOR-BAR: Discontinuity Sparking</span>
            </div>
          )}
          {hasEccentricity && (
            <div className="px-2.5 py-1 rounded bg-yellow-950/80 border border-yellow-500/40 text-yellow-300 text-xs num flex items-center gap-2">
              <span className="w-1.5 h-1.5 rounded-full bg-yellow-500" />
              <span>ECCENTRICITY: Rotor Shaft Orbit Precession</span>
            </div>
          )}
          {hasBearingFault && (
            <div className="px-2.5 py-1 rounded bg-red-950/80 border border-red-500/40 text-red-300 text-xs num flex items-center gap-2">
              <span className="w-1.5 h-1.5 rounded-full bg-red-500" />
              <span>BEARING: Race Shockwave Pulse</span>
            </div>
          )}
        </div>

        {/* Bottom Interactive Controls Bar */}
        <div className="absolute bottom-3 left-3 right-3 flex flex-wrap items-center justify-between gap-2 p-2 rounded-md bg-[var(--surface)]/90 backdrop-blur-md border border-[var(--border)]">
          <div className="flex items-center gap-2 text-xs">
            <button
              onClick={() => setIsPaused(!isPaused)}
              className="btn py-1 px-2.5 text-xs text-[var(--ink)]"
            >
              {isPaused ? '▶ Play' : '⏸ Pause'}
            </button>

            <span className="text-[var(--border)]">|</span>

            {/* Speed multipliers */}
            <span className="text-[11px] num text-[var(--muted)]">Speed:</span>
            {[0.2, 0.5, 1.0].map((s) => (
              <button
                key={s}
                onClick={() => setSpeedMultiplier(s)}
                className={`py-0.5 px-2 rounded text-xs num ${
                  speedMultiplier === s
                    ? 'btn-primary font-semibold'
                    : 'text-[var(--muted)] hover:text-[var(--ink)]'
                }`}
              >
                {s}x
              </button>
            ))}
          </div>

          <div className="flex items-center gap-2 text-xs">
            {/* Zoom Controls */}
            <button
              onClick={() => setZoom((z) => Math.max(0.6, z - 0.15))}
              className="btn py-1 px-2 text-[var(--ink)] num"
              title="Zoom out"
            >
              −
            </button>
            <span className="text-[11px] num text-[var(--muted)]">{(zoom * 100).toFixed(0)}%</span>
            <button
              onClick={() => setZoom((z) => Math.min(2.0, z + 0.15))}
              className="btn py-1 px-2 text-[var(--ink)] num"
              title="Zoom in"
            >
              +
            </button>

            <button
              onClick={handleResetCamera}
              className="btn py-1 px-2.5 text-[var(--muted)] hover:text-[var(--ink)] text-xs"
            >
              Reset 3D Angle
            </button>
          </div>
        </div>
      </div>

      {/* Physics & 3D Legend Bar */}
      <footer className="grid grid-cols-2 sm:grid-cols-4 gap-2.5 text-xs text-[var(--muted)] num pt-1">
        <div className="p-2 rounded-md bg-[var(--surface-raised)] border border-[var(--border)] flex items-center gap-2 cursor-default">
          <span className="w-2.5 h-2.5 rounded bg-amber-500/80" />
          <span className="text-[var(--ink-2)]">Stator 3-Phase Coils</span>
        </div>
        <div className="p-2 rounded-md bg-[var(--surface-raised)] border border-[var(--border)] flex items-center gap-2 cursor-default">
          <span className="w-2.5 h-2.5 rounded bg-zinc-400" />
          <span className="text-[var(--ink-2)]">Squirrel-Cage Rotor Bars</span>
        </div>
        <div className="p-2 rounded-md bg-[var(--surface-raised)] border border-[var(--border)] flex items-center gap-2 cursor-default">
          <span className="w-2.5 h-2.5 rounded-full bg-cyan-400" />
          <span className="text-[var(--ink-2)]">Rotating Flux Wave (50 Hz)</span>
        </div>
        <div className="p-2 rounded-md bg-[var(--surface-raised)] border border-[var(--border)] flex items-center gap-2 cursor-default">
          <span className="w-2.5 h-2.5 rounded-full bg-blue-400" />
          <span className="text-[var(--ink-2)]">Drive-End Bearing Race</span>
        </div>
      </footer>
    </div>
  )
}

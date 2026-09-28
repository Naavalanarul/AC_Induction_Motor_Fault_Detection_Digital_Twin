import { useState, type CSSProperties, type PointerEvent, type ReactNode } from 'react'

export function TiltCard({ children, className = '' }: { children: ReactNode; className?: string }) {
  const [tilt, setTilt] = useState({ x: 0, y: 0, glowX: 50, glowY: 50 })

  const handlePointerMove = (event: PointerEvent<HTMLDivElement>) => {
    const bounds = event.currentTarget.getBoundingClientRect()
    const x = (event.clientX - bounds.left) / bounds.width
    const y = (event.clientY - bounds.top) / bounds.height
    setTilt({ x: (0.5 - y) * 3, y: (x - 0.5) * 3, glowX: x * 100, glowY: y * 100 })
  }

  return (
    <div
      className={`glass-card tilt-card ${className}`}
      onPointerMove={handlePointerMove}
      onPointerLeave={() => setTilt({ x: 0, y: 0, glowX: 50, glowY: 50 })}
      style={{ '--tilt-x': `${tilt.x}deg`, '--tilt-y': `${tilt.y}deg`, '--glow-x': `${tilt.glowX}%`, '--glow-y': `${tilt.glowY}%` } as CSSProperties}
    >
      {children}
    </div>
  )
}

import React, { useState, type CSSProperties } from 'react'
import { Activity, AlertTriangle, Plus } from 'lucide-react'
import { api } from '../api/client'
import type { Frame, Motor, Role } from '../api/types'
import { getZoneFromMHI } from '../api/types'
import { MetricCard } from './ui/MetricCard'
import { AddMotorModal } from './AddMotorModal'

export interface FleetDashboardProps {
  motors: Motor[]
  frames: Record<number, Frame>
  role?: Role
  onSelectMotor: (motorId: number) => void
  onRefreshMotors: () => Promise<void>
  onOpenDsa?: () => void
}

export const FleetDashboard: React.FC<FleetDashboardProps> = ({
  motors, frames, role, onSelectMotor, onRefreshMotors, onOpenDsa,
}) => {
  const [seeding, setSeeding] = useState(false)
  const [seedResult, setSeedResult] = useState<string | null>(null)
  const [seedError, setSeedError] = useState<string | null>(null)
  const [isAddModalOpen, setIsAddModalOpen] = useState(false)

  const totalMotors = motors.length
  let totalMhi = 0
  let activeFaultsCount = 0

  motors.forEach((m) => {
    const f = frames[m.id]
    const mhi = f?.health_index ?? f?.diagnosis?.health_index ?? 100
    totalMhi += mhi
    const faults = f?.faults ?? []
    if (faults.length > 0 || (f?.diagnosis?.fault_type && f.diagnosis.fault_type !== 'healthy')) {
      activeFaultsCount += 1
    }
  })

  const avgMhi = totalMotors > 0 ? (totalMhi / totalMotors).toFixed(1) : '100.0'
  const avgMhiNum = totalMotors > 0 ? totalMhi / totalMotors : 100
  const fleetZone = getZoneFromMHI(avgMhiNum)
  const healthTone: 'green' | 'amber' = avgMhiNum >= 80 ? 'green' : 'amber'

  const handleSeedPresets = async () => {
    try {
      setSeeding(true); setSeedError(null); setSeedResult(null)
      const res = await api<{ created: string[]; skipped: string[] }>('/admin/seed-presets', { method: 'POST' })
      await onRefreshMotors()
      setSeedResult(`Fleet seeded: ${res.created.length} created, ${res.skipped.length} existing.`)
    } catch (err: unknown) {
      setSeedError(err instanceof Error ? err.message : 'Failed to seed preset motors')
    } finally {
      setSeeding(false)
    }
  }

  return (
    <div className="fleet-page">
      {seedResult && (
        <div className="glass-card" style={{ padding: '12px 16px', borderColor: 'rgba(16,185,129,0.3)', marginBottom: 16 }}>
          <p style={{ color: 'var(--good)', fontSize: 13 }}>{seedResult}</p>
        </div>
      )}
      {seedError && (
        <div className="glass-card" style={{ padding: '12px 16px', borderColor: 'rgba(239,68,68,0.3)', marginBottom: 16 }}>
          <p style={{ color: 'var(--critical)', fontSize: 13 }}>{seedError}</p>
        </div>
      )}

      <section className="fleet-intro">
        <div>
          <span className="eyebrow">PLANT MOTOR OPERATIONS</span>
          <div className="fleet-title">Fleet Operations Grid</div>
          <div className="page-subtitle">
            Assets ranked by fault severity, remaining service window, and live condition.
          </div>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <div className="live-pill">
            <span className="live-dot" />
            <span>{totalMotors} ASSETS ONLINE</span>
          </div>
          {onOpenDsa && (
            <button className="btn" onClick={onOpenDsa}>
              Fleet DSA Queue
            </button>
          )}
          {role === 'admin' && (
            <>
              <button
                className="btn btn-primary"
                onClick={() => setIsAddModalOpen(true)}
                style={{ display: 'flex', alignItems: 'center', gap: 6 }}
                title="Add new motor asset with presets or custom parameters"
              >
                <Plus size={15} />
                <span>Add Motor</span>
              </button>
              <button className="btn" onClick={handleSeedPresets} disabled={seeding}>
                {seeding ? 'Seeding...' : 'Seed Fleet Presets'}
              </button>
            </>
          )}
        </div>
      </section>

      <section className="fleet-metrics" aria-label="Fleet summary">
        <MetricCard eyebrow="Fleet Size" value={String(totalMotors)} status="ONLINE">
          <Activity size={22} className="fleet-metric-icon" />
        </MetricCard>
        <MetricCard eyebrow="ACTIVE FAULTS" value={String(activeFaultsCount)} status={activeFaultsCount > 0 ? 'ACTION' : 'CLEAR'} tone={activeFaultsCount > 0 ? 'amber' : 'cyan'}>
          <AlertTriangle size={22} className="fleet-metric-icon" style={{ color: activeFaultsCount > 0 ? 'var(--warning)' : 'var(--data-cyan, var(--accent))' }} />
        </MetricCard>
        <MetricCard eyebrow="Avg Health Index" value={avgMhi} unit="%" status={`ZONE ${fleetZone}`} tone={healthTone}>
          <div
            className="radial-dial fleet-health-dial"
            style={{ '--health-index': `${avgMhi}%` } as CSSProperties}
          >
            <div className="radial-dial__core">{fleetZone}</div>
          </div>
        </MetricCard>
      </section>

      {/* Prioritized Service Queue Table (from Enterprise Design) */}
      <section className="fleet-list-card glass-card" aria-labelledby="service-queue-title">
        <div className="fleet-list-head">
          <div>
            <span className="eyebrow">PRIORITIZED SERVICE QUEUE</span>
            <div id="service-queue-title" className="fleet-title" style={{ fontSize: '1.25rem' }}>
              Motor Assets Service Ranking
            </div>
          </div>
          <span className="fleet-updated">Live ranking updated</span>
        </div>
        <div className="fleet-table-head" aria-hidden="true">
          <span>Priority / motor</span>
          <span>Location</span>
          <span>Condition</span>
          <span>Service window</span>
          <span>Live readings</span>
        </div>
        <div className="motor-list">
          {motors.map((motor) => {
            const f = frames[motor.id]
            const mhi = f?.health_index ?? f?.diagnosis?.health_index ?? 100
            const state = f?.supervisory?.state ?? 'NORMAL'
            const faults = f?.faults ?? []
            const faultName = faults.length > 0
              ? faults[0].fault_type.replace(/_/g, ' ')
              : f?.diagnosis?.fault_type && f.diagnosis.fault_type !== 'healthy'
              ? f.diagnosis.fault_type.replace(/_/g, ' ')
              : null

            let priority: 'Critical' | 'High' | 'Medium' | 'Routine' = 'Routine'
            let serviceDays: number
            let status = 'Running nominal'

            if (state === 'TRIP' || mhi < 50) {
              priority = 'Critical'
              serviceDays = 1
              status = state === 'TRIP' ? 'Service required · Tripped' : 'Critical degradation'
            } else if (state === 'DERATE' || mhi < 70) {
              priority = 'High'
              serviceDays = Math.max(2, Math.round((mhi - 50) / 4))
              status = faultName ? `${faultName} detected` : 'Monitor closely'
            } else if (mhi < 85) {
              priority = 'Medium'
              serviceDays = Math.max(10, Math.round((mhi - 60) * 1.2))
              status = 'Inspection recommended'
            } else {
              serviceDays = Math.max(30, Math.round(mhi * 0.5))
            }

            const tempVal = f?.sensors?.temp?.value ?? f?.sensors?.thermal?.value ?? 45.0
            const vibRms = f?.sensors?.vibration?.rms
              ? Math.sqrt(Object.values(f.sensors.vibration.rms).reduce((a, b) => a + b * b, 0))
              : 2.2

            const badgeStyle = priority === 'Critical'
              ? { bg: 'rgba(239, 68, 68, 0.15)', text: '#f87171', border: 'rgba(239, 68, 68, 0.3)' }
              : priority === 'High'
              ? { bg: 'rgba(245, 158, 11, 0.15)', text: '#fbbf24', border: 'rgba(245, 158, 11, 0.3)' }
              : priority === 'Medium'
              ? { bg: 'rgba(56, 189, 248, 0.15)', text: '#38bdf8', border: 'rgba(56, 189, 248, 0.3)' }
              : { bg: 'rgba(16, 185, 129, 0.15)', text: '#34d399', border: 'rgba(16, 185, 129, 0.3)' }

            return (
              <div
                role="button"
                tabIndex={0}
                className={`motor-row motor-row--${priority.toLowerCase()}`}
                key={motor.id}
                aria-label={`Open digital twin for ${motor.name}`}
                onClick={() => onSelectMotor(motor.id)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault()
                    onSelectMotor(motor.id)
                  }
                }}
              >
                <div className="motor-identity">
                  <span
                    style={{
                      backgroundColor: badgeStyle.bg,
                      color: badgeStyle.text,
                      border: `1px solid ${badgeStyle.border}`,
                      padding: '2px 8px',
                      borderRadius: 4,
                      fontSize: 10,
                      fontWeight: 600,
                      fontFamily: 'var(--font-mono)',
                      textTransform: 'uppercase',
                    }}
                  >
                    {priority}
                  </span>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '3px' }}>
                    <span className="motor-name">{motor.name}</span>
                    <span className="motor-id" style={{ marginTop: '2px' }}>ID: {motor.id} · {(motor.rated_power / 1000).toFixed(1)} kW</span>
                  </div>
                </div>
                <span className="motor-location">Bay 0{motor.id} · Line {motor.id}</span>
                <div className="motor-condition">
                  <strong>{Math.round(mhi)}%</strong>
                  <span>{status}</span>
                </div>
                <div className="motor-service">
                  <strong>{serviceDays} days</strong>
                  <span>until planned service</span>
                </div>
                <div className="motor-readings">
                  <span>{tempVal.toFixed(1)} °C</span>
                  <span>{vibRms.toFixed(1)} mm/s</span>
                </div>
              </div>
            )
          })}
        </div>
      </section>

      <AddMotorModal
        isOpen={isAddModalOpen}
        onClose={() => setIsAddModalOpen(false)}
        onMotorAdded={async (newId) => {
          await onRefreshMotors()
          onSelectMotor(newId)
        }}
      />
    </div>
  )
}

import { QueryClient, QueryClientProvider, useQuery } from '@tanstack/react-query'
import { Suspense, lazy, useCallback, useEffect, useRef, useState, type CSSProperties, type PointerEvent as ReactPointerEvent } from 'react'
import { Box, Sun, Moon, Bell, Clock3, User } from 'lucide-react'
import { api } from './api/client'
import type { Frame, Motor, Role, SensorRow } from './api/types'
import { AuthProvider, useAuth } from './auth/AuthContext'
import { MetricCard } from './components/ui/MetricCard'
import { TrendChart } from './components/charts/TrendChart'
import { DiagnosisPanel } from './components/DiagnosisPanel'
import { FaultConsole } from './components/FaultConsole'
import { FleetDashboard } from './components/FleetDashboard'
import { FleetPriorityQueue } from './components/FleetPriorityQueue'
import { HealthMaintenanceTab } from './components/HealthMaintenanceTab'
import { LoginForm } from './components/LoginForm'
import { MotorParamsStudio } from './components/MotorParamsStudio'
import { SadaPanel } from './components/SadaPanel'
import { SensorPanels } from './components/SensorPanels'
import { TripBanner } from './components/TripBanner'
import { ErrorBoundary } from './components/ErrorBoundary'
import { SignOutConfirmModal } from './components/SignOutConfirmModal'
import { ProfileDatabaseModal } from './components/ProfileDatabaseModal'
import { AlertsModal } from './components/AlertsModal'
import { useMotorStream } from './hooks/useMotorStream'

const Motor3DViewer = lazy(() => import('./components/Motor3DViewer').then((m) => ({ default: m.Motor3DViewer })))
const HistoryView = lazy(() => import('./components/HistoryView').then((m) => ({ default: m.HistoryView })))
const EngineeringDocsModal = lazy(() =>
  import('./components/EngineeringDocsModal').then((m) => ({ default: m.EngineeringDocsModal })),
)

const queryClient = new QueryClient({ defaultOptions: { queries: { retry: 1, staleTime: 2000 } } })

type TabKey = 'fleet' | 'live' | 'maintenance' | '3d' | 'dsa' | 'params' | 'history'

function Shell() {
  const { session, logout, can } = useAuth()
  const [tab, setTab] = useState<TabKey>('fleet')
  const [selected, setSelected] = useState<number | null>(null)
  const [fleetFrames, setFleetFrames] = useState<Record<number, Frame>>({})
  const [isSignOutModalOpen, setIsSignOutModalOpen] = useState(false)
  const [isProfileModalOpen, setIsProfileModalOpen] = useState(false)
  const [isDocsModalOpen, setIsDocsModalOpen] = useState(false)
  const [isAlertsModalOpen, setIsAlertsModalOpen] = useState(false)
  const shellRef = useRef<HTMLElement>(null)
  const [theme, setTheme] = useState<'dark' | 'light'>(() => {
    return (typeof window !== 'undefined' && (localStorage.getItem('app-theme') as 'dark' | 'light')) || 'dark'
  })

  useEffect(() => {
    document.documentElement.dataset.theme = theme
    localStorage.setItem('app-theme', theme)
  }, [theme])

  const toggleTheme = () => setTheme((prev) => (prev === 'dark' ? 'light' : 'dark'))

  const handleGridPointer = (event: ReactPointerEvent<HTMLElement>) => {
    shellRef.current?.style.setProperty('--grid-cursor-x', `${(event.clientX / window.innerWidth) * 100}%`)
    shellRef.current?.style.setProperty('--grid-cursor-y', `${(event.clientY / window.innerHeight) * 100}%`)
  }

  const motors = useQuery({ queryKey: ['motors'], queryFn: () => api<Motor[]>('/motors'), enabled: !!session })
  const motorId = selected ?? motors.data?.[0]?.id ?? null
  const selectedMotor = motors.data?.find((m) => m.id === motorId)

  const sensors = useQuery({
    queryKey: ['sensors', motorId],
    queryFn: () => api<SensorRow[]>(`/motors/${motorId}/sensors`),
    enabled: motorId != null,
  })

  const handleFrame = useCallback((f: Frame) => {
    setFleetFrames((prev) => ({ ...prev, [f.motor_id]: f }))
  }, [])

  const { frame, trend, status, reconnect } = useMotorStream(
    tab !== 'history' ? motorId : null,
    120,
    handleFrame,
  )

  const trippedMotors = (motors.data || [])
    .map((m) => {
      const f = fleetFrames[m.id] || (m.id === motorId ? frame : null)
      // Acknowledged trips stay listed: the motor is still latched off until reset.
      if (f?.supervisory?.trip || f?.supervisory?.reason_code?.includes('SENSOR_LOSS')) {
        return {
          id: m.id,
          name: m.name,
          reason_code: f.supervisory.reason_code,
          acknowledged: f.supervisory.acknowledged,
          latched_fault: f.supervisory.latched_fault,
          latched_severity: f.supervisory.latched_severity,
        }
      }
      return null
    })
    .filter((x): x is NonNullable<typeof x> => x !== null)

  const isMotorView = tab !== 'fleet' && tab !== 'dsa'
  const isHardwareStream = sensors.data?.some((s) => s.mode === 'hardware') ?? false

  if (!session) return <LoginForm />

  return (
    <main ref={shellRef} className="app-shell" onPointerMove={handleGridPointer}>
      {/* Persistent Emergency Trip Banner */}
      <TripBanner
        trippedMotors={trippedMotors}
        onAcknowledged={() => { reconnect(); motors.refetch() }}
      />

      {/* Floating Navigation Bar with Separated Islands (No Continuous Bar, Gap across Center) */}
      <header className="floating-nav-bar">
        {/* Left: Brand Lockup (Standing cleanly without navbar covering, fixed at top-left) */}
        <div
          className="nav-island nav-island--brand"
          role="button"
          tabIndex={0}
          style={{ cursor: 'pointer' }}
          onClick={() => setTab('fleet')}
          onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') setTab('fleet') }}
          title="Return to Fleet Dashboard"
        >
          <div className="brand-lockup">
            <div className="brand-node">
              <Box size={20} strokeWidth={1.5} />
            </div>
            <div className="brand-copy">
              <span className="brand-name">TWIN-CORE</span>
              <span className="brand-asset">INDUSTRIAL INTELLIGENCE</span>
            </div>
          </div>
        </div>

        {/* Right Island: Motor Navigation Menu (Kept at Right End with Profile, No Fleet, No 3D Twin) */}
        <div className="nav-island nav-island--actions">
          {isMotorView && (
            <nav className="nav-links" aria-label="motor views">
              <button
                className={`nav-link${tab === 'live' ? ' is-active active' : ''}`}
                onClick={() => setTab('live')}
              >
                Telemetry
              </button>
              <button
                className={`nav-link${tab === 'maintenance' ? ' is-active active' : ''}`}
                onClick={() => setTab('maintenance')}
              >
                Maintenance
              </button>
              <button
                className={`nav-link${tab === 'params' ? ' is-active active' : ''}`}
                onClick={() => setTab('params')}
              >
                Parameters Studio
              </button>
              <button
                className={`nav-link${tab === 'history' ? ' is-active active' : ''}`}
                onClick={() => setTab('history')}
              >
                History
              </button>
            </nav>
          )}

          {isMotorView && <div className="nav-divider" />}

          <button
            onClick={toggleTheme}
            className="nav-icon-btn"
            title={`Switch to ${theme === 'dark' ? 'light' : 'dark'} mode`}
            aria-label="Toggle theme"
          >
            {theme === 'dark' ? <Sun size={18} /> : <Moon size={18} />}
          </button>

          <div className="notification-wrap">
            <button
              className="nav-icon-btn"
              aria-label="Notifications"
              onClick={() => setIsAlertsModalOpen(true)}
              title="View System Alerts"
            >
              <Bell size={18} />
            </button>
            {trippedMotors.length > 0 && (
              <span className="notification-count">{trippedMotors.length}</span>
            )}
          </div>

          <button
            type="button"
            className="nav-profile-chip"
            onClick={() => setIsProfileModalOpen(true)}
            title={`Operator Profile & Database Status (${session.username}) — Click to configure MySQL and view Docs`}
            aria-label="Operator profile and database settings"
          >
            <div className="nav-avatar">
              <User size={15} strokeWidth={2.2} />
            </div>
          </button>

          <button className="nav-signout" onClick={() => setIsSignOutModalOpen(true)}>Sign out</button>
        </div>
      </header>

      {/* Main Content */}
      <div className="dashboard">
        {tab === 'fleet' ? (
          <ErrorBoundary fallbackTitle="Error loading Fleet Dashboard">
            <FleetDashboard
              motors={motors.data ?? []}
              frames={fleetFrames}
              role={session.role as Role}
              onSelectMotor={(id) => { setSelected(id); setTab('live') }}
              onRefreshMotors={async () => { await motors.refetch() }}
              onOpenDsa={() => setTab('dsa')}
            />
          </ErrorBoundary>
        ) : motorId == null ? (
          <div className="glass-card" style={{ textAlign: 'center', padding: '48px' }}>
            <p className="text-secondary">{motors.isLoading ? 'Connecting to digital twin orchestrator…' : 'No motors configured in database.'}</p>
          </div>
        ) : tab === 'dsa' ? (
          <ErrorBoundary fallbackTitle="Error loading Fleet Priority Queue">
            <div style={{ marginBottom: 16, display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
              <div>
                <span className="eyebrow">FLEET DISPATCH &amp; TRIAGE</span>
                <h1 className="fleet-title" style={{ fontSize: '1.25rem' }}>Fleet Priority Queue (Binary Heap O(log n))</h1>
              </div>
              <button className="btn" onClick={() => setTab('fleet')}>
                ← Back to Fleet
              </button>
            </div>
            <FleetPriorityQueue />
          </ErrorBoundary>
        ) : (
          /* Motor Digital Twin Dashboard: 'live' | 'maintenance' | 'params' | 'history' | '3d' */
          <div className="motor-twin-container">
            {/* Contextual Motor Dashboard Header: Second navbar removed, only ← Motor fleet button stands alone */}
            <section className="fleet-intro" style={{ marginBottom: 16 }}>
              <div>
                <span className="eyebrow">ASSET DIGITAL TWIN &amp; TELEMETRY</span>
                <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                  <h1 className="fleet-title" style={{ whiteSpace: 'nowrap' }}>{selectedMotor?.name ?? `Motor ${motorId}`}</h1>
                  {motors.data && motors.data.length > 1 && (
                    <select
                      className="input"
                      style={{ fontSize: 12, padding: '4px 8px', height: 30, background: 'var(--surface-raised)', borderColor: 'var(--border)' }}
                      aria-label="Switch motor"
                      value={motorId ?? ''}
                      onChange={(e) => setSelected(Number(e.target.value))}
                    >
                      {motors.data.map((m) => (
                        <option key={m.id} value={m.id}>{m.name}</option>
                      ))}
                    </select>
                  )}
                </div>
                <div className="page-subtitle">
                  Asset MTR-0{motorId} · Bay 0{motorId} · Line 0{motorId} · Synchronized live
                </div>
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                <div
                  className="live-pill"
                  data-testid="telemetry-mode-badge"
                  style={{
                    borderColor: isHardwareStream ? 'rgba(0, 229, 255, 0.4)' : 'rgba(16, 185, 129, 0.4)',
                    background: isHardwareStream ? 'rgba(0, 229, 255, 0.08)' : 'rgba(16, 185, 129, 0.08)',
                    color: isHardwareStream ? 'var(--accent)' : 'var(--good)',
                    fontSize: 11,
                    letterSpacing: '0.04em',
                    fontWeight: 600,
                  }}
                  title={isHardwareStream ? 'Ingesting from physical DAQ hardware' : 'Coupled nonlinear RK45 state-space dynamic model'}
                >
                  <span
                    className="live-dot"
                    style={{ background: isHardwareStream ? 'var(--accent)' : 'var(--good)' }}
                  />
                  <span>{isHardwareStream ? 'Mode: Real Hardware Stream' : 'Mode: Dynamic State-Space Emulation'}</span>
                </div>
                <button className="btn" onClick={() => setTab('fleet')}>
                  ← Motor fleet
                </button>
              </div>
            </section>

            {tab === 'history' ? (
              <ErrorBoundary fallbackTitle="Error loading History View">
                <Suspense fallback={<div className="glass-card" style={{ textAlign: 'center', padding: '64px', color: 'var(--muted)' }}>Loading history…</div>}>
                  <HistoryView motorId={motorId} />
                </Suspense>
              </ErrorBoundary>
            ) : tab === '3d' ? (
              <ErrorBoundary fallbackTitle="Error loading 3D Digital Twin Viewer">
                <Suspense fallback={<div className="glass-card" style={{ textAlign: 'center', padding: '64px', color: 'var(--muted)' }}>Loading 3D twin…</div>}>
                  <Motor3DViewer frame={frame} motorName={selectedMotor?.name} />
                </Suspense>
              </ErrorBoundary>
            ) : !frame ? (
              <div className="glass-card" style={{ textAlign: 'center', padding: '64px' }}>
                <div style={{ width: 32, height: 32, border: '2px solid var(--ink)', borderTopColor: 'transparent', borderRadius: '50%', animation: 'login-spin 900ms linear infinite', margin: '0 auto 12px' }} />
                <p style={{ color: 'var(--ink)', fontSize: 14 }}>Streaming telemetry frames from motor simulation worker…</p>
                <p style={{ color: 'var(--muted)', fontSize: 12, marginTop: 4 }}>Checking RK4 integration state · WebSocket connection {status}</p>
                {status === 'closed' && (
                  <div style={{ display: 'flex', gap: 8, justifyContent: 'center', marginTop: 12 }}>
                    <button className="btn btn-primary" onClick={() => reconnect()}>Reconnect Stream</button>
                    <button className="btn" onClick={() => logout()}>Re-Authenticate</button>
                  </div>
                )}
              </div>
            ) : tab === 'params' ? (
              <div className="space-y-6">
                <ErrorBoundary fallbackTitle="Error loading Parameters Studio">
                  <MotorParamsStudio
                    currentMotor={selectedMotor}
                    onApplyParams={() => { motors.refetch() }}
                  />
                </ErrorBoundary>

                {/* Simulation Bench & Supervisory Interlock Transferred from Maintenance */}
                <div className="tri-panel" style={{ marginTop: 24 }}>
                  <ErrorBoundary fallbackTitle="Error loading Diagnosis Panel">
                    <DiagnosisPanel diagnosis={frame.diagnosis} mlBackend={frame.ml_backend} />
                  </ErrorBoundary>
                  <div className="tri-panel__mid">
                    <ErrorBoundary fallbackTitle="Error loading Supervisory SADA Panel">
                      <SadaPanel motorId={motorId} sup={frame.supervisory} canOperate={can('operator')} />
                    </ErrorBoundary>
                    <section className="card">
                      <header className="flex items-center justify-between mb-2">
                        <h2 className="text-xs font-semibold uppercase tracking-wider text-[var(--muted)]">
                          Smoothed Severity Trend (Last 12 s)
                        </h2>
                        <span className="text-[10px] num text-[var(--muted)] bg-[var(--surface-raised)] px-1.5 py-0.5 rounded border border-[var(--border)]">
                          EMA α=0.25
                        </span>
                      </header>
                      <TrendChart data={trend} dataKey="severity" unit="" label="Smoothed severity" height={95} domain={[0, 1]} />
                    </section>
                  </div>
                  <ErrorBoundary fallbackTitle="Error loading Fault Injection Console">
                    <FaultConsole
                      motorId={motorId}
                      faults={frame.faults}
                      canOperate={can('operator')}
                      tripped={frame.supervisory.trip}
                      tripReason={frame.supervisory.reason_code}
                    />
                  </ErrorBoundary>
                </div>
              </div>
            ) : tab === 'maintenance' ? (
              /* Maintenance Section: Health Analysis and AI Classifier (SADA and Fault Console cleared to Parameters Studio) */
              <div className="space-y-6">
                <ErrorBoundary fallbackTitle="Error loading Health & Maintenance">
                  {selectedMotor ? (
                    <HealthMaintenanceTab motor={selectedMotor} frame={frame} />
                  ) : (
                    <div className="glass-card" style={{ textAlign: 'center', padding: '48px', color: 'var(--muted)' }}>Select a motor to view health analysis.</div>
                  )}
                </ErrorBoundary>

                <ErrorBoundary fallbackTitle="Error loading Diagnosis Panel">
                  <DiagnosisPanel diagnosis={frame.diagnosis} mlBackend={frame.ml_backend} />
                </ErrorBoundary>
              </div>
            ) : (
              /* Telemetry Deck: 3-Card Symmetrical KPI Overview & 6-Sensor Network */
              <ErrorBoundary fallbackTitle="Error displaying Live Telemetry Deck">
                {/* Symmetrical 3-Card Health & Dynamics Overview (Supervisory SADA card removed) */}
                <section className="health-overview" aria-label="Motor health index">
                  {/* Health Index Card */}
                  <MetricCard
                    eyebrow="HEALTH INDEX"
                    value={String(Math.round(frame.health_index ?? frame.diagnosis?.health_index ?? 100))}
                    unit="%"
                    status={
                      (frame.health_index ?? 100) < 65 ? 'CRITICAL' : (frame.health_index ?? 100) < 80 ? 'WARNING' : 'NOMINAL'
                    }
                    tone={(frame.health_index ?? 100) < 80 ? 'amber' : 'green'}
                  >
                    <div
                      className="radial-dial"
                      aria-label={`${Math.round(frame.health_index ?? 100)} percent health`}
                      style={{ '--health-index': `${Math.round(frame.health_index ?? 100)}%` } as CSSProperties}
                    >
                      <div className="radial-dial__core">{frame.zone ?? 'A'}</div>
                    </div>
                  </MetricCard>

                  {/* Estimated Service Window */}
                  <MetricCard
                    eyebrow="ESTIMATED SERVICE"
                    value={String(
                      frame.supervisory?.state === 'TRIP'
                        ? 1
                        : frame.supervisory?.state === 'DERATE'
                        ? 3
                        : Math.max(7, Math.round(((frame.health_index ?? 100) - 50) * 0.8))
                    )}
                    unit="days"
                    status={frame.supervisory?.state === 'TRIP' ? 'CRITICAL' : (frame.health_index ?? 100) < 80 ? 'ACTION' : 'PLANNED'}
                    tone={frame.supervisory?.state === 'TRIP' || (frame.health_index ?? 100) < 80 ? 'amber' : 'green'}
                  >
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8, color: 'var(--muted)', fontSize: 12 }}>
                      <Clock3 size={18} style={{ color: 'var(--warning)' }} />
                      <span>Bearing service window</span>
                    </div>
                  </MetricCard>

                  {/* Operational Dynamics */}
                  <MetricCard
                    eyebrow="SHAFT DYNAMICS"
                    value={(frame.mechanics?.rpm ?? 0).toFixed(0)}
                    unit="RPM"
                    status={`TORQUE ${(frame.mechanics?.torque_nm ?? 0).toFixed(1)} N·m`}
                    tone="cyan"
                  >
                    <div style={{ fontSize: 11, fontFamily: 'var(--font-mono)', color: 'var(--muted)', marginTop: 4 }}>
                      Slip: {selectedMotor && selectedMotor.rated_speed > 0 ? (((selectedMotor.rated_speed - (frame.mechanics?.rpm ?? 0)) / selectedMotor.rated_speed) * 100).toFixed(1) : '—'}%
                    </div>
                  </MetricCard>
                </section>

                {/* Enterprise 6 Dual-Source Sensor Network */}
                <section style={{ marginBottom: 20 }}>
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
                    <div>
                      <span className="eyebrow">LIVE SENSOR NETWORK</span>
                      <h2 className="fleet-title" style={{ fontSize: '1.25rem' }}>Motor Instrumentation</h2>
                    </div>
                    <div className="live-pill">
                      <span className="live-dot" />
                      <span>6 DUAL-SOURCE SENSORS</span>
                    </div>
                  </div>
                  <SensorPanels
                    frame={frame}
                    sensors={sensors.data ?? []}
                    trend={trend}
                    canAdmin={can('admin')}
                    onModeChanged={() => sensors.refetch()}
                  />
                </section>
              </ErrorBoundary>
            )}
          </div>
        )}
      </div>

      {/* Main Dashboard Global Footer */}
      <footer className="app-footer" aria-label="System footer">
        <div className="app-footer__content">
          <a
            href="https://github.com/Naavalanarul/AC_Induction_Motor_Fault_Detection_Digital_Twin"
            target="_blank"
            rel="noopener noreferrer"
            className="app-footer__link"
          >
            https://github.com/Naavalanarul/AC_Induction_Motor_Fault_Detection_Digital_Twin
          </a>
          <span className="app-footer__sep">·</span>
          <span>2026</span>
          <span className="app-footer__sep">·</span>
          <span>Naavalanarul</span>
          <span className="app-footer__sep">·</span>
          <span>MIT License</span>
        </div>
      </footer>

      {/* Sign Out Confirmation Modal */}
      <SignOutConfirmModal
        isOpen={isSignOutModalOpen}
        username={session.username}
        onClose={() => setIsSignOutModalOpen(false)}
        onConfirm={() => {
          setIsSignOutModalOpen(false)
          logout()
        }}
      />

      {/* Operator Profile & Database Settings Modal */}
      <ProfileDatabaseModal
        isOpen={isProfileModalOpen}
        user={session}
        onClose={() => setIsProfileModalOpen(false)}
        onOpenDocs={() => setIsDocsModalOpen(true)}
      />

      {/* Engineering, Physics & Architecture Documentation Modal */}
      {isDocsModalOpen && (
        <Suspense fallback={null}>
          <EngineeringDocsModal
            isOpen={isDocsModalOpen}
            onClose={() => setIsDocsModalOpen(false)}
          />
        </Suspense>
      )}

      {/* Supervisory Alerts Modal */}
      <AlertsModal
        isOpen={isAlertsModalOpen}
        onClose={() => setIsAlertsModalOpen(false)}
        motorId={motorId}
        motorName={selectedMotor?.name}
        canOperate={can('operator')}
      />
    </main>
  )
}

export default function App() {
  return (
    <ErrorBoundary fallbackTitle="Application Error">
      <QueryClientProvider client={queryClient}>
        <AuthProvider>
          <Shell />
        </AuthProvider>
      </QueryClientProvider>
    </ErrorBoundary>
  )
}

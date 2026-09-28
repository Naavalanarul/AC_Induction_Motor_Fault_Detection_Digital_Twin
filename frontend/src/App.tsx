import { QueryClient, QueryClientProvider, useQuery } from '@tanstack/react-query'
import { useCallback, useEffect, useRef, useState, type CSSProperties, type PointerEvent as ReactPointerEvent } from 'react'
import { Box, Sun, Moon, Bell, Clock3, RotateCw } from 'lucide-react'
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
import { HistoryView } from './components/HistoryView'
import { LoginForm } from './components/LoginForm'
import { Motor3DViewer } from './components/Motor3DViewer'
import { MotorParamsStudio } from './components/MotorParamsStudio'
import { SadaPanel } from './components/SadaPanel'
import { SensorPanels } from './components/SensorPanels'
import { StatusBadge } from './components/StatusBadge'
import { TripBanner } from './components/TripBanner'
import { ErrorBoundary } from './components/ErrorBoundary'
import { useMotorStream } from './hooks/useMotorStream'

const queryClient = new QueryClient({ defaultOptions: { queries: { retry: 1, staleTime: 2000 } } })

type TabKey = 'fleet' | 'live' | 'maintenance' | '3d' | 'dsa' | 'params' | 'history'

const TABS: { key: TabKey; label: string }[] = [
  { key: 'fleet', label: 'Fleet' },
  { key: 'live', label: 'Live' },
  { key: 'maintenance', label: 'Health & Maintenance' },
  { key: '3d', label: '3D Motor Twin' },
  { key: 'dsa', label: 'Fleet DSA Queue' },
  { key: 'params', label: 'Parameters Studio' },
  { key: 'history', label: 'History' },
]

function Shell() {
  const { session, logout, can } = useAuth()
  const [tab, setTab] = useState<TabKey>('fleet')
  const [selected, setSelected] = useState<number | null>(null)
  const [fleetFrames, setFleetFrames] = useState<Record<number, Frame>>({})
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
    tab !== 'history' && tab !== 'params' ? motorId : null,
    120,
    handleFrame,
  )

  const trippedMotors = (motors.data || [])
    .map((m) => {
      const f = fleetFrames[m.id] || (m.id === motorId ? frame : null)
      if (f?.supervisory?.trip && !f.supervisory.acknowledged) {
        return { id: m.id, name: m.name, reason_code: f.supervisory.reason_code, acknowledged: f.supervisory.acknowledged }
      }
      return null
    })
    .filter((x): x is NonNullable<typeof x> => x !== null)

  if (!session) return <LoginForm />

  return (
    <main ref={shellRef} className="app-shell" onPointerMove={handleGridPointer}>
      {/* Persistent Emergency Trip Banner */}
      <TripBanner
        trippedMotors={trippedMotors}
        onAcknowledged={() => { reconnect(); motors.refetch() }}
      />

      {/* Floating Glass Navigation Bar */}
      <header className="floating-nav">
        <div className="brand-lockup">
          <div className="brand-node">
            <Box size={18} strokeWidth={1.5} />
          </div>
          <div className="brand-copy">
            <span className="brand-name">TWIN-CORE</span>
            <span className="brand-asset">
              {selectedMotor ? `${selectedMotor.name}` : 'MOTOR FLEET'}
            </span>
          </div>
          {(tab === 'live' || tab === '3d') && (
            <div className="live-pill">
              <span className="live-dot" />
              <span>{status === 'open' ? `LIVE · t=${frame?.t.toFixed(1) ?? '–'}s` : status === 'connecting' ? 'CONNECTING…' : 'RECONNECTING…'}</span>
            </div>
          )}
        </div>

        <div className="nav-capsule">
          {/* Motor Selector */}
          <select
            className="nav-motor-select"
            aria-label="motor"
            value={motorId ?? ''}
            onChange={(e) => setSelected(Number(e.target.value))}
          >
            {motors.data?.map((m) => (
              <option key={m.id} value={m.id}>{m.name}</option>
            ))}
          </select>

          {/* View Tabs */}
          <nav className="nav-links" aria-label="views">
            {TABS.map((t) => (
              <button
                key={t.key}
                className={`nav-link${tab === t.key ? ' is-active' : ''}`}
                onClick={() => setTab(t.key)}
              >
                {t.label}
              </button>
            ))}
          </nav>

          {/* Right Actions */}
          <div className="nav-actions">
            <button
              onClick={toggleTheme}
              className="nav-icon-btn"
              title={`Switch to ${theme === 'dark' ? 'light' : 'dark'} mode`}
              aria-label="Toggle theme"
            >
              {theme === 'dark' ? <Sun size={17} /> : <Moon size={17} />}
            </button>

            <div className="notification-wrap">
              <button className="nav-icon-btn" aria-label="Notifications">
                <Bell size={17} />
              </button>
              {trippedMotors.length > 0 && (
                <span className="notification-count">{trippedMotors.length}</span>
              )}
            </div>

            <div className="nav-session">
              <span className="nav-username">{session.username}</span>
              <span className="nav-role">{session.role}</span>
              <button className="nav-signout" onClick={logout}>Sign out</button>
            </div>
          </div>
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
            />
          </ErrorBoundary>
        ) : motorId == null ? (
          <div className="glass-card" style={{ textAlign: 'center', padding: '48px' }}>
            <p className="text-secondary">{motors.isLoading ? 'Connecting to digital twin orchestrator…' : 'No motors configured in database.'}</p>
          </div>
        ) : tab === 'maintenance' ? (
          <ErrorBoundary fallbackTitle="Error loading Health & Maintenance">
            {selectedMotor ? (
              <HealthMaintenanceTab motor={selectedMotor} frame={frame} />
            ) : (
              <div className="glass-card" style={{ textAlign: 'center', padding: '48px', color: 'var(--muted)' }}>Select a motor to view health analysis.</div>
            )}
          </ErrorBoundary>
        ) : tab === 'history' ? (
          <ErrorBoundary fallbackTitle="Error loading History View">
            <HistoryView motorId={motorId} />
          </ErrorBoundary>
        ) : tab === 'dsa' ? (
          <ErrorBoundary fallbackTitle="Error loading Fleet Priority Queue">
            <FleetPriorityQueue />
          </ErrorBoundary>
        ) : tab === 'params' ? (
          <ErrorBoundary fallbackTitle="Error loading Parameters Studio">
            <MotorParamsStudio currentMotor={selectedMotor} />
          </ErrorBoundary>
        ) : tab === '3d' ? (
          <ErrorBoundary fallbackTitle="Error loading 3D Digital Twin Viewer">
            <Motor3DViewer frame={frame} motorName={selectedMotor?.name} />
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
        ) : (
          <ErrorBoundary fallbackTitle="Error displaying Live Telemetry Deck">
            {/* Enterprise Dashboard Intro */}
            <section className="fleet-intro" style={{ marginBottom: 16 }}>
              <div>
                <span className="eyebrow">ASSET TELEMETRY &amp; DIGITAL TWIN</span>
                <h1 className="fleet-title">{selectedMotor?.name ?? `Motor ${motorId}`}</h1>
                <div className="page-subtitle">
                  Asset MTR-0{motorId} · Bay 0{motorId} · Line 0{motorId} · Synchronized moments ago
                </div>
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                <button className="btn" onClick={() => setTab('fleet')}>
                  ← Motor fleet
                </button>
                <div className="live-pill">
                  <RotateCw size={12} style={{ animation: 'login-spin 3s linear infinite' }} />
                  <span>Digital twin synchronized</span>
                </div>
              </div>
            </section>

            {/* Enterprise Symmetrical 4-Card Health Overview */}
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

              {/* Supervisory SADA State */}
              <MetricCard
                eyebrow="SUPERVISORY SADA"
                value={frame.supervisory?.state ?? 'NORMAL'}
                status={frame.supervisory?.trip ? 'TRIP LATCHED' : `LOAD ${Math.round((frame.supervisory?.load_cmd ?? 1) * 100)}%`}
                tone={frame.supervisory?.trip ? 'amber' : frame.supervisory?.state !== 'NORMAL' ? 'amber' : 'cyan'}
              >
                <div style={{ marginTop: 4 }}>
                  <StatusBadge state={frame.supervisory?.state ?? 'NORMAL'} />
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

            {/* Primary Tri-Panel Control Deck */}
            <div className="tri-panel">
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
                <FaultConsole motorId={motorId} faults={frame.faults} canOperate={can('operator')} />
              </ErrorBoundary>
            </div>
          </ErrorBoundary>
        )}
      </div>
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

import { QueryClient, QueryClientProvider, useQuery } from '@tanstack/react-query'
import { useCallback, useEffect, useState } from 'react'
import { api } from './api/client'
import type { Frame, Motor, Role, SensorRow } from './api/types'
import { AuthProvider, useAuth } from './auth/AuthContext'
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

function Shell() {
  const { session, logout, can } = useAuth()
  const [tab, setTab] = useState<'fleet' | 'live' | 'maintenance' | '3d' | 'dsa' | 'params' | 'history'>('fleet')
  const [selected, setSelected] = useState<number | null>(null)
  const [fleetFrames, setFleetFrames] = useState<Record<number, Frame>>({})
  const [theme, setTheme] = useState<'dark' | 'light'>(() => {
    return (typeof window !== 'undefined' && (localStorage.getItem('app-theme') as 'dark' | 'light')) || 'dark'
  })

  useEffect(() => {
    document.documentElement.dataset.theme = theme
    localStorage.setItem('app-theme', theme)
  }, [theme])

  const toggleTheme = () => {
    setTheme((prev) => (prev === 'dark' ? 'light' : 'dark'))
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
        return {
          id: m.id,
          name: m.name,
          reason_code: f.supervisory.reason_code,
          acknowledged: f.supervisory.acknowledged,
        }
      }
      return null
    })
    .filter((x): x is NonNullable<typeof x> => x !== null)

  if (!session) return <LoginForm />

  return (
    <div className="min-h-screen bg-[var(--page)] text-[var(--ink)] flex flex-col">
      {/* Persistent Emergency Trip Banner */}
      <TripBanner
        trippedMotors={trippedMotors}
        onAcknowledged={() => {
          reconnect()
          motors.refetch()
        }}
      />
      {/* Top Industrial Command Bar */}
      <header className="sticky top-0 z-40 border-b border-[var(--border)] bg-[var(--surface)]/95 backdrop-blur-md px-4 py-2.5">
        <div className="max-w-[1720px] mx-auto flex flex-wrap items-center justify-between gap-3">
          {/* Brand + Motor Selector + Navigation */}
          <div className="flex flex-wrap items-center gap-3 sm:gap-4">
            <div className="flex items-center gap-2.5">
              <div className="w-7 h-7 rounded-md bg-[var(--surface-raised)] border border-[var(--border)] text-[var(--ink)] flex items-center justify-center">
                <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <circle cx="12" cy="12" r="9" />
                  <circle cx="12" cy="12" r="3" />
                  <path d="M12 3v3M12 18v3M3 12h3M18 12h3" />
                </svg>
              </div>
              <div>
                <h1 className="text-sm font-semibold tracking-tight text-[var(--ink)] flex items-center gap-2">
                  <span>AC Motor Digital Twin</span>
                  <span className="text-[10px] num px-1.5 py-0.2 rounded bg-[var(--surface-raised)] text-[var(--muted)] border border-[var(--border)] uppercase">
                    v2.4 SADA
                  </span>
                </h1>
              </div>
            </div>

            <div className="h-4 w-[1px] bg-[var(--border)] hidden sm:block" />

            {/* Motor Selector with Specs Pill */}
            <div className="flex items-center gap-2">
              <select
                className="input py-1 text-xs num font-medium bg-[var(--surface-raised)] border-[var(--border)] text-[var(--ink)]"
                aria-label="motor"
                value={motorId ?? ''}
                onChange={(e) => setSelected(Number(e.target.value))}
              >
                {motors.data?.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.name}
                  </option>
                ))}
              </select>

              {selectedMotor && (
                <span className="hidden md:inline-flex items-center gap-1.5 px-2 py-0.5 rounded bg-[var(--surface-raised)] border border-[var(--border)] text-[11px] num text-[var(--muted)]">
                  <span className="text-[var(--ink)]">{(selectedMotor.rated_power / 1000).toFixed(1)} kW</span>
                  <span>·</span>
                  <span>{selectedMotor.rated_speed} RPM</span>
                  <span>·</span>
                  <span>{selectedMotor.rated_torque.toFixed(1)} N·m</span>
                </span>
              )}
            </div>

            <div className="h-4 w-[1px] bg-[var(--border)] hidden sm:block" />

            {/* View Switcher */}
            <nav className="flex flex-wrap gap-1 bg-[var(--surface-raised)] p-0.5 rounded-lg border border-[var(--border)]" aria-label="views">
              <button
                className={`btn text-xs py-1 px-3 rounded-md transition-all ${
                  tab === 'fleet' ? 'btn-primary font-medium' : 'bg-transparent border-transparent text-[var(--muted)] hover:text-[var(--ink)]'
                }`}
                onClick={() => setTab('fleet')}
              >
                Fleet
              </button>
              <button
                className={`btn text-xs py-1 px-3 rounded-md transition-all ${
                  tab === 'live' ? 'btn-primary font-medium' : 'bg-transparent border-transparent text-[var(--muted)] hover:text-[var(--ink)]'
                }`}
                onClick={() => setTab('live')}
              >
                Live
              </button>
              <button
                className={`btn text-xs py-1 px-3 rounded-md transition-all ${
                  tab === 'maintenance' ? 'btn-primary font-medium' : 'bg-transparent border-transparent text-[var(--muted)] hover:text-[var(--ink)]'
                }`}
                onClick={() => setTab('maintenance')}
              >
                Health & Maintenance
              </button>
              <button
                className={`btn text-xs py-1 px-3 rounded-md transition-all ${
                  tab === '3d' ? 'btn-primary font-medium' : 'bg-transparent border-transparent text-[var(--muted)] hover:text-[var(--ink)]'
                }`}
                onClick={() => setTab('3d')}
              >
                3D Motor Twin
              </button>
              <button
                className={`btn text-xs py-1 px-3 rounded-md transition-all ${
                  tab === 'dsa' ? 'btn-primary font-medium' : 'bg-transparent border-transparent text-[var(--muted)] hover:text-[var(--ink)]'
                }`}
                onClick={() => setTab('dsa')}
              >
                Fleet DSA Queue
              </button>
              <button
                className={`btn text-xs py-1 px-3 rounded-md transition-all ${
                  tab === 'params' ? 'btn-primary font-medium' : 'bg-transparent border-transparent text-[var(--muted)] hover:text-[var(--ink)]'
                }`}
                onClick={() => setTab('params')}
              >
                Parameters Studio
              </button>
              <button
                className={`btn text-xs py-1 px-3 rounded-md transition-all ${
                  tab === 'history' ? 'btn-primary font-medium' : 'bg-transparent border-transparent text-[var(--muted)] hover:text-[var(--ink)]'
                }`}
                onClick={() => setTab('history')}
              >
                History
              </button>
            </nav>
          </div>

          {/* Right Controls: Stream status, Theme, User role, Logout */}
          <div className="flex items-center gap-3 text-xs">
            {(tab === 'live' || tab === '3d') && (
              <div className="flex items-center gap-2 px-2.5 py-1 rounded-full bg-[var(--surface-raised)] border border-[var(--border)]">
                <span
                  className={`w-1.5 h-1.5 rounded-full ${
                    status === 'open'
                      ? 'bg-emerald-400'
                      : status === 'connecting'
                      ? 'bg-amber-400 animate-pulse'
                      : 'bg-rose-500'
                  }`}
                />
                <span className="muted tabular num text-[11px]" role="status">
                  {status === 'open' ? `live · t=${frame?.t.toFixed(1) ?? '–'}s` : status === 'connecting' ? 'connecting…' : 'reconnecting…'}
                </span>
              </div>
            )}

            {/* Dark / Light Mode Toggle */}
            <button
              onClick={toggleTheme}
              className="p-1.5 rounded-md bg-[var(--surface-raised)] border border-[var(--border)] hover:border-[var(--border-hover)] text-[var(--muted)] hover:text-[var(--ink)] transition-colors"
              title={`Switch to ${theme === 'dark' ? 'light' : 'dark'} mode`}
              aria-label="Toggle theme"
            >
              {theme === 'dark' ? (
                <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M12 3v1m0 16v1m9-9h-1M4 12H3m15.364 6.364l-.707-.707M6.343 6.343l-.707-.707m12.728 0l-.707.707M6.343 17.657l-.707.707M16 12a4 4 0 11-8 0 4 4 0 018 0z" />
                </svg>
              ) : (
                <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M20.354 15.354A9 9 0 018.646 3.646 9.003 9.003 0 0012 21a9.003 9.003 0 008.354-5.646z" />
                </svg>
              )}
            </button>

            {/* Session Info */}
            <div className="flex items-center gap-2 pl-2 border-l border-[var(--border)]">
              <span className="muted hidden sm:inline">{session.username}</span>
              <span className="text-[10px] uppercase num px-1.5 py-0.5 rounded font-medium bg-[var(--surface-raised)] border border-[var(--border)] text-[var(--muted)]">
                {session.role}
              </span>
              <button
                className="btn text-xs py-1 px-2.5 bg-[var(--surface-raised)] border-[var(--border)] hover:border-rose-800 hover:text-rose-400 transition-colors"
                onClick={logout}
              >
                Sign out
              </button>
            </div>
          </div>
        </div>
      </header>

      {/* Main Container */}
      <main className="max-w-[1720px] w-full mx-auto px-4 py-4 flex-1 flex flex-col gap-4">
        {tab === 'fleet' ? (
          <ErrorBoundary fallbackTitle="Error loading Fleet Dashboard">
            <FleetDashboard
              motors={motors.data ?? []}
              frames={fleetFrames}
              role={session.role as Role}
              onSelectMotor={(id) => {
                setSelected(id)
                setTab('live')
              }}
              onRefreshMotors={async () => {
                await motors.refetch()
              }}
            />
          </ErrorBoundary>
        ) : motorId == null ? (
          <div className="card text-center py-12">
            <p className="muted">{motors.isLoading ? 'Connecting to digital twin orchestrator…' : 'No motors configured in database.'}</p>
          </div>
        ) : tab === 'maintenance' ? (
          <ErrorBoundary fallbackTitle="Error loading Health & Maintenance">
            {selectedMotor ? (
              <HealthMaintenanceTab motor={selectedMotor} frame={frame} />
            ) : (
              <div className="card text-center py-12 text-neutral-400">Select a motor to view health analysis.</div>
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
          <div className="card text-center py-16 flex flex-col items-center justify-center gap-3">
            <div className="w-8 h-8 border-2 border-[var(--ink)] border-t-transparent rounded-full animate-spin" />
            <p className="text-[var(--ink)] num text-sm">Streaming telemetry frames from motor simulation worker…</p>
            <p className="text-xs text-[var(--muted)] num">Checking RK4 integration state · WebSocket connection {status}</p>
            {status === 'closed' && (
              <div className="flex items-center gap-2 mt-2">
                <button
                  type="button"
                  className="btn btn-primary text-xs py-1.5 px-3"
                  onClick={() => reconnect()}
                >
                  Reconnect Stream
                </button>
                <button
                  type="button"
                  className="btn text-xs py-1.5 px-3"
                  onClick={() => logout()}
                >
                  Re-Authenticate
                </button>
              </div>
            )}
          </div>
        ) : (
          <ErrorBoundary fallbackTitle="Error displaying Live Telemetry Deck">
            {/* Live Operational KPI HUD Banner */}
            <section className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3" aria-label="Operational Telemetry HUD">
              {/* Rotor Speed */}
              <div className="card card-interactive p-3.5 flex flex-col justify-between">
                <span className="text-[10px] uppercase tracking-wider text-[var(--muted)] font-medium flex items-center justify-between">
                  <span>Rotor Speed</span>
                  <span className="w-1.5 h-1.5 rounded-full bg-[var(--ink-2)]" />
                </span>
                <div className="mt-2 flex items-baseline gap-1.5">
                  <span className="text-2xl font-bold num-kpi text-[var(--ink)]">{(frame.mechanics?.rpm ?? 0).toFixed(0)}</span>
                  <span className="text-xs num text-[var(--muted)]">RPM</span>
                </div>
                <span className="text-[10px] num text-[var(--muted)] mt-1.5">
                  Slip: {selectedMotor && selectedMotor.rated_speed > 0 ? (((selectedMotor.rated_speed - (frame.mechanics?.rpm ?? 0)) / selectedMotor.rated_speed) * 100).toFixed(1) : '—'}%
                </span>
              </div>

              {/* Electromagnetic Torque */}
              <div className="card card-interactive p-3.5 flex flex-col justify-between">
                <span className="text-[10px] uppercase tracking-wider text-[var(--muted)] font-medium flex items-center justify-between">
                  <span>Shaft Torque</span>
                  <span className="w-1.5 h-1.5 rounded-full bg-[var(--ink-2)]" />
                </span>
                <div className="mt-2 flex items-baseline gap-1.5">
                  <span className="text-2xl font-bold num-kpi text-[var(--ink)]">{(frame.mechanics?.torque_nm ?? 0).toFixed(1)}</span>
                  <span className="text-xs num text-[var(--muted)]">N·m</span>
                </div>
                <span className="text-[10px] num text-[var(--muted)] mt-1.5">
                  Demand: {(frame.mechanics?.load_nm ?? 0).toFixed(1)} N·m
                </span>
              </div>

              {/* Stator Current RMS */}
              <div className="card card-interactive p-3.5 flex flex-col justify-between">
                <span className="text-[10px] uppercase tracking-wider text-[var(--muted)] font-medium flex items-center justify-between">
                  <span>Phase Current IA</span>
                  <span className="w-1.5 h-1.5 rounded-full bg-[var(--ink-2)]" />
                </span>
                <div className="mt-2 flex items-baseline gap-1.5">
                  <span className="text-2xl font-bold num-kpi text-[var(--ink)]">
                    {(frame.sensors?.current?.rms?.ia ?? 0).toFixed(2)}
                  </span>
                  <span className="text-xs num text-[var(--muted)]">A RMS</span>
                </div>
                <span className="text-[10px] num text-[var(--muted)] mt-1.5">
                  IB: {(frame.sensors?.current?.rms?.ib ?? 0).toFixed(2)} · IC: {(frame.sensors?.current?.rms?.ic ?? 0).toFixed(2)}
                </span>
              </div>

              {/* Stator Temp */}
              <div className="card card-interactive p-3.5 flex flex-col justify-between">
                <span className="text-[10px] uppercase tracking-wider text-[var(--muted)] font-medium flex items-center justify-between">
                  <span>Stator Temp</span>
                  <span className={`w-1.5 h-1.5 rounded-full ${(frame.sensors?.temp?.value ?? frame.sensors?.thermal?.value ?? 0) > 85 ? 'bg-rose-500' : 'bg-[var(--ink-2)]'}`} />
                </span>
                <div className="mt-2 flex items-baseline gap-1.5">
                  <span className="text-2xl font-bold num-kpi text-[var(--ink)]">
                    {(frame.sensors?.temp?.value ?? frame.sensors?.thermal?.value ?? 45.0).toFixed(1)}
                  </span>
                  <span className="text-xs num text-[var(--muted)]">°C</span>
                </div>
                <span className="text-[10px] num text-[var(--muted)] mt-1.5">
                  Ambient: 25.0 °C
                </span>
              </div>

              {/* SADA State Badge */}
              <div className="card card-interactive p-3.5 flex flex-col justify-between">
                <span className="text-[10px] uppercase tracking-wider text-[var(--muted)] font-medium flex items-center justify-between">
                  <span>Supervisory State</span>
                  <span className="w-1.5 h-1.5 rounded-full bg-[var(--ink-2)]" />
                </span>
                <div className="mt-2">
                  <StatusBadge state={frame.supervisory?.state ?? 'NORMAL'} />
                </div>
                <span className="text-[10px] num text-[var(--muted)] mt-1.5">
                  Load cmd: {((frame.supervisory?.load_cmd ?? 1) * 100).toFixed(0)}%
                </span>
              </div>

              {/* Safety Interlock Trip Status */}
              <div className="card card-interactive p-3.5 flex flex-col justify-between">
                <span className="text-[10px] uppercase tracking-wider text-[var(--muted)] font-medium flex items-center justify-between">
                  <span>Trip Interlock</span>
                  <span className={`w-1.5 h-1.5 rounded-full ${frame.supervisory?.trip ? 'bg-rose-500' : 'bg-emerald-500'}`} />
                </span>
                <div className="mt-2">
                  <span className={`text-xs font-semibold num px-2 py-0.5 rounded border inline-block ${
                    frame.supervisory?.trip
                      ? 'bg-rose-950/40 text-rose-300 border-rose-500/30'
                      : 'bg-emerald-950/40 text-emerald-300 border-emerald-500/30'
                  }`}>
                    {frame.supervisory?.trip ? 'TRIPPED' : 'ARMED / OK'}
                  </span>
                </div>
                <span className="text-[10px] num text-[var(--muted)] mt-1.5">
                  Severity EMA: {((frame.supervisory?.smoothed_severity ?? 0) * 100).toFixed(0)}%
                </span>
              </div>
            </section>

            {/* Primary Tri-Panel Control Deck */}
            <div className="grid gap-4 lg:grid-cols-[1.2fr_1fr_1fr]">
              <ErrorBoundary fallbackTitle="Error loading Diagnosis Panel">
                <DiagnosisPanel diagnosis={frame.diagnosis} mlBackend={frame.ml_backend} />
              </ErrorBoundary>
              <div className="grid gap-4">
                <ErrorBoundary fallbackTitle="Error loading Supervisory SADA Panel">
                  <SadaPanel motorId={motorId} sup={frame.supervisory} canOperate={can('operator')} />
                </ErrorBoundary>
                <section className="card p-4 bg-[var(--surface)] border-[var(--border)]">
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

            {/* Deep Sensor Telemetry Deck */}
            <ErrorBoundary fallbackTitle="Error loading Sensor Telemetry Panels">
              <SensorPanels
                frame={frame}
                sensors={sensors.data ?? []}
                trend={trend}
                canAdmin={can('admin')}
                onModeChanged={() => sensors.refetch()}
              />
            </ErrorBoundary>
          </ErrorBoundary>
        )}
      </main>
    </div>
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


import { QueryClient, QueryClientProvider, useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { api } from './api/client'
import type { Motor, SensorRow } from './api/types'
import { AuthProvider, useAuth } from './auth/AuthContext'
import { TrendChart } from './components/charts/TrendChart'
import { DiagnosisPanel } from './components/DiagnosisPanel'
import { FaultConsole } from './components/FaultConsole'
import { HistoryView } from './components/HistoryView'
import { LoginForm } from './components/LoginForm'
import { SadaPanel } from './components/SadaPanel'
import { SensorPanels } from './components/SensorPanels'
import { useMotorStream } from './hooks/useMotorStream'

const queryClient = new QueryClient({ defaultOptions: { queries: { retry: 1, staleTime: 2000 } } })

function Shell() {
  const { session, logout, can } = useAuth()
  const [tab, setTab] = useState<'live' | 'history'>('live')
  const [selected, setSelected] = useState<number | null>(null)
  const motors = useQuery({ queryKey: ['motors'], queryFn: () => api<Motor[]>('/motors'), enabled: !!session })
  const motorId = selected ?? motors.data?.[0]?.id ?? null
  const sensors = useQuery({
    queryKey: ['sensors', motorId],
    queryFn: () => api<SensorRow[]>(`/motors/${motorId}/sensors`),
    enabled: motorId != null,
  })
  const { frame, trend, status } = useMotorStream(tab === 'live' ? motorId : null)

  if (!session) return <LoginForm />
  return (
    <div className="max-w-[1600px] mx-auto px-4 py-3 grid gap-3">
      <header className="flex flex-wrap items-center gap-3 justify-between">
        <div className="flex items-center gap-3">
          <h1 className="text-lg font-semibold">AC Motor Digital Twin</h1>
          <select className="input" aria-label="motor" value={motorId ?? ''} onChange={(e) => setSelected(Number(e.target.value))}>
            {motors.data?.map((m) => <option key={m.id} value={m.id}>{m.name}</option>)}
          </select>
          <nav className="flex gap-1" aria-label="views">
            <button className={`btn ${tab === 'live' ? 'btn-primary' : ''}`} onClick={() => setTab('live')}>Live</button>
            <button className={`btn ${tab === 'history' ? 'btn-primary' : ''}`} onClick={() => setTab('history')}>History</button>
          </nav>
        </div>
        <div className="flex items-center gap-3 text-sm">
          {tab === 'live' && (
            <span className="muted tabular" role="status">
              {status === 'open' ? `● live · t=${frame?.t.toFixed(1) ?? '–'} s` : status === 'connecting' ? 'connecting…' : 'reconnecting…'}
            </span>
          )}
          <span className="muted">{session.username} ({session.role})</span>
          <button className="btn" onClick={logout}>Sign out</button>
        </div>
      </header>

      {motorId == null ? (
        <p className="muted">{motors.isLoading ? 'Loading motors…' : 'No motors configured.'}</p>
      ) : tab === 'history' ? (
        <HistoryView motorId={motorId} />
      ) : !frame ? (
        <p className="muted">Waiting for live data…</p>
      ) : (
        <>
          <div className="grid gap-3 lg:grid-cols-[1.2fr_1fr_1fr]">
            <DiagnosisPanel diagnosis={frame.diagnosis} mlBackend={frame.ml_backend} />
            <div className="grid gap-3">
              <SadaPanel motorId={motorId} sup={frame.supervisory} canOperate={can('operator')} />
              <section className="card">
                <h2 className="text-xs muted">Smoothed severity (last 12 s)</h2>
                <TrendChart data={trend} dataKey="severity" unit="" label="Smoothed severity" height={90} domain={[0, 1]} />
              </section>
            </div>
            <FaultConsole motorId={motorId} faults={frame.faults} canOperate={can('operator')} />
          </div>
          <SensorPanels frame={frame} sensors={sensors.data ?? []} trend={trend} canAdmin={can('admin')}
            onModeChanged={() => sensors.refetch()} />
        </>
      )}
    </div>
  )
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <Shell />
      </AuthProvider>
    </QueryClientProvider>
  )
}

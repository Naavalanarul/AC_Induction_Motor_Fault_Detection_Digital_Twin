import { useState, useEffect } from 'react'
import { createPortal } from 'react-dom'
import { useQuery } from '@tanstack/react-query'
import {
  User,
  Database,
  CheckCircle2,
  AlertTriangle,
  RefreshCw,
  X,
  Lock,
  Eye,
  EyeOff,
  Server,
  Activity,
  ShieldCheck,
  Loader2,
  HardDrive,
  KeyRound,
  BookOpen,
} from 'lucide-react'
import { api } from '../api/client'
import type { DatabaseStatus, DbTestResult, Role } from '../api/types'

export interface ProfileDatabaseModalProps {
  isOpen: boolean
  onClose: () => void
  onOpenDocs?: () => void
  user: {
    username: string
    role: Role | string
  }
}

export function ProfileDatabaseModal({ isOpen, onClose, onOpenDocs, user }: ProfileDatabaseModalProps) {
  // DB status query via TanStack Query
  const {
    data: dbStatus,
    isLoading: loadingStatus,
    error: queryError,
    refetch: fetchStatus,
  } = useQuery({
    queryKey: ['db-status'],
    queryFn: () => api<DatabaseStatus>('/system/db-status'),
    enabled: isOpen,
    staleTime: 1000,
  })

  const statusError = queryError ? (queryError as Error).message : null

  // MySQL configuration form state
  const [mysqlUser, setMysqlUser] = useState<string>('dt')
  const [mysqlPassword, setMysqlPassword] = useState<string>('')
  const [mysqlHost, setMysqlHost] = useState<string>('localhost')
  const [mysqlPort, setMysqlPort] = useState<number>(3306)
  const [mysqlDatabase, setMysqlDatabase] = useState<string>('digital_twin')
  const [showPassword, setShowPassword] = useState<boolean>(false)

  // Test / apply action state
  const [testing, setTesting] = useState<boolean>(false)
  const [applying, setApplying] = useState<boolean>(false)
  const [testResult, setTestResult] = useState<DbTestResult | null>(null)

  // Escape key listener & body scroll lock
  useEffect(() => {
    if (!isOpen) return
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', handleKeyDown)
    const prevOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      window.removeEventListener('keydown', handleKeyDown)
      document.body.style.overflow = prevOverflow
    }
  }, [isOpen, onClose])

  if (!isOpen) return null

  const handleTestConnection = async (apply: boolean) => {
    if (apply) {
      setApplying(true)
    } else {
      setTesting(true)
    }
    setTestResult(null)

    try {
      const res = await api<DbTestResult>('/system/db-test', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          password: mysqlPassword,
          user: mysqlUser,
          host: mysqlHost,
          port: Number(mysqlPort),
          database: mysqlDatabase,
          apply,
        }),
      })
      setTestResult(res)
      if (res.success && apply) {
        // Refetch active status immediately
        await fetchStatus()
      }
    } catch (err: unknown) {
      setTestResult({
        success: false,
        message: err instanceof Error ? err.message : 'Database connection test request failed',
        latency_ms: null,
        applied: false,
      })
    } finally {
      setTesting(false)
      setApplying(false)
    }
  }

  const isConnected = dbStatus?.connected ?? false

  return createPortal(
    <div className="modal-backdrop" onClick={onClose} role="presentation">
      <div
        className="modal-dialog glass-card profile-modal-dialog"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-labelledby="profile-modal-title"
      >
        {/* Header */}
        <header className="modal-header">
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <div
              style={{
                width: 36,
                height: 36,
                borderRadius: '50%',
                background: 'rgba(0, 229, 255, 0.12)',
                border: '1.5px solid var(--accent)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                color: 'var(--accent)',
                boxShadow: '0 0 12px rgba(0, 229, 255, 0.25)',
              }}
            >
              <User size={18} strokeWidth={2.2} />
            </div>
            <div>
              <span className="eyebrow" style={{ color: 'var(--accent)' }}>OPERATOR PROFILE &amp; SYSTEM</span>
              <h2 id="profile-modal-title" className="fleet-title" style={{ fontSize: '1.2rem', marginTop: 1 }}>
                Operator Profile &amp; Database Settings
              </h2>
            </div>
          </div>
          <button
            type="button"
            className="nav-icon-btn"
            onClick={onClose}
            aria-label="Close dialog"
            title="Close dialog"
          >
            <X size={18} />
          </button>
        </header>

        {/* Scrollable Modal Body */}
        <div className="modal-body">
          {/* Card 1: Active Operator Profile */}
          <section className="card" style={{ padding: '16px 20px', display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 12 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
              <div
                style={{
                  width: 44,
                  height: 44,
                  borderRadius: 10,
                  background: 'var(--surface-hover)',
                  border: '1px solid var(--border)',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  color: 'var(--ink)',
                }}
              >
                <ShieldCheck size={24} style={{ color: 'var(--good)' }} />
              </div>
              <div>
                <div style={{ fontSize: 15, fontWeight: 700, color: 'var(--ink)' }}>
                  {user.username}
                </div>
                <div style={{ fontSize: 12, color: 'var(--muted)', marginTop: 2, display: 'flex', alignItems: 'center', gap: 8 }}>
                  <span
                    style={{
                      padding: '2px 8px',
                      borderRadius: 'var(--corner-full)',
                      background: 'rgba(0, 229, 255, 0.1)',
                      border: '1px solid rgba(0, 229, 255, 0.3)',
                      color: 'var(--accent)',
                      fontSize: 10,
                      fontWeight: 700,
                      letterSpacing: '0.05em',
                      textTransform: 'uppercase',
                    }}
                  >
                    Role: {user.role}
                  </span>
                  <span>TLS Secured Session</span>
                </div>
              </div>
            </div>
            <div style={{ textAlign: 'right', fontSize: 11, color: 'var(--muted)' }}>
              <div>Plant Network Gateway</div>
              <div style={{ color: 'var(--good)', fontWeight: 600, marginTop: 2 }}>● Authenticated</div>
            </div>
          </section>

          {/* Card 2: Physics Engine & Scientific Documentation */}
          <section
            className="card"
            style={{
              padding: '16px 20px',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              gap: 16,
              background: 'linear-gradient(135deg, rgba(0, 229, 255, 0.07), rgba(16, 185, 129, 0.04))',
              borderColor: 'rgba(0, 229, 255, 0.28)',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
              <div
                style={{
                  width: 42,
                  height: 42,
                  borderRadius: 10,
                  background: 'rgba(0, 229, 255, 0.12)',
                  border: '1.5px solid var(--accent)',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  color: 'var(--accent)',
                  flexShrink: 0,
                  boxShadow: '0 0 14px rgba(0, 229, 255, 0.25)',
                }}
              >
                <BookOpen size={20} strokeWidth={2} />
              </div>
              <div>
                <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--ink)', letterSpacing: '0.01em' }}>
                  Physics Engine &amp; Architecture Documentation
                </div>
                <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 2, lineHeight: 1.4 }}>
                  Coupled nonlinear RK45 state-space ODEs, mathematical fault models (ITSC, BRB, eccentricity), analytical MCSA Welch PSD, 4-node LPTN, and peer-reviewed research papers.
                </div>
              </div>
            </div>
            {onOpenDocs && (
              <button
                type="button"
                className="btn btn-primary"
                onClick={() => {
                  onClose()
                  onOpenDocs()
                }}
                style={{
                  fontSize: 12,
                  padding: '8px 14px',
                  display: 'flex',
                  alignItems: 'center',
                  gap: 6,
                  flexShrink: 0,
                  whiteSpace: 'nowrap',
                }}
                data-testid="profile-open-docs-btn"
                title="Open comprehensive scientific and architecture documentation"
              >
                <BookOpen size={14} />
                <span>Open Docs</span>
              </button>
            )}
          </section>

          {/* Card 3: Live Database Connection Status */}
          <section className="card" style={{ padding: '18px 20px' }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 14 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <Database size={16} style={{ color: 'var(--accent)' }} />
                <h3 style={{ fontSize: 13, fontWeight: 600, color: 'var(--ink)', margin: 0, textTransform: 'uppercase', letterSpacing: '0.04em' }}>
                  Live Database Connectivity Status
                </h3>
              </div>
              <button
                type="button"
                className="btn"
                onClick={() => { fetchStatus() }}
                disabled={loadingStatus}
                style={{ padding: '4px 10px', fontSize: 11, display: 'flex', alignItems: 'center', gap: 6 }}
                title="Ping database connection now"
              >
                <RefreshCw size={12} style={{ animation: loadingStatus ? 'login-spin 900ms linear infinite' : 'none' }} />
                <span>{loadingStatus ? 'Checking…' : 'Ping / Refresh'}</span>
              </button>
            </div>

            {/* Status Indicator Banner */}
            <div
              style={{
                padding: '12px 16px',
                borderRadius: 'var(--corner-md)',
                background: isConnected ? 'rgba(16, 185, 129, 0.08)' : 'rgba(239, 68, 68, 0.08)',
                border: `1px solid ${isConnected ? 'rgba(16, 185, 129, 0.3)' : 'rgba(239, 68, 68, 0.3)'}`,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                marginBottom: 16,
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                {isConnected ? (
                  <CheckCircle2 size={18} style={{ color: 'var(--good)' }} />
                ) : (
                  <AlertTriangle size={18} style={{ color: 'var(--critical)' }} />
                )}
                <div>
                  <div style={{ fontSize: 13, fontWeight: 700, color: isConnected ? 'var(--good)' : 'var(--critical)' }}>
                    {isConnected ? 'DATABASE CONNECTED (ONLINE)' : 'DATABASE DISCONNECTED (OFFLINE)'}
                  </div>
                  <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 2 }}>
                    {isConnected
                      ? `Active Engine: ${dbStatus?.engine ?? 'SQLAlchemy'} · Latency: ${dbStatus?.latency_ms ?? '—'} ms`
                      : (dbStatus?.error ?? statusError ?? 'Database link unreachable. Check connection parameters below.')}
                  </div>
                </div>
              </div>
              {isConnected && (
                <div className="live-pill" style={{ borderColor: 'rgba(56, 138, 102, 0.35)' }}>
                  <span className="live-dot" style={{ background: 'var(--good)', boxShadow: '0 0 6px var(--good)' }} />
                  <span style={{ color: 'var(--good)' }}>HEALTHY</span>
                </div>
              )}
            </div>

            {/* Detailed Parameters Grid */}
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(130px, 1fr))', gap: 10 }}>
              <div style={{ background: 'var(--surface-hover)', padding: '8px 12px', borderRadius: 'var(--corner-sm)', border: '1px solid var(--border-subtle)' }}>
                <span className="eyebrow" style={{ fontSize: 9 }}>DIALECT / ENGINE</span>
                <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--ink)', marginTop: 2, textTransform: 'uppercase' }}>
                  {dbStatus?.dialect ?? '—'}
                </div>
              </div>
              <div style={{ background: 'var(--surface-hover)', padding: '8px 12px', borderRadius: 'var(--corner-sm)', border: '1px solid var(--border-subtle)' }}>
                <span className="eyebrow" style={{ fontSize: 9 }}>DATABASE</span>
                <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--ink)', marginTop: 2 }}>
                  {dbStatus?.database ?? '—'}
                </div>
              </div>
              <div style={{ background: 'var(--surface-hover)', padding: '8px 12px', borderRadius: 'var(--corner-sm)', border: '1px solid var(--border-subtle)' }}>
                <span className="eyebrow" style={{ fontSize: 9 }}>USER</span>
                <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--ink)', marginTop: 2 }}>
                  {dbStatus?.user ?? '—'}
                </div>
              </div>
              <div style={{ background: 'var(--surface-hover)', padding: '8px 12px', borderRadius: 'var(--corner-sm)', border: '1px solid var(--border-subtle)' }}>
                <span className="eyebrow" style={{ fontSize: 9 }}>HOST &amp; PORT</span>
                <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--ink)', marginTop: 2 }}>
                  {dbStatus?.host ?? '—'}{dbStatus?.port ? `:${dbStatus.port}` : ''}
                </div>
              </div>
            </div>

            {/* Tables schema info */}
            {dbStatus && dbStatus.tables.length > 0 && (
              <div style={{ marginTop: 12, paddingTop: 10, borderTop: '1px solid var(--border-subtle)' }}>
                <span className="eyebrow" style={{ fontSize: 10, display: 'block', marginBottom: 6 }}>
                  PERSISTENCE SCHEMA TABLES ({dbStatus.tables.length})
                </span>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                  {dbStatus.tables.map((t) => (
                    <span
                      key={t}
                      style={{
                        padding: '2px 8px',
                        background: 'rgba(255, 255, 255, 0.04)',
                        border: '1px solid var(--border-subtle)',
                        borderRadius: 'var(--corner-sm)',
                        fontSize: 11,
                        color: 'var(--ink-2)',
                        fontFamily: 'var(--font-mono)',
                      }}
                    >
                      {t}
                    </span>
                  ))}
                </div>
              </div>
            )}
          </section>

          {/* Card 3: Configure MySQL Password & Connection */}
          <section className="card" style={{ padding: '18px 20px' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
              <KeyRound size={16} style={{ color: 'var(--accent)' }} />
              <h3 style={{ fontSize: 13, fontWeight: 600, color: 'var(--ink)', margin: 0, textTransform: 'uppercase', letterSpacing: '0.04em' }}>
                Add MySQL Password &amp; Connection
              </h3>
            </div>
            <p style={{ fontSize: 12, color: 'var(--muted)', margin: '0 0 14px 0', lineHeight: 1.45 }}>
              Enter or update your MySQL credentials to test or switch connection to an enterprise MySQL server (local or Dockerized).
            </p>

            {/* Connection Test Feedback Banner */}
            {testResult && (
              <div
                style={{
                  padding: '10px 14px',
                  borderRadius: 'var(--corner-md)',
                  background: testResult.success ? 'rgba(16, 185, 129, 0.08)' : 'rgba(239, 68, 68, 0.08)',
                  border: `1px solid ${testResult.success ? 'rgba(16, 185, 129, 0.3)' : 'rgba(239, 68, 68, 0.3)'}`,
                  display: 'flex',
                  alignItems: 'flex-start',
                  gap: 10,
                  marginBottom: 14,
                  fontSize: 12,
                  color: testResult.success ? 'var(--good)' : 'var(--critical)',
                  lineHeight: 1.4,
                }}
              >
                {testResult.success ? (
                  <CheckCircle2 size={16} style={{ flexShrink: 0, marginTop: 1 }} />
                ) : (
                  <AlertTriangle size={16} style={{ flexShrink: 0, marginTop: 1 }} />
                )}
                <div>
                  <div style={{ fontWeight: 600 }}>{testResult.message}</div>
                  {testResult.applied && (
                    <div style={{ fontSize: 11, color: 'var(--ink-2)', marginTop: 2 }}>
                      Runtime engine updated. Future telemetry writes will route through this MySQL database.
                    </div>
                  )}
                </div>
              </div>
            )}

            {/* Inputs Grid */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
              {/* MySQL Password Input with Show/Hide Toggle */}
              <div>
                <label style={{ display: 'block', marginBottom: 4, fontSize: 11, fontWeight: 600, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: '0.04em' }}>
                  MySQL Password <span style={{ color: 'var(--accent)' }}>*</span>
                </label>
                <div style={{ position: 'relative', display: 'flex', alignItems: 'center' }}>
                  <Lock size={15} style={{ position: 'absolute', left: 12, color: 'var(--muted)', pointerEvents: 'none' }} />
                  <input
                    type={showPassword ? 'text' : 'password'}
                    className="input"
                    value={mysqlPassword}
                    onChange={(e) => setMysqlPassword(e.target.value)}
                    placeholder="Enter MySQL password (e.g. change-me)"
                    style={{ paddingLeft: 34, paddingRight: 40, width: '100%', fontSize: 13, background: 'var(--page)' }}
                    autoComplete="current-password"
                  />
                  <button
                    type="button"
                    onClick={() => setShowPassword(!showPassword)}
                    style={{
                      position: 'absolute',
                      right: 10,
                      background: 'none',
                      border: 'none',
                      color: 'var(--muted)',
                      cursor: 'pointer',
                      padding: 4,
                      display: 'flex',
                      alignItems: 'center',
                    }}
                    title={showPassword ? 'Hide password' : 'Show password'}
                    aria-label={showPassword ? 'Hide password' : 'Show password'}
                  >
                    {showPassword ? <EyeOff size={16} /> : <Eye size={16} />}
                  </button>
                </div>
              </div>

              {/* Host, Port, User, Database Row */}
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(130px, 1fr))', gap: 10 }}>
                <div>
                  <label style={{ display: 'block', marginBottom: 4, fontSize: 11, fontWeight: 600, color: 'var(--muted)', textTransform: 'uppercase' }}>
                    MySQL Host
                  </label>
                  <input
                    type="text"
                    className="input"
                    value={mysqlHost}
                    onChange={(e) => setMysqlHost(e.target.value)}
                    placeholder="localhost"
                    style={{ fontSize: 13, background: 'var(--page)' }}
                  />
                </div>
                <div>
                  <label style={{ display: 'block', marginBottom: 4, fontSize: 11, fontWeight: 600, color: 'var(--muted)', textTransform: 'uppercase' }}>
                    Port
                  </label>
                  <input
                    type="number"
                    className="input"
                    value={mysqlPort}
                    onChange={(e) => setMysqlPort(Number(e.target.value))}
                    placeholder="3306"
                    style={{ fontSize: 13, background: 'var(--page)' }}
                  />
                </div>
                <div>
                  <label style={{ display: 'block', marginBottom: 4, fontSize: 11, fontWeight: 600, color: 'var(--muted)', textTransform: 'uppercase' }}>
                    User
                  </label>
                  <input
                    type="text"
                    className="input"
                    value={mysqlUser}
                    onChange={(e) => setMysqlUser(e.target.value)}
                    placeholder="dt"
                    style={{ fontSize: 13, background: 'var(--page)' }}
                  />
                </div>
                <div>
                  <label style={{ display: 'block', marginBottom: 4, fontSize: 11, fontWeight: 600, color: 'var(--muted)', textTransform: 'uppercase' }}>
                    Database
                  </label>
                  <input
                    type="text"
                    className="input"
                    value={mysqlDatabase}
                    onChange={(e) => setMysqlDatabase(e.target.value)}
                    placeholder="digital_twin"
                    style={{ fontSize: 13, background: 'var(--page)' }}
                  />
                </div>
              </div>

              {/* Action Buttons */}
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'flex-end', gap: 10, marginTop: 6 }}>
                <button
                  type="button"
                  className="btn"
                  onClick={() => handleTestConnection(false)}
                  disabled={testing || applying || !mysqlPassword.trim()}
                  style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12 }}
                >
                  {testing ? (
                    <Loader2 size={14} style={{ animation: 'login-spin 900ms linear infinite' }} />
                  ) : (
                    <Activity size={14} />
                  )}
                  <span>{testing ? 'Testing Link…' : 'Test Connection'}</span>
                </button>
                <button
                  type="button"
                  className="btn btn-primary"
                  onClick={() => handleTestConnection(true)}
                  disabled={testing || applying || !mysqlPassword.trim()}
                  style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12 }}
                >
                  {applying ? (
                    <Loader2 size={14} style={{ animation: 'login-spin 900ms linear infinite' }} />
                  ) : (
                    <Server size={14} />
                  )}
                  <span>{applying ? 'Applying…' : 'Save & Connect MySQL'}</span>
                </button>
              </div>

              <div style={{ fontSize: 11, color: 'var(--muted)', display: 'flex', alignItems: 'center', gap: 6, marginTop: 4 }}>
                <HardDrive size={13} style={{ flexShrink: 0 }} />
                <span>
                  Tip: When running the local stack via Docker Compose, use user <code>dt</code> with host <code>localhost</code> and your password from <code>compose.yaml</code>.
                </span>
              </div>
            </div>
          </section>
        </div>

        {/* Fixed Modal Footer */}
        <footer className="modal-footer" style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          {onOpenDocs ? (
            <button
              type="button"
              className="btn"
              onClick={() => {
                onClose()
                onOpenDocs()
              }}
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: 6,
                fontSize: 12,
                color: 'var(--accent)',
                borderColor: 'rgba(0, 229, 255, 0.35)',
                background: 'rgba(0, 229, 255, 0.08)',
              }}
              data-testid="profile-footer-docs-btn"
            >
              <BookOpen size={14} />
              <span>Physics &amp; Architecture Docs</span>
            </button>
          ) : <div />}
          <button type="button" className="btn" onClick={onClose}>
            Close
          </button>
        </footer>
      </div>
    </div>,
    document.body
  )
}

import { useState, type FormEvent } from 'react'
import { useAuth } from '../auth/AuthContext'

export function LoginForm() {
  const { login } = useAuth()
  const [u, setU] = useState('')
  const [p, setP] = useState('')
  const [err, setErr] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setErr(null)
    setLoading(true)
    try {
      await login(u, p)
    } catch (ex) {
      setErr((ex as Error).message)
    } finally {
      setLoading(false)
    }
  }

  const fillDemo = (user: string, pass: string) => {
    setU(user)
    setP(pass)
    setErr(null)
  }

  return (
    <main className="min-h-screen grid place-items-center px-4 py-8 relative overflow-hidden bg-[var(--page)] text-[var(--foreground)]">
      {/* Background industrial grid overlay */}
      <div 
        className="absolute inset-0 opacity-10 pointer-events-none"
        style={{
          backgroundImage: `radial-gradient(circle at 1px 1px, var(--border-hover) 1px, transparent 0)`,
          backgroundSize: '24px 24px'
        }}
      />

      <div className="w-full max-w-md relative z-10">
        {/* Brand Emblem & Header */}
        <div className="text-center mb-8">
          <div className="inline-flex items-center justify-center w-14 h-14 rounded-xl bg-[var(--surface-raised)] border border-[var(--border)] text-[var(--foreground)] mb-4">
            <svg className="w-7 h-7 text-[var(--accent)]" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75">
              <circle cx="12" cy="12" r="9" strokeDasharray="3 3" />
              <circle cx="12" cy="12" r="4" />
              <path d="M12 2v3M12 19v3M2 12h3M19 12h3M4.93 4.93l2.12 2.12M16.95 16.95l2.12 2.12M4.93 19.07l2.12-2.12M16.95 7.05l2.12-2.12" />
            </svg>
          </div>
          <h1 className="text-xl font-bold tracking-tight text-[var(--foreground)] uppercase">
            AC Motor Digital Twin
          </h1>
          <p className="text-xs text-[var(--muted)] mt-1 font-mono tracking-wide">
            Supervisory Control &amp; Fault Diagnostic Cockpit
          </p>
        </div>

        {/* Login Card */}
        <div className="card p-6 sm:p-8 bg-[var(--surface)] border border-[var(--border)] rounded-xl">
          <div className="flex items-center justify-between pb-4 mb-5 border-b border-[var(--border)]">
            <span className="text-xs font-semibold text-[var(--foreground)] uppercase tracking-wider flex items-center gap-2">
              <span className="w-2 h-2 rounded-full bg-emerald-400" />
              Operator Authentication
            </span>
            <span className="text-[10px] font-mono num text-[var(--muted)] bg-[var(--surface-raised)] px-2 py-0.5 rounded border border-[var(--border)]">
              SADA v2.4
            </span>
          </div>

          <form onSubmit={submit} className="grid gap-4">
            <div className="grid gap-1.5">
              <label className="text-xs font-medium text-[var(--muted)]" htmlFor="login-username">
                Operator Username
              </label>
              <div className="relative">
                <input
                  id="login-username"
                  className="input w-full pl-9 pr-3 py-2 text-sm font-mono text-[var(--foreground)]"
                  value={u}
                  onChange={(e) => setU(e.target.value)}
                  autoComplete="username"
                  placeholder="e.g. admin"
                  required
                />
                <svg className="w-4 h-4 text-[var(--muted)] absolute left-3 top-2.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z" />
                </svg>
              </div>
            </div>

            <div className="grid gap-1.5">
              <label className="text-xs font-medium text-[var(--muted)]" htmlFor="login-password">
                Security Password
              </label>
              <div className="relative">
                <input
                  id="login-password"
                  className="input w-full pl-9 pr-3 py-2 text-sm font-mono text-[var(--foreground)]"
                  type="password"
                  value={p}
                  onChange={(e) => setP(e.target.value)}
                  autoComplete="current-password"
                  placeholder="••••••••••••"
                  required
                />
                <svg className="w-4 h-4 text-[var(--muted)] absolute left-3 top-2.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z" />
                </svg>
              </div>
            </div>

            {err && (
              <div
                className="p-3 rounded-lg text-xs font-medium bg-rose-500/10 border border-rose-500/30 text-rose-400 flex items-center gap-2"
                role="alert"
              >
                <svg className="w-4 h-4 shrink-0 text-rose-400" viewBox="0 0 20 20" fill="currentColor">
                  <path fillRule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7 4a1 1 0 11-2 0 1 1 0 012 0zm-1-9a1 1 0 00-1 1v4a1 1 0 102 0V6a1 1 0 00-1-1z" clipRule="evenodd" />
                </svg>
                <span>{err}</span>
              </div>
            )}

            <button
              className="btn btn-primary w-full py-2.5 text-sm font-semibold tracking-wide flex items-center justify-center gap-2 mt-1"
              type="submit"
              disabled={loading}
            >
              {loading ? (
                <>
                  <svg className="animate-spin h-4 w-4 text-white" viewBox="0 0 24 24">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none" />
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                  </svg>
                  <span>Authenticating…</span>
                </>
              ) : (
                <>
                  <span>Sign In to Cockpit</span>
                  <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M14 5l7 7m0 0l-7 7m7-7H3" />
                  </svg>
                </>
              )}
            </button>
          </form>

          {/* Quick-fill credentials helper */}
          <div className="mt-6 pt-4 border-t border-[var(--border)]">
            <span className="text-[11px] font-mono text-[var(--muted)] block mb-2">
              Default Environment Credentials:
            </span>
            <div className="flex gap-2">
              <button
                type="button"
                onClick={() => fillDemo('admin', 'admin-pass-123')}
                className="btn text-xs py-1 px-2.5 bg-[var(--surface-raised)] hover:bg-[var(--surface-hover)] text-[var(--accent)] border border-[var(--border)] hover:border-[var(--border-hover)] transition-all font-mono"
              >
                Admin Quick-Fill
              </button>
            </div>
          </div>
        </div>

        {/* Footer telemetry status */}
        <div className="text-center mt-6 text-[11px] font-mono text-[var(--muted)] flex items-center justify-center gap-3">
          <span className="inline-flex items-center gap-1.5">
            <span className="w-1.5 h-1.5 rounded-full bg-emerald-500" /> API Gateway <span className="num">:8000</span>
          </span>
          <span>·</span>
          <span>FastAPI + SQLite WAL</span>
          <span>·</span>
          <span>WebSocket Stream</span>
        </div>
      </div>
    </main>
  )
}


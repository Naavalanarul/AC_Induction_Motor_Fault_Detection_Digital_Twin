import { useState, type KeyboardEvent } from 'react'
import { useAuth } from '../auth/AuthContext'
import { Box, User, Lock, Loader2, ShieldCheck } from 'lucide-react'

export function LoginForm() {
  const { login: doLogin } = useAuth()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const canSubmit = username.trim().length > 0 && password.length > 0 && !busy

  const handleLogin = async () => {
    if (!canSubmit) return
    setBusy(true)
    setError('')
    try {
      await doLogin(username, password)
    } catch (e) {
      setError((e as Error).message || 'Authentication failed')
    } finally {
      setBusy(false)
    }
  }

  const handleKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') handleLogin()
  }

  return (
    <main className="login-shell">
      <div className="login-grid-backdrop" />
      <header className="login-brand">
        <div className="brand-node">
          <Box size={18} strokeWidth={1.5} />
        </div>
        <div className="brand-copy">
          <span className="brand-name">TWIN-CORE</span>
          <span className="brand-asset">INDUSTRIAL INTELLIGENCE</span>
        </div>
      </header>

      <section className="login-layout" aria-label="Twin Core authentication">
        <div className="login-card glass-card">
          <div className="login-card__head">
            <span className="eyebrow">OPERATOR ACCESS</span>
            <div className="login-title" role="heading" aria-level={2}>Welcome back</div>
            <div className="login-subtitle">Sign in with your plant network credentials.</div>
          </div>
          <div className="login-fields">
            <label className="login-field-group">
              <span className="login-field-label">Username</span>
              <div className="login-input-wrap">
                <User size={16} className="login-input-icon" />
                <input
                  className="login-input"
                  type="text"
                  placeholder="Enter operator username"
                  autoComplete="username"
                  aria-label="Username"
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                />
              </div>
            </label>
            <label className="login-field-group">
              <span className="login-field-label">Password</span>
              <div className="login-input-wrap">
                <Lock size={16} className="login-input-icon" />
                <input
                  className="login-input"
                  type="password"
                  placeholder="Enter password"
                  autoComplete="current-password"
                  aria-label="Password"
                  value={password}
                  onKeyDown={handleKeyDown}
                  onChange={(e) => setPassword(e.target.value)}
                />
              </div>
            </label>
          </div>
          {error && (
            <p className="login-error" role="alert">{error}</p>
          )}
          <button
            className="login-submit"
            disabled={!canSubmit}
            onClick={handleLogin}
          >
            {busy ? <Loader2 size={16} className="login-spinner" /> : <ShieldCheck size={16} />}
            <span>{busy ? 'Connecting...' : 'Sign in'}</span>
          </button>
          <div className="login-security">
            <Lock size={13} />
            <span>TLS secured · plant network only</span>
          </div>
        </div>
      </section>
    </main>
  )
}

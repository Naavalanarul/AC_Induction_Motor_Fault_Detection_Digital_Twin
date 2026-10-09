import { useState, useRef, useEffect, useCallback, type KeyboardEvent, type SyntheticEvent } from 'react'
import { useAuth } from '../auth/AuthContext'
import { Box, User, Lock, Loader2, ShieldCheck, Eye, EyeOff } from 'lucide-react'

export type LoginMode = 'live' | 'static'

export interface LoginFormProps {
  onLoginSuccess?: (mode: LoginMode) => void
  initialMode?: LoginMode
}

export function LoginForm({ onLoginSuccess, initialMode = 'live' }: LoginFormProps) {
  const { login: doLogin } = useAuth()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [mode, setMode] = useState<LoginMode>(initialMode)
  const [showPassword, setShowPassword] = useState(false)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const passwordInputRef = useRef<HTMLInputElement>(null)

  const canSubmit = username.trim().length > 0 && password.length > 0 && !busy

  const handleLogin = async () => {
    if (!canSubmit) return
    setBusy(true)
    setError('')
    try {
      await doLogin(username, password)
      onLoginSuccess?.(mode)
    } catch (e) {
      setError((e as Error).message || 'Authentication failed')
    } finally {
      setBusy(false)
    }
  }

  const handleKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') handleLogin()
  }

  const revealPassword = (e?: SyntheticEvent) => {
    if (e) e.preventDefault()
    const input = passwordInputRef.current
    const hadFocus = document.activeElement === input
    const start = input?.selectionStart
    const end = input?.selectionEnd
    setShowPassword(true)
    if (hadFocus && input && typeof start === 'number' && typeof end === 'number') {
      requestAnimationFrame(() => {
        input.focus()
        input.setSelectionRange(start, end)
      })
    }
  }

  const hidePassword = useCallback(() => {
    if (!showPassword) return
    const input = passwordInputRef.current
    const hadFocus = document.activeElement === input
    const start = input?.selectionStart
    const end = input?.selectionEnd
    setShowPassword(false)
    if (hadFocus && input && typeof start === 'number' && typeof end === 'number') {
      requestAnimationFrame(() => {
        input.focus()
        input.setSelectionRange(start, end)
      })
    }
  }, [showPassword])

  useEffect(() => {
    const handleVisibilityChange = () => {
      if (document.hidden) hidePassword()
    }
    document.addEventListener('visibilitychange', handleVisibilityChange)
    return () => {
      document.removeEventListener('visibilitychange', handleVisibilityChange)
    }
  }, [hidePassword])

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
                  onKeyDown={handleKeyDown}
                />
              </div>
            </label>
            <label className="login-field-group">
              <span className="login-field-label">Password</span>
              <div className="login-input-wrap">
                <Lock size={16} className="login-input-icon" />
                <input
                  ref={passwordInputRef}
                  className="login-input"
                  type={showPassword ? 'text' : 'password'}
                  placeholder="Enter password"
                  autoComplete="current-password"
                  aria-label="Password"
                  value={password}
                  onKeyDown={handleKeyDown}
                  onBlur={hidePassword}
                  onChange={(e) => setPassword(e.target.value)}
                  style={{ paddingRight: 38 }}
                />
                <button
                  type="button"
                  className="login-eye-btn"
                  aria-label="Show password (hold)"
                  aria-pressed={showPassword}
                  title="Hold to reveal password"
                  tabIndex={0}
                  onPointerDown={revealPassword}
                  onPointerUp={hidePassword}
                  onPointerCancel={hidePassword}
                  onPointerLeave={hidePassword}
                  onKeyDown={(e) => {
                    if (e.key === ' ' || e.key === 'Enter') {
                      e.preventDefault()
                      revealPassword()
                    }
                  }}
                  onKeyUp={(e) => {
                    if (e.key === ' ' || e.key === 'Enter') {
                      e.preventDefault()
                      hidePassword()
                    }
                  }}
                >
                  {showPassword ? <EyeOff size={16} /> : <Eye size={16} />}
                </button>
              </div>
            </label>
          </div>

          <div className="login-mode-group">
            <span className="login-field-label">Session Mode</span>
            <div className="login-mode-selector" role="radiogroup" aria-label="Target session mode">
              <button
                type="button"
                role="radio"
                aria-checked={mode === 'live'}
                className={`login-mode-btn ${mode === 'live' ? 'is-active' : ''}`}
                onClick={() => setMode('live')}
              >
                Live twin
              </button>
              <button
                type="button"
                role="radio"
                aria-checked={mode === 'static'}
                className={`login-mode-btn ${mode === 'static' ? 'is-active' : ''}`}
                onClick={() => setMode('static')}
              >
                Static analysis
              </button>
            </div>
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

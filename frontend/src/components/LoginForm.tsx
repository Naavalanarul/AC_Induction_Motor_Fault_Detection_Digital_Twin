import { useState, type FormEvent } from 'react'
import { useAuth } from '../auth/AuthContext'

export function LoginForm() {
  const { login } = useAuth()
  const [u, setU] = useState('')
  const [p, setP] = useState('')
  const [err, setErr] = useState<string | null>(null)
  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setErr(null)
    try {
      await login(u, p)
    } catch (ex) {
      setErr((ex as Error).message)
    }
  }
  return (
    <main className="min-h-screen grid place-items-center px-4">
      <form onSubmit={submit} className="card w-full max-w-sm grid gap-3">
        <h1 className="text-lg font-semibold">Motor Digital Twin</h1>
        <label className="grid gap-1 text-sm">Username
          <input className="input" value={u} onChange={(e) => setU(e.target.value)} autoComplete="username" required /></label>
        <label className="grid gap-1 text-sm">Password
          <input className="input" type="password" value={p} onChange={(e) => setP(e.target.value)} autoComplete="current-password" required /></label>
        {err && <p className="text-sm" role="alert" style={{ color: 'var(--critical)' }}>{err}</p>}
        <button className="btn btn-primary" type="submit">Sign in</button>
      </form>
    </main>
  )
}

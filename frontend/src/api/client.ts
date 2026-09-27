// Thin fetch wrapper: attaches the access token, refreshes once on 401.

const API = '/api/v1'
const KEY = 'dt.auth'

export type Session = { access_token: string; refresh_token: string; role: string; username: string }

export function loadSession(): Session | null {
  try {
    const raw = sessionStorage.getItem(KEY)
    return raw ? (JSON.parse(raw) as Session) : null
  } catch {
    return null
  }
}

export function saveSession(s: Session | null) {
  try {
    if (s) sessionStorage.setItem(KEY, JSON.stringify(s))
    else sessionStorage.removeItem(KEY)
  } catch {
    /* storage unavailable: session lives in memory only */
  }
}

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

let onAuthLost: () => void = () => {}
export function setAuthLostHandler(fn: () => void) {
  onAuthLost = fn
}

export function notifyAuthLost() {
  saveSession(null)
  onAuthLost()
}

let activeRefresh: Promise<boolean> | null = null

export async function refresh(): Promise<boolean> {
  if (activeRefresh) return activeRefresh
  activeRefresh = (async () => {
    const s = loadSession()
    if (!s || !s.refresh_token) {
      notifyAuthLost()
      return false
    }
    try {
      const r = await fetch(`${API}/auth/refresh`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ refresh_token: s.refresh_token }),
      })
      if (!r.ok) {
        notifyAuthLost()
        return false
      }
      const fresh = (await r.json()) as Session
      saveSession(fresh)
      return true
    } catch {
      return false
    } finally {
      activeRefresh = null
    }
  })()
  return activeRefresh
}

export function isTokenExpired(token: string, skewSeconds = 30): boolean {
  try {
    const parts = token.split('.')
    if (parts.length !== 3) return false
    const payload = JSON.parse(atob(parts[1].replace(/-/g, '+').replace(/_/g, '/')))
    if (typeof payload.exp !== 'number') return false
    return payload.exp * 1000 <= Date.now() + skewSeconds * 1000
  } catch {
    return false
  }
}

export async function getValidToken(): Promise<string | null> {
  const s = loadSession()
  if (!s) return null
  if (isTokenExpired(s.access_token)) {
    const ok = await refresh()
    if (!ok) return null
    return loadSession()?.access_token ?? null
  }
  return s.access_token
}

export async function api<T>(path: string, init: RequestInit = {}, retry = true): Promise<T> {
  let s = loadSession()
  if (s && isTokenExpired(s.access_token)) {
    await refresh()
    s = loadSession()
  }
  const headers = new Headers(init.headers)
  if (init.body) headers.set('Content-Type', 'application/json')
  if (s) headers.set('Authorization', `Bearer ${s.access_token}`)
  const r = await fetch(`${API}${path}`, { ...init, headers })
  if (r.status === 401 && retry && s) {
    if (await refresh()) return api<T>(path, init, false)
    notifyAuthLost()
  }
  if (!r.ok) {
    let detail = r.statusText
    try {
      const body = await r.json()
      detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail)
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(r.status, detail)
  }
  return (await r.json()) as T
}

export async function login(username: string, password: string): Promise<Session> {
  const r = await fetch(`${API}/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
  })
  if (!r.ok) throw new ApiError(r.status, r.status === 429 ? 'Too many attempts, wait a minute' : 'Invalid credentials')
  const s = (await r.json()) as Session
  saveSession(s)
  return s
}

export const newIdempotencyKey = () =>
  typeof crypto !== 'undefined' && 'randomUUID' in crypto
    ? crypto.randomUUID()
    : `${Date.now()}-${Math.random().toString(16).slice(2)}`

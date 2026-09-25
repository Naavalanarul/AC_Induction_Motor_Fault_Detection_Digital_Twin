import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { login as apiLogin, loadSession, saveSession, setAuthLostHandler, type Session } from '../api/client'
import type { Role } from '../api/types'

type AuthValue = {
  session: Session | null
  login: (u: string, p: string) => Promise<void>
  logout: () => void
  can: (role: Role) => boolean
}

const RANK: Record<Role, number> = { viewer: 0, operator: 1, admin: 2 }
const AuthContext = createContext<AuthValue | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null>(() => loadSession())

  useEffect(() => setAuthLostHandler(() => setSession(null)), [])

  const login = useCallback(async (u: string, p: string) => {
    setSession(await apiLogin(u, p))
  }, [])
  const logout = useCallback(() => {
    saveSession(null)
    setSession(null)
  }, [])
  const can = useCallback(
    (role: Role) => !!session && (RANK[session.role as Role] ?? -1) >= RANK[role],
    [session],
  )
  const value = useMemo(() => ({ session, login, logout, can }), [session, login, logout, can])
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

// eslint-disable-next-line react-refresh/only-export-components
export function useAuth() {
  const v = useContext(AuthContext)
  if (!v) throw new Error('useAuth outside AuthProvider')
  return v
}

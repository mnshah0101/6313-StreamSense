import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { ApiError, api, errorMessage, setSignedOutHandler } from './api'
import { roleAtLeast, type Role, type User } from './data/types'

/**
 * Who is signed in. GET /auth/me on load decides between the app and the sign-in page; any later
 * 401 from the API (expired / revoked session, disabled account) signs out in place, so the URL
 * stays and the user lands back on the same page after signing in.
 */
type State =
  | { status: 'loading' }
  | { status: 'error'; message: string }
  | { status: 'signedOut'; notice?: string }
  | { status: 'signedIn'; user: User }

interface Auth {
  state: State
  user: User | null
  /** True when the signed-in role is at least `role`. */
  can: (role: Role) => boolean
  login: (email: string, password: string) => Promise<void>
  logout: () => Promise<void>
  /** Show the sign-in page with a notice (e.g. after a password change revoked the session). */
  signedOut: (notice?: string) => void
  retry: () => void
}

const Ctx = createContext<Auth | null>(null)

const NOTICES: Record<string, string> = {
  session_expired: 'Session expired. Sign in again.',
  account_disabled: 'This account is disabled.',
  not_signed_in: 'Signed out. Sign in again.',
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<State>({ status: 'loading' })

  const check = useCallback(() => {
    setState({ status: 'loading' })
    api.me()
      .then((user) => setState({ status: 'signedIn', user }))
      .catch((e) => {
        if (e instanceof ApiError && e.status === 401 && e.code !== 'unauthorized') {
          setState({ status: 'signedOut', notice: e.code === 'account_disabled' ? NOTICES.account_disabled : undefined })
        } else setState({ status: 'error', message: errorMessage(e) })
      })
  }, [])

  useEffect(() => { check() }, [check])

  // Any API call that finds the session gone drops back to the sign-in page.
  useEffect(() => {
    setSignedOutHandler((code) => {
      setState((s) => (s.status === 'signedIn' ? { status: 'signedOut', notice: NOTICES[code] } : s))
    })
    return () => setSignedOutHandler(null)
  }, [])

  const login = useCallback(async (email: string, password: string) => {
    const user = await api.login(email, password)
    setState({ status: 'signedIn', user })
  }, [])
  const logout = useCallback(async () => {
    try { await api.logout() } catch { /* signed out locally either way */ }
    setState({ status: 'signedOut' })
  }, [])
  const signedOut = useCallback((notice?: string) => setState({ status: 'signedOut', notice }), [])

  const user = state.status === 'signedIn' ? state.user : null
  const value = useMemo<Auth>(() => ({
    state, user, can: (role) => roleAtLeast(user?.role, role), login, logout, signedOut, retry: check,
  }), [state, user, login, logout, signedOut, check])
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}

export function useAuth(): Auth {
  const a = useContext(Ctx)
  if (!a) throw new Error('useAuth outside provider')
  return a
}

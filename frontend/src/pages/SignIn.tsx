import { useState, type FormEvent, type ReactNode } from 'react'
import { useAuth } from '../auth'
import { ApiError, errorMessage } from '../api'
import { Logo } from '../components/Nav'
import { btnPrimary, cardCls, inputCls } from '../components/ui'

export default function SignIn({ notice }: { notice?: string }) {
  const { login } = useAuth()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    if (busy) return
    setBusy(true); setErr(null)
    try {
      await login(email.trim(), password)
    } catch (e) {
      setErr(e instanceof ApiError && e.status === 401 ? 'Wrong email or password.' : errorMessage(e))
      setBusy(false)
    }
  }

  return (
    <AuthScreen>
      <form onSubmit={submit} className={`${cardCls} flex w-80 flex-col gap-3`}>
        {notice && !err && <div className="text-xs text-text-secondary">{notice}</div>}
        <label className="flex flex-col gap-1">
          <span className="text-[10px] uppercase tracking-wide text-text-muted">Email</span>
          <input type="text" autoComplete="username" autoCapitalize="none" spellCheck={false} autoFocus required value={email} onChange={(e) => setEmail(e.target.value)} className={inputCls} />
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-[10px] uppercase tracking-wide text-text-muted">Password</span>
          <input type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} className={inputCls} />
        </label>
        {err && <div className="text-xs text-red-400" role="alert">{err}</div>}
        <button type="submit" className={`${btnPrimary} mt-1`} disabled={busy || !email.trim() || !password}>{busy ? 'Signing in…' : 'Sign in'}</button>
      </form>
    </AuthScreen>
  )
}

/** Centered logo + content, for sign-in and the auth loading / error states. */
export function AuthScreen({ children }: { children: ReactNode }) {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-6 px-6">
      <Logo />
      {children}
    </div>
  )
}

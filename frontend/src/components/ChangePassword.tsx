import { useEffect, useState, type FormEvent } from 'react'
import { api, errorMessage } from '../api'
import { useAuth } from '../auth'
import { btnGhost, btnPrimarySm, cardCls, inputCls } from './ui'

export const MIN_PASSWORD = 10

/** Modal: current + new password. Success revokes every session, so it ends at the sign-in page. */
export default function ChangePassword({ onClose }: { onClose: () => void }) {
  const { signedOut } = useAuth()
  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')
  const [repeat, setRepeat] = useState('')
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  useEffect(() => {
    const esc = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', esc)
    return () => document.removeEventListener('keydown', esc)
  }, [onClose])

  const problem = next.length < MIN_PASSWORD ? `At least ${MIN_PASSWORD} characters.` : next !== repeat ? 'Passwords do not match.' : null
  const submit = async (e: FormEvent) => {
    e.preventDefault()
    if (busy || problem || !current) return
    setBusy(true); setErr(null)
    try {
      await api.changePassword(current, next)
      signedOut('Password changed. Sign in again.')
    } catch (e) {
      setErr(errorMessage(e))
      setBusy(false)
    }
  }

  const field = (label: string, value: string, set: (v: string) => void, auto: string, autoFocus = false) => (
    <label className="flex flex-col gap-1">
      <span className="text-[10px] uppercase tracking-wide text-text-muted">{label}</span>
      <input type="password" autoComplete={auto} autoFocus={autoFocus} value={value} onChange={(e) => set(e.target.value)} className={inputCls} />
    </label>
  )
  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center bg-black/60" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose() }}>
      <form onSubmit={submit} role="dialog" aria-modal="true" aria-label="Change password" className={`${cardCls} flex w-80 flex-col gap-3`}>
        <h2 className="font-display text-base font-bold uppercase tracking-wide">Change password</h2>
        {field('Current', current, setCurrent, 'current-password', true)}
        {field('New', next, setNext, 'new-password')}
        {field('Repeat new', repeat, setRepeat, 'new-password')}
        {next && problem && <div className="text-[11px] text-text-muted">{problem}</div>}
        {err && <div className="text-xs text-red-400" role="alert">{err}</div>}
        <div className="flex gap-2">
          <button type="submit" className={btnPrimarySm} disabled={busy || !!problem || !current}>{busy ? 'Saving…' : 'Save'}</button>
          <button type="button" className={btnGhost} onClick={onClose}>Cancel</button>
        </div>
        <div className="text-[11px] text-text-muted">Signs you out everywhere.</div>
      </form>
    </div>
  )
}

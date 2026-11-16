import { useEffect, useState, type FormEvent } from 'react'
import { api, errorMessage } from '../api'
import { useAuth } from '../auth'
import { ROLES, type Role, type User } from '../data/types'
import { dateTimeLabel } from '../data/format'
import { MIN_PASSWORD } from '../components/ChangePassword'
import { Pill, btnGhost, btnGhostRow, btnPrimarySm, cardCls, inputCls } from '../components/ui'

/** Admin: accounts. The API is the authority (self-lockout, last admin); the UI only avoids the obvious. */
export default function Users() {
  const { user: me } = useAuth()
  const [users, setUsers] = useState<User[] | null>(null)
  const [loadErr, setLoadErr] = useState<string | null>(null)
  // Per-row error / busy / password-reset state.
  const [rowErr, setRowErr] = useState<Record<number, string>>({})
  const [rowOk, setRowOk] = useState<Record<number, string>>({})
  const [busy, setBusy] = useState<number | null>(null)
  const [resetting, setResetting] = useState<number | null>(null)
  const [newPw, setNewPw] = useState('')

  const load = () => api.listUsers().then((u) => { setUsers(u); setLoadErr(null) }).catch((e) => setLoadErr(errorMessage(e)))
  useEffect(() => { void load() }, [])

  const run = async (id: number, p: Promise<unknown>, ok?: string) => {
    setBusy(id)
    setRowErr(({ [id]: _, ...rest }) => rest)
    setRowOk(({ [id]: _, ...rest }) => rest)
    try {
      const r = await p
      if (r && typeof r === 'object' && 'id' in r) setUsers((prev) => prev?.map((u) => (u.id === id ? (r as User) : u)) ?? prev)
      if (ok) setRowOk((m) => ({ ...m, [id]: ok }))
      return true
    } catch (e) {
      setRowErr((m) => ({ ...m, [id]: errorMessage(e) }))
      void load() // show the server's state again (e.g. a role select reverted)
      return false
    } finally {
      setBusy(null)
    }
  }
  const submitReset = async (id: number) => {
    if (newPw.length < MIN_PASSWORD) return
    if (await run(id, api.resetPassword(id, newPw), 'Password reset')) { setResetting(null); setNewPw('') }
  }

  return (
    <div className="flex flex-col gap-6">
      <h1 className="font-display text-xl font-bold uppercase tracking-wide">Users</h1>
      {loadErr && <div className="text-xs text-red-400">{loadErr}</div>}

      <div className="overflow-hidden rounded-xl border border-border-subtle bg-bg-card">
        <table className="w-full text-xs">
          <thead className="text-left text-[10px] uppercase tracking-wide text-text-muted">
            <tr className="border-b border-border-subtle">
              <th className="px-4 py-2 font-medium">Name</th>
              <th className="px-4 py-2 font-medium">Email</th>
              <th className="px-4 py-2 font-medium">Role</th>
              <th className="px-4 py-2 font-medium">Status</th>
              <th className="px-4 py-2 font-medium">Last sign-in</th>
              <th className="px-4 py-2"></th>
            </tr>
          </thead>
          <tbody>
            {users === null && !loadErr && <tr><td colSpan={6} className="px-4 py-3 text-text-muted">Loading…</td></tr>}
            {users?.map((u) => {
              const self = u.id === me?.id
              return (
                <tr key={u.id} className="border-b border-border-subtle align-top last:border-0">
                  <td className="px-4 py-2">
                    <div className="font-medium">{u.name}{self && <span className="ml-1.5 text-text-muted">(you)</span>}</div>
                    {rowErr[u.id] && <div className="mt-1 text-red-400">{rowErr[u.id]}</div>}
                    {rowOk[u.id] && <div className="mt-1 text-green-400">{rowOk[u.id]}</div>}
                  </td>
                  <td className="px-4 py-2 text-text-secondary">{u.email}</td>
                  <td className="px-4 py-2">
                    <select
                      value={u.role}
                      disabled={self || busy === u.id}
                      title={self ? "You can't change your own role" : undefined}
                      onChange={(e) => void run(u.id, api.updateUser(u.id, { role: e.target.value as Role }))}
                      className={`${inputCls} py-1`}
                      aria-label={`Role for ${u.email}`}
                    >
                      {ROLES.map((r) => <option key={r} value={r}>{r}</option>)}
                    </select>
                  </td>
                  <td className="px-4 py-2">
                    <div className="flex items-center gap-2">
                      {u.active ? <Pill tone="green">active</Pill> : <Pill>inactive</Pill>}
                      {!self && (
                        <button className={btnGhostRow} disabled={busy === u.id} onClick={() => void run(u.id, api.updateUser(u.id, { active: !u.active }))}>
                          {u.active ? 'Deactivate' : 'Activate'}
                        </button>
                      )}
                    </div>
                  </td>
                  <td className="px-4 py-2 text-text-secondary">{u.lastLoginAt ? dateTimeLabel(u.lastLoginAt) : <span className="text-text-muted">never</span>}</td>
                  <td className="px-4 py-2 text-right">
                    {resetting === u.id ? (
                      <form className="flex items-center justify-end gap-2" onSubmit={(e) => { e.preventDefault(); void submitReset(u.id) }}>
                        <input type="password" autoComplete="new-password" autoFocus placeholder={`New password (${MIN_PASSWORD}+)`} value={newPw} onChange={(e) => setNewPw(e.target.value)} className={`${inputCls} w-44 py-1`} />
                        <button type="submit" className={btnPrimarySm} disabled={busy === u.id || newPw.length < MIN_PASSWORD}>Set</button>
                        <button type="button" className={btnGhostRow} onClick={() => { setResetting(null); setNewPw('') }}>Cancel</button>
                      </form>
                    ) : !self && (
                      <button className={btnGhostRow} onClick={() => { setResetting(u.id); setNewPw('') }}>Reset password</button>
                    )}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      <AddUser onCreated={(u) => setUsers((prev) => [...(prev ?? []), u])} />
    </div>
  )
}

function AddUser({ onCreated }: { onCreated: (u: User) => void }) {
  const blank = { email: '', name: '', role: 'viewer' as Role, password: '' }
  const [f, setF] = useState(blank)
  const [err, setErr] = useState<string | null>(null)
  const [ok, setOk] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const set = (k: keyof typeof f) => (v: string) => setF((x) => ({ ...x, [k]: v }))
  const ready = f.email.includes('@') && f.name.trim() && f.password.length >= MIN_PASSWORD

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    if (!ready || busy) return
    setBusy(true); setErr(null); setOk(null)
    try {
      const u = await api.createUser({ ...f, email: f.email.trim(), name: f.name.trim() })
      onCreated(u)
      setOk(`Added ${u.email}`)
      setF(blank)
    } catch (e) { setErr(errorMessage(e)) } finally { setBusy(false) }
  }

  const label = 'text-[10px] uppercase tracking-wide text-text-muted'
  return (
    <form onSubmit={submit} className={`${cardCls} flex flex-col gap-3`}>
      <h2 className="text-sm font-medium">Add user</h2>
      <div className="grid grid-cols-1 gap-3 md:grid-cols-4">
        <label className="flex flex-col gap-1"><span className={label}>Email</span>
          <input type="email" autoComplete="off" value={f.email} onChange={(e) => set('email')(e.target.value)} className={inputCls} /></label>
        <label className="flex flex-col gap-1"><span className={label}>Name</span>
          <input value={f.name} onChange={(e) => set('name')(e.target.value)} className={inputCls} /></label>
        <label className="flex flex-col gap-1"><span className={label}>Role</span>
          <select value={f.role} onChange={(e) => set('role')(e.target.value)} className={inputCls}>
            {ROLES.map((r) => <option key={r} value={r}>{r}</option>)}
          </select></label>
        <label className="flex flex-col gap-1"><span className={label}>Initial password</span>
          <input type="password" autoComplete="new-password" placeholder={`${MIN_PASSWORD}+ characters`} value={f.password} onChange={(e) => set('password')(e.target.value)} className={inputCls} /></label>
      </div>
      <div className="flex items-center gap-3">
        <button type="submit" className={btnPrimarySm} disabled={!ready || busy}>{busy ? 'Adding…' : 'Add user'}</button>
        {f.password && f.password.length < MIN_PASSWORD && <span className="text-[11px] text-text-muted">Password needs {MIN_PASSWORD}+ characters.</span>}
        {err && <span className="text-xs text-red-400">{err}</span>}
        {ok && <span className="text-xs text-green-400">{ok}</span>}
        {(f.email || f.name || f.password) && <button type="button" className={btnGhost} onClick={() => { setF(blank); setErr(null) }}>Clear</button>}
      </div>
    </form>
  )
}

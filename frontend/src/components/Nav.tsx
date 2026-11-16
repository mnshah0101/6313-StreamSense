import { useEffect, useRef, useState } from 'react'
import { NavLink, Link, useLocation } from 'react-router-dom'
import { useStore } from '../store'
import { useAuth } from '../auth'
import { IconBell, IconPlus, Pill } from './ui'
import ChangePassword from './ChangePassword'

const linkCls = ({ isActive }: { isActive: boolean }) =>
  `rounded-lg px-3 py-1.5 text-sm transition-colors focus:outline-none focus:ring-1 focus:ring-accent ${
    isActive ? 'font-medium text-text-primary' : 'text-text-secondary hover:text-text-primary'
  }`

export function Logo() {
  return (
    <span className="flex items-center gap-2">
      <span className="inline-flex h-6 w-6 items-center justify-center rounded-md bg-text-primary" aria-hidden>
        <svg viewBox="0 0 24 24" className="h-4 w-4" fill="none" stroke="#0a0a0a" strokeWidth="2.5" strokeLinecap="round"><path d="M6 8h12M6 12h12M6 16h7" /></svg>
      </span>
      <span className="font-display text-xl font-bold uppercase tracking-wide">StreamSense</span>
    </span>
  )
}

export default function Nav() {
  const { toggleSidebar, sidebarOpen, unseenAlerts, alerts } = useStore()
  const { can } = useAuth()
  const loc = useLocation()
  const openCount = alerts.filter((a) => a.status === 'open').length
  const badge = unseenAlerts > 0 ? unseenAlerts : openCount
  return (
    <header className="sticky top-0 z-20 h-12 border-b border-border-subtle bg-bg-card">
      <div className="flex h-full items-center gap-4 px-6">
        <Link to="/" className="rounded-lg focus:outline-none focus:ring-1 focus:ring-accent"><Logo /></Link>
        <nav className="ml-4 flex items-center gap-1" aria-label="Primary">
          <NavLink to="/" end className={linkCls}>Games</NavLink>
          <NavLink to="/performance" className={linkCls}>Model Performance</NavLink>
          <NavLink to="/status" className={linkCls}>Status</NavLink>
          {can('admin') && <NavLink to="/admin/users" className={linkCls}>Admin</NavLink>}
          {loc.pathname.startsWith('/games/') && (
            <span className="rounded-lg px-3 py-1.5 text-sm font-medium text-text-primary">Match Analysis</span>
          )}
          {loc.pathname === '/new' && (
            <span className="rounded-lg px-3 py-1.5 text-sm font-medium text-text-primary">New Analysis</span>
          )}
        </nav>
        <div className="ml-auto flex items-center gap-2">
          {can('reviewer') && (
            <Link to="/new" className="inline-flex items-center gap-1.5 rounded-lg bg-accent px-3 py-1.5 text-xs font-medium text-white transition-colors hover:bg-accent-hover focus:outline-none focus:ring-1 focus:ring-accent" aria-label="New analysis">
              <IconPlus className="h-4 w-4" />
              <span>New Analysis</span>
            </Link>
          )}
          <button
            onClick={toggleSidebar}
            aria-label={`Alerts, ${openCount} open`}
            aria-pressed={sidebarOpen}
            className={`relative inline-flex h-8 w-8 items-center justify-center rounded-lg border transition-colors focus:outline-none focus:ring-1 focus:ring-accent ${
              sidebarOpen ? 'border-text-muted bg-bg-card-hover text-text-primary' : 'border-border-subtle text-text-secondary hover:border-text-muted hover:text-text-primary hover:bg-bg-card-hover'
            }`}
          >
            <IconBell />
            {badge > 0 && (
              <span className={`absolute -right-1.5 -top-1.5 min-w-4 rounded-full px-1 text-center text-[10px] font-medium leading-4 ${unseenAlerts > 0 ? 'bg-accent text-white' : 'bg-bg-card-hover text-text-secondary border border-border-subtle'}`}>
                {badge}
              </span>
            )}
          </button>
          <UserMenu />
        </div>
      </div>
    </header>
  )
}

function UserMenu() {
  const { user, logout } = useAuth()
  const [open, setOpen] = useState(false)
  const [changing, setChanging] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!open) return
    const close = (e: MouseEvent | KeyboardEvent) => {
      if (e instanceof KeyboardEvent ? e.key === 'Escape' : !ref.current?.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', close)
    document.addEventListener('keydown', close)
    return () => { document.removeEventListener('mousedown', close); document.removeEventListener('keydown', close) }
  }, [open])
  if (!user) return null
  const item = 'block w-full rounded-md px-3 py-1.5 text-left text-xs text-text-secondary transition-colors hover:bg-bg-card-hover hover:text-text-primary focus:outline-none focus:ring-1 focus:ring-accent'
  return (
    <div ref={ref} className="relative">
      <button
        onClick={() => setOpen((o) => !o)}
        aria-haspopup="menu"
        aria-expanded={open}
        title={user.email}
        className="inline-flex h-8 items-center gap-2 rounded-lg border border-border-subtle px-2.5 text-xs text-text-secondary transition-colors hover:border-text-muted hover:text-text-primary focus:outline-none focus:ring-1 focus:ring-accent"
      >
        <span className="max-w-32 truncate font-medium text-text-primary">{user.name}</span>
        <Pill>{user.role}</Pill>
      </button>
      {open && (
        <div role="menu" className="absolute right-0 top-10 z-30 w-44 rounded-lg border border-border-subtle bg-bg-card p-1 shadow-lg">
          <div className="truncate px-3 py-1.5 text-[11px] text-text-muted">{user.email}</div>
          <button role="menuitem" className={item} onClick={() => { setOpen(false); setChanging(true) }}>Change password</button>
          <button role="menuitem" className={item} onClick={() => { setOpen(false); void logout() }}>Sign out</button>
        </div>
      )}
      {changing && <ChangePassword onClose={() => setChanging(false)} />}
    </div>
  )
}

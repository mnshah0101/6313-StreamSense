import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useStore } from '../store'
import { useAuth } from '../auth'
import { ApiError, errorMessage } from '../api'
import { dateTimeLabel, gameTitle } from '../data/format'
import type { Alert } from '../data/types'
import FrameThumb from './FrameThumb'
import TeamCrest from './TeamCrest'
import { DefectPill, EmptyState, IconX, Pill, Segmented, btnGhostRow, btnPrimarySm } from './ui'

export default function AlertsSidebar() {
  const { sidebarOpen, setSidebarOpen, alerts, reviewAlert, gamesById } = useStore()
  const canReview = useAuth().can('reviewer')
  const [tab, setTab] = useState<'open' | 'reviewed'>('open')
  // Failed save per alert: what we tried and why it failed.
  const [failing, setFailing] = useState<{ id: string; decision: 'confirmed' | 'dismissed'; message: string } | null>(null)
  const [saving, setSaving] = useState<string | null>(null)
  const nav = useNavigate()
  if (!sidebarOpen) return null

  const review = async (a: Alert, decision: 'confirmed' | 'dismissed') => {
    setSaving(a.id)
    try {
      await reviewAlert(a, decision)
      setFailing(null)
    } catch (e) {
      const message = e instanceof ApiError && e.status === 409 ? `Save failed: ${e.message}` : `Save failed (${errorMessage(e)}). The alert stays open.`
      setFailing({ id: a.id, decision, message })
    } finally {
      setSaving(null)
    }
  }

  // Newest reviews first on the Reviewed tab; the API already orders open alerts worst first.
  const list = alerts.filter((a) => a.status === tab && gamesById[a.gameId])
  if (tab === 'reviewed') list.sort((a, b) => (b.reviewedAt ?? b.createdAt).localeCompare(a.reviewedAt ?? a.createdAt))
  const open = (a: (typeof alerts)[number]) => {
    nav(`/games/${a.gameId}?frame=${a.frameIndex}&alert=${a.id}`)
  }

  return (
    <aside className="fixed inset-y-12 right-0 z-10 flex w-[420px] flex-col border-l border-border-subtle bg-bg-card" aria-label="Alerts">
      <div className="flex items-center gap-3 border-b border-border-subtle px-4 py-3">
        <h2 className="font-display text-base font-bold uppercase tracking-wide">Alerts</h2>
        <Segmented value={tab} onChange={setTab} options={[{ value: 'open', label: `Open (${alerts.filter((a) => a.status === 'open').length})` }, { value: 'reviewed', label: `Reviewed (${alerts.filter((a) => a.status === 'reviewed').length})` }]} />
        <button onClick={() => setSidebarOpen(false)} aria-label="Close alerts" className="ml-auto rounded-lg p-1 text-text-secondary transition-colors hover:bg-bg-card-hover hover:text-text-primary focus:outline-none focus:ring-1 focus:ring-accent">
          <IconX />
        </button>
      </div>
      <div className="flex-1 overflow-y-auto">
        {list.length === 0 ? (
          <EmptyState>{tab === 'open' ? 'No open alerts.' : 'No reviewed alerts.'}</EmptyState>
        ) : (
          <ul className="divide-y divide-border-subtle">
            {list.map((a) => {
              const game = gamesById[a.gameId]
              return (
                <li key={a.id} className="transition-colors hover:bg-bg-card-hover">
                  <div className="flex gap-3 px-4 py-3">
                    <button onClick={() => open(a)} className="w-24 shrink-0 overflow-hidden rounded-lg border border-border-subtle focus:outline-none focus:ring-1 focus:ring-accent" aria-label={`Open alert for ${gameTitle(game)}`}>
                      <FrameThumb imageUrl={a.thumbUrl ?? a.imageUrl} label={`Alerted frame ${a.frameIndex}`} />
                    </button>
                    <div className="min-w-0 flex-1">
                      <button onClick={() => open(a)} className="flex w-full min-w-0 items-center gap-1.5 text-left focus:outline-none focus:ring-1 focus:ring-accent rounded">
                        <TeamCrest team={game.home} size={14} /><TeamCrest team={game.away} size={14} />
                        <span className="truncate text-sm font-medium">{gameTitle(game)}</span>
                        <span className="ml-auto shrink-0 text-xs text-text-muted">{a.raisedAt}</span>
                      </button>
                      <div className="mt-1.5 flex flex-wrap gap-1.5">
                        {a.detections.map((d) => <DefectPill key={d.type} d={d} />)}
                      </div>
                      {tab === 'open' ? canReview && (
                        <div className="mt-2 flex items-center gap-2">
                          <button className={btnPrimarySm} disabled={saving === a.id} onClick={() => review(a, 'confirmed')}>Confirm</button>
                          <button className={btnGhostRow} disabled={saving === a.id} onClick={() => review(a, 'dismissed')}>
                            Dismiss
                          </button>
                        </div>
                      ) : (
                        <div className="mt-2 flex items-center gap-2 text-[11px] text-text-muted">
                          {a.decision === 'confirmed' ? <Pill tone="green">confirmed</Pill> : <Pill tone="neutral">dismissed</Pill>}
                          <span>by {a.reviewedBy ?? 'unknown'}{a.reviewedAt ? ` · ${dateTimeLabel(a.reviewedAt)}` : ''}</span>
                        </div>
                      )}
                      {failing?.id === a.id && (
                        <div className="mt-2 flex items-center gap-2 text-xs text-red-400">
                          <span>{failing.message}</span>
                          {a.status === 'open' && <button className={btnGhostRow} disabled={saving === a.id} onClick={() => review(a, failing.decision)}>Retry</button>}
                        </div>
                      )}
                    </div>
                  </div>
                </li>
              )
            })}
          </ul>
        )}
      </div>
    </aside>
  )
}

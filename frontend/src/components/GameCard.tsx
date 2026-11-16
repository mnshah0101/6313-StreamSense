import { Link } from 'react-router-dom'
import type { Game } from '../data/types'
import { dateLabel, gameTitle } from '../data/format'
import { useStore } from '../store'
import MatchupThumb from './MatchupThumb'
import { StatusPill } from './ui'

export default function GameCard({ game, wide = false }: { game: Game; wide?: boolean }) {
  const { alerts } = useStore()
  const status = game.status
  const open = alerts.filter((a) => a.gameId === game.id && a.status === 'open')
  const worst = game.stretches[0]
  const worstLabel = worst?.defects[0] && status !== 'no-video' && status !== 'queued'
    ? `${worst.defects[0].type} · sev ${worst.defects[0].severity ?? '—'}` : null
  return (
    <Link
      to={`/games/${game.id}`}
      className={`group block shrink-0 overflow-hidden rounded-xl border border-border-subtle bg-bg-card transition-colors hover:border-text-muted focus:outline-none focus:ring-1 focus:ring-accent ${wide ? 'w-full' : 'w-64'}`}
    >
      <div className="relative aspect-video border-b border-border-subtle bg-bg-primary">
        <MatchupThumb game={game} />
        {status === 'no-video' && (
          <div className="absolute inset-0 flex items-center justify-center bg-bg-primary/70 text-xs text-red-400">No video available</div>
        )}
        <div className="absolute left-2 top-2"><StatusPill status={status} openAlerts={open.length} /></div>
        <div className="absolute bottom-2 right-2 rounded-md bg-bg-primary/85 px-1.5 py-0.5 text-[10px] text-text-secondary">{game.mediaKind === 'image' ? 'image' : `${game.durationMin} min`}</div>
      </div>
      <div className="p-3">
        <div className="flex items-baseline justify-between gap-2">
          <div className="truncate font-display text-base font-bold uppercase tracking-wide">{gameTitle(game)}</div>
        </div>
        <div className="mt-0.5 truncate text-xs text-text-secondary">
          {[game.sport, game.league, `${dateLabel(game.date)} ${game.startTime}`.trim()].filter(Boolean).join(' · ')}
        </div>
        {worstLabel && <div className="mt-1 truncate text-[11px] text-text-muted">{worstLabel}</div>}
      </div>
    </Link>
  )
}

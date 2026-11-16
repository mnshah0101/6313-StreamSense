import type { Game } from '../data/types'
import FrameThumb from './FrameThumb'
import SportIcon from './SportIcon'
import TeamCrest from './TeamCrest'

/** Catalog poster: the uploaded footage's poster frame (dimmed) with both teams' initials. */
export default function MatchupThumb({ game }: { game: Game }) {
  const pending = !game.posterUrl && (game.status === 'queued' || game.status === 'processing')
  return (
    <div className="relative h-full w-full overflow-hidden">
      <div className="h-full w-full opacity-40">
        <FrameThumb imageUrl={game.posterUrl} pending={pending} label={`Poster frame, ${game.home} vs ${game.away}`} />
      </div>
      <div className="absolute inset-0 flex items-center justify-center gap-3">
        <TeamBlock name={game.home} />
        <span className="font-display text-base font-bold uppercase tracking-wide text-text-secondary">vs</span>
        <TeamBlock name={game.away} />
      </div>
      <div className="absolute bottom-2 left-2 inline-flex items-center gap-1 rounded-md bg-bg-primary/85 px-1.5 py-0.5 text-[10px] text-text-secondary">
        <SportIcon sport={game.sport} className="h-3 w-3" />
        <span>{game.sport}</span>
      </div>
    </div>
  )
}

function TeamBlock({ name }: { name: string }) {
  return (
    <div className="flex w-20 flex-col items-center gap-1">
      <TeamCrest team={name} size={44} />
      <span className="max-w-full truncate text-[10px] font-medium uppercase tracking-wide text-text-primary">{name}</span>
    </div>
  )
}

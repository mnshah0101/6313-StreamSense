import { useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { gameTitle } from '../data/format'
import { CAMERAS, DEFECT_TYPES, SPORTS, worstSev as worstOf, type Game, type GameStatus } from '../data/types'
import { useStore } from '../store'
import { useAuth } from '../auth'
import { api, errorMessage } from '../api'
import GameCard from '../components/GameCard'
import { EmptyState, IconChevron, IconPlus, IconSearch, btnGhost, btnPrimary, inputCls } from '../components/ui'

type StatusFilter = 'all' | GameStatus | 'needs-review'

export default function Home() {
  const { alerts, games, gamesLoaded, apiError } = useStore()
  const { can } = useAuth()
  const [q, setQ] = useState('')
  const [sport, setSport] = useState('all')
  const [status, setStatus] = useState<StatusFilter>('all')
  const [defect, setDefect] = useState('all')
  const [camera, setCamera] = useState('all')
  const [sort, setSort] = useState<'recent' | 'severity' | 'title'>('recent')

  const openFor = (g: Game) => alerts.filter((a) => a.gameId === g.id && a.status === 'open').length
  const worstSev = (g: Game) => worstOf(g.stretches.flatMap((s) => s.defects))

  const filtering = q.trim() !== '' || sport !== 'all' || status !== 'all' || defect !== 'all' || camera !== 'all'

  // Filters run server-side (GET /games?q&sport&status&camera&defect); "needs review" and sort stay local.
  const [results, setResults] = useState<Game[]>([])
  const [filterErr, setFilterErr] = useState<string | null>(null)
  useEffect(() => {
    if (!filtering) return
    let cancelled = false
    const all = (v: string) => (v === 'all' ? undefined : v)
    const t = window.setTimeout(() => {
      api.listGames({ q: q.trim() || undefined, sport: all(sport), camera: all(camera), defect: all(defect), status: status === 'needs-review' ? undefined : all(status) })
        .then((list) => { if (!cancelled) { setResults(list); setFilterErr(null) } })
        .catch((e) => { if (!cancelled) setFilterErr(errorMessage(e)) })
    }, 250)
    return () => { cancelled = true; window.clearTimeout(t) }
  }, [filtering, q, sport, status, defect, camera, games])

  const filtered = useMemo(() => {
    let list = status === 'needs-review' ? results.filter((g) => openFor(g) > 0) : results
    list = [...list].sort((a, b) => {
      if (sort === 'severity') return worstSev(b) - worstSev(a)
      if (sort === 'title') return gameTitle(a).localeCompare(gameTitle(b))
      return (b.date + b.startTime).localeCompare(a.date + a.startTime)
    })
    return list
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [results, status, sort, alerts])

  const clear = () => { setQ(''); setSport('all'); setStatus('all'); setDefect('all'); setCamera('all') }

  const needsReview = games.filter((g) => openFor(g) > 0).sort((a, b) => worstSev(b) - worstSev(a))
  const live = games.filter((g) => ['live', 'processing', 'queued'].includes(g.status))
  const recent = games.filter((g) => g.status === 'analyzed').sort((a, b) => (b.date + b.startTime).localeCompare(a.date + a.startTime))
  const sports = [...SPORTS, ...games.map((g) => g.sport).filter((s) => !SPORTS.includes(s))]
  const cameras = [...new Set([...CAMERAS, ...games.map((g) => g.camera).filter(Boolean)])]
  const bySport = [...new Set(sports)].map((s) => ({ sport: s, games: games.filter((g) => g.sport === s) })).filter((x) => x.games.length > 0)

  const selectCls = `${inputCls} pr-7`

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-end gap-3">
        <div>
          <h1 className="font-display text-xl font-bold uppercase tracking-wide">Games</h1>
          {!gamesLoaded && <p className="text-xs text-text-secondary">Loading…</p>}
          {(apiError || (filtering && filterErr)) && <p className="text-xs text-red-400">{filtering && filterErr ? filterErr : apiError}</p>}
        </div>
        <div className="ml-auto flex flex-wrap items-center gap-2">
          <label className="relative">
            <span className="sr-only">Search games</span>
            <IconSearch className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-text-muted" />
            <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search" className={`${inputCls} w-64 pl-8`} />
          </label>
          <Filter label="Sport" value={sport} onChange={setSport} options={[...new Set(sports)]} cls={selectCls} />
          <Filter label="Status" value={status} onChange={(v) => setStatus(v as StatusFilter)} cls={selectCls}
            options={[['needs-review', 'Needs review'], ['live', 'Live'], ['processing', 'Processing'], ['queued', 'Queued'], ['analyzed', 'Analyzed'], ['no-video', 'No video']]} />
          <Filter label="Defect" value={defect} onChange={setDefect} options={DEFECT_TYPES} cls={selectCls} />
          <Filter label="Camera" value={camera} onChange={setCamera} options={cameras} cls={selectCls} />
          <Filter label="Sort" value={sort} onChange={(v) => setSort(v as typeof sort)} cls={selectCls} noAll
            options={[['recent', 'Most recent'], ['severity', 'Most severe'], ['title', 'Title A–Z']]} />
          {filtering && <button className={btnGhost} onClick={clear}>Clear</button>}
        </div>
      </div>

      {gamesLoaded && games.length === 0 && !filtering ? (
        <div className="flex flex-col items-center justify-center gap-3 rounded-xl border border-dashed border-border-subtle bg-bg-card px-6 py-16 text-center">
          <div className="text-sm text-text-secondary">No games yet.</div>
          {can('reviewer') && <Link to="/new" className={`${btnPrimary} inline-flex items-center gap-1.5`}><IconPlus />New Analysis</Link>}
        </div>
      ) : filtering ? (
        <section>
          <div className="mb-3 text-xs text-text-secondary">{filtered.length} result{filtered.length === 1 ? '' : 's'}</div>
          {filtered.length === 0 ? (
            <EmptyState action={<button className={btnGhost} onClick={clear}>Clear</button>}>
              No matches.
            </EmptyState>
          ) : (
            <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
              {filtered.map((g) => <GameCard key={g.id} game={g} wide />)}
            </div>
          )}
        </section>
      ) : (
        <>
          {needsReview.length > 0 && <Row title="Needs review" games={needsReview} />}
          {live.length > 0 && <Row title="In progress" games={live} />}
          {recent.length > 0 && <Row title="Recent" games={recent} />}
          {bySport.map((x) => <Row key={x.sport} title={x.sport} games={x.games} />)}
        </>
      )}
    </div>
  )
}

function Filter({ label, value, onChange, options, cls, noAll = false }: { label: string; value: string; onChange: (v: string) => void; options: (string | [string, string])[]; cls: string; noAll?: boolean }) {
  return (
    <label className="inline-flex items-center gap-1.5">
      <span className="text-[10px] uppercase tracking-wide text-text-muted">{label}</span>
      <select value={value} onChange={(e) => onChange(e.target.value)} className={cls}>
        {!noAll && <option value="all">All</option>}
        {options.map((o) => {
          const [v, l] = Array.isArray(o) ? o : [o, o]
          return <option key={v} value={v}>{l}</option>
        })}
      </select>
    </label>
  )
}

function Row({ title, games }: { title: string; games: Game[] }) {
  const ref = useRef<HTMLDivElement>(null)
  const scroll = (dir: number) => ref.current?.scrollBy({ left: dir * 560, behavior: 'smooth' })
  return (
    <section>
      <div className="mb-2 flex items-baseline gap-3">
        <h2 className="font-display text-base font-bold uppercase tracking-wide">{title}</h2>
        <div className="ml-auto flex gap-1">
          <button onClick={() => scroll(-1)} aria-label={`Scroll ${title} left`} className="rounded-lg border border-border-subtle p-1 text-text-secondary transition-colors hover:border-text-muted hover:text-text-primary focus:outline-none focus:ring-1 focus:ring-accent"><IconChevron dir="left" /></button>
          <button onClick={() => scroll(1)} aria-label={`Scroll ${title} right`} className="rounded-lg border border-border-subtle p-1 text-text-secondary transition-colors hover:border-text-muted hover:text-text-primary focus:outline-none focus:ring-1 focus:ring-accent"><IconChevron /></button>
        </div>
      </div>
      <div ref={ref} className="row-scroll -mx-6 flex gap-4 overflow-x-auto px-6 pb-1">
        {games.map((g) => <GameCard key={g.id} game={g} />)}
      </div>
    </section>
  )
}

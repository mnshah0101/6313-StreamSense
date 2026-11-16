import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import { FRAME_INTERVAL_SEC, clockLabel, dateLabel, dateTimeLabel, gameTitle, timeLabel, wallClock, jobStatusLine } from '../data/format'
import { DEFECT_TYPES, jobActive, type Alert, type DefectType, type Frame, type Game, type Job } from '../data/types'
import { usePoll, useStore } from '../store'
import { useAuth } from '../auth'
import { ApiError, api, errorMessage } from '../api'
import FrameThumb from '../components/FrameThumb'
import TeamCrest from '../components/TeamCrest'
import SportIcon from '../components/SportIcon'
import Timeline from '../components/Timeline'
import { DefectPill, Eyebrow, IconFlag, IconThumb, Pill, Spinner, StatusPill, Toggle, btnGhost, btnGhostRow, btnPrimarySm, cardCls, inputCls } from '../components/ui'

/** Game + frames from the API. Refetches while a job runs so partial results fill the timeline. */
function useMatchData(id: string) {
  const { gamesById, upsertGame, jobs, trackJob, refreshFeedback } = useStore()
  const [game, setGame] = useState<Game | null>(gamesById[id] ?? null)
  const [apiFrames, setApiFrames] = useState<Frame[]>([])
  const [loadErr, setLoadErr] = useState<{ status: number; message: string } | null>(null)
  const [loading, setLoading] = useState(true)
  const job: Job | undefined = jobs.find((j) => j.gameId === id) // newest first

  const load = useCallback(async () => {
    try {
      const [g, fr] = await Promise.all([api.getGame(id), api.gameFrames(id)])
      setGame(g)
      upsertGame(g)
      setApiFrames(fr)
      setLoadErr(null)
    } catch (e) {
      setLoadErr({ status: e instanceof ApiError ? e.status : 0, message: errorMessage(e) })
    } finally {
      setLoading(false)
    }
  }, [id, upsertGame])

  useEffect(() => {
    setGame(gamesById[id] ?? null); setApiFrames([]); setLoading(true)
    void load()
    void refreshFeedback()
    // The latest job for this game (latency stats, and polling if it is still running).
    api.listJobs({ gameId: id, limit: 1 }).then(([j]) => { if (j) trackJob(j) }).catch(() => {})
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id])

  // The store polls GET /jobs/{id} every 1.5 s; each change in progress pulls the new frames.
  const jobKey = job ? `${job.id}:${job.status}:${job.doneFrames}` : ''
  useEffect(() => {
    if (jobKey) void load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jobKey])

  // Live streams: append frames as they arrive.
  usePoll(async () => {
    const next = apiFrames.length ? apiFrames[apiFrames.length - 1].index + 1 : 0
    const more = await api.gameFrames(id, { start: next }).catch(() => [])
    if (more.length) setApiFrames((prev) => [...prev, ...more.filter((f) => f.index >= next)])
  }, 5000, game?.status === 'live')

  const lastIdx = apiFrames.reduce((m, f) => Math.max(m, f.index), -1)
  const active = !!job && jobActive(job)
  const visible = active ? Math.min(lastIdx + 1, job!.doneFrames) : lastIdx + 1
  const total = Math.max(game?.totalFrames ?? 0, active ? job!.totalFrames : 0)

  const frames = useMemo<Frame[]>(() => {
    if (!game) return []
    const byIdx = new Map(apiFrames.map((f) => [f.index, f]))
    const n = Math.max(total, lastIdx + 1)
    return Array.from({ length: n }, (_, i) => {
      const stretch = game.stretches.find((st) => i >= st.start && i <= st.end)
      const f = byIdx.get(i)
      return f ? { ...f, stretch } : { index: i, tSec: i * FRAME_INTERVAL_SEC, score: 0, detections: [], pending: true }
    })
  }, [game, apiFrames, total, lastIdx])

  return { game, frames, visible, total, job, loading, loadErr, reload: load }
}

export default function MatchAnalysis() {
  const { id = '' } = useParams()
  const [params, setParams] = useSearchParams()
  const { alerts, feedback, addFeedback, removeFeedback, reviewAlert, threshold, rerunAnalysis } = useStore()
  const canReview = useAuth().can('reviewer')
  const { game, frames, visible, total, job, loading, loadErr } = useMatchData(id)
  const status = game?.status
  const [actionErr, setActionErr] = useState<string | null>(null)
  const [starting, setStarting] = useState(false)
  const running = !!job && jobActive(job)
  const isImage = game?.mediaKind === 'image'
  // Re-run only finished (or failed / cancelled) analyses of stored footage.
  const canRerun = canReview && !!game?.hasVideo && !running && status !== 'live' &&
    (status === 'analyzed' || job?.status === 'failed' || job?.status === 'cancelled')
  const rerun = async () => {
    if (!game) return
    setStarting(true); setActionErr(null)
    try { await rerunAnalysis(game.id) } catch (e) { setActionErr(errorMessage(e)) } finally { setStarting(false) }
  }
  const [reviewErr, setReviewErr] = useState<{ alertId: string; decision: 'confirmed' | 'dismissed'; message: string } | null>(null)
  const review = async (a: Alert, decision: 'confirmed' | 'dismissed') => {
    try { await reviewAlert(a, decision); setReviewErr(null) } catch (e) {
      setReviewErr({ alertId: a.id, decision, message: e instanceof ApiError && e.status === 409 ? `Save failed: ${e.message}` : `Save failed (${errorMessage(e)}). The alert stays open.` })
    }
  }
  const act = (p: Promise<unknown>) => { setActionErr(null); p.catch((e) => setActionErr(errorMessage(e))) }

  const selected = params.get('frame') !== null ? Number(params.get('frame')) : null
  const select = (i: number | null) => {
    const next = new URLSearchParams(params)
    if (i === null) next.delete('frame'); else next.set('frame', String(i))
    next.delete('alert')
    setParams(next, { replace: true })
  }

  // Default to the worst frame once results exist (an image has only frame 0).
  useEffect(() => {
    if (!game || selected !== null) return
    const worst = game.mediaKind === 'image' ? (visible > 0 ? 0 : undefined) : game.stretches.map((s) => s.worst).filter((w) => w < visible)[0]
    if (worst !== undefined) select(worst)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [game?.id, visible])

  if (!game) {
    if (loading) return <div className="text-sm text-text-muted">Loading match…</div>
    return (
      <div className="text-sm text-text-muted">
        {loadErr && loadErr.status !== 404 ? <span className="text-red-400">{loadErr.message} </span> : <>Game not found. </>}
        <Link to="/" className="underline">Games</Link>
      </div>
    )
  }

  const gameAlerts = alerts.filter((a) => a.gameId === game.id)
  const gameFeedback = feedback.filter((f) => f.gameId === game.id)
  const frame = selected !== null ? frames[selected] : undefined
  const badFrames = frames.slice(0, visible).filter((f) => f.detections.length > 0).length
  const openAlerts = gameAlerts.filter((a) => a.status === 'open').length
  const alertAtFrame = frame ? gameAlerts.find((a) => a.frameIndex === frame.index) : undefined
  const progress = total ? visible / total : 0
  const meta = [game.league, game.venue, `${dateLabel(game.date)} ${game.startTime}`.trim()].filter(Boolean)
  const emptyMessage = loading ? 'Loading…'
    : status === 'no-video' ? 'No footage stored.'
    : job?.status === 'failed' ? `Analysis failed${job.error ? `: ${job.error}` : '.'}`
    : running ? jobStatusLine(job).text
    : job?.status === 'cancelled' ? 'Analysis cancelled.'
    : 'No results yet.'

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-end gap-4">
        <div className="min-w-0">
          <Link to="/" className="text-xs text-text-secondary hover:text-text-primary">← Games</Link>
          <div className="mt-1 flex items-center gap-3">
            <div className="flex items-center -space-x-1">
              <TeamCrest team={game.home} size={28} />
              <TeamCrest team={game.away} size={28} />
            </div>
            <h1 className="font-display text-xl font-bold uppercase tracking-wide">{gameTitle(game)}</h1>
            <span className="inline-flex text-text-secondary" title={game.sport}><SportIcon sport={game.sport} /></span>
            <StatusPill status={game.status} openAlerts={openAlerts} />
          </div>
          {meta.length > 0 && <div className="text-xs text-text-secondary">{meta.join(' · ')}</div>}
        </div>
        {canRerun && (
          <div className="ml-auto flex items-center gap-2">
            <button className={btnGhost} disabled={starting} onClick={rerun} title="Replaces these results">
              {starting ? <span className="inline-flex items-center gap-2"><Spinner />Starting…</span> : 'Re-run'}
            </button>
          </div>
        )}
      </div>

      <div className="grid grid-cols-3 gap-4">
        <Stat label="Frames" value={`${visible}`} sub={visible < total ? `of ${total}` : undefined} />
        <Stat label="Flagged" value={`${badFrames}`} />
        <Stat label="Open alerts" value={`${openAlerts}`} />
      </div>

      {/* Image: one frame, no timeline */}
      {isImage && (visible === 0 || running || actionErr) && (
        <section className={cardCls}>
          {actionErr && <div className="mb-2 text-xs text-red-400">{actionErr}</div>}
          <div className={`flex items-center gap-2 text-sm ${job?.status === 'failed' ? 'text-red-400' : running ? 'text-yellow-400' : 'text-text-muted'}`}>
            {running && <Spinner />}{visible === 0 ? emptyMessage : 'Re-running…'}
          </div>
        </section>
      )}

      {/* Timeline */}
      {!isImage && <section className={cardCls}>
        <div className="mb-3 flex flex-wrap items-center gap-3">
          <h2 className="text-sm font-medium">Timeline</h2>
          {running && (() => {
            const st = jobStatusLine(job)
            return (
              <div className={`ml-auto flex items-center gap-2 text-xs ${st.stale ? 'text-text-muted' : 'text-yellow-400'}`}>
                <Spinner />
                <span>{st.text}</span>
                {st.progress !== null && (
                  <span className="h-1 w-24 rounded-sm bg-border-subtle" aria-hidden><span className="block h-1 rounded-sm bg-yellow-400/70" style={{ width: `${Math.round(st.progress * 100)}%` }} /></span>
                )}
              </div>
            )
          })()}
          {status === 'live' && <div className="ml-auto text-xs text-red-400">Live</div>}
        </div>
        {actionErr && <div className="mb-3 text-xs text-red-400">{actionErr}</div>}
        {visible === 0 ? (
          <div className={`flex flex-col items-center gap-3 py-10 text-center text-sm ${job?.status === 'failed' ? 'text-red-400' : 'text-text-muted'}`}>
            <span className="inline-flex items-center gap-2">{running && <Spinner />}{emptyMessage}</span>
            {canRerun && <button className={btnGhost} disabled={starting} onClick={rerun}>Re-run</button>}
          </div>
        ) : (
          <>
            {visible < total && (
              <div className="mb-3 flex items-center gap-2">
                <div className="flex h-2 flex-1 gap-1" aria-hidden>
                  <div className="h-2 flex-1 rounded-sm bg-border-subtle"><div className="h-2 rounded-sm bg-green-500" style={{ width: `${progress * 100}%` }} /></div>
                </div>
                <span className="text-[11px] tabular-nums text-text-secondary">{Math.round(progress * 100)}%</span>
              </div>
            )}
            <Timeline frames={frames} visible={visible} selected={selected} onSelect={select} feedback={gameFeedback} threshold={threshold} />
          </>
        )}
      </section>}

      {/* Frame detail */}
      {frame && (
        <FrameDetail
          key={frame.index}
          frame={frame}
          game={game}
          isImage={isImage}
          canReview={canReview}
          alertId={alertAtFrame?.id}
          alertRaisedAt={alertAtFrame?.createdAt}
          alertStatus={alertAtFrame?.status}
          alertDecision={alertAtFrame?.decision ?? undefined}
          reviewError={alertAtFrame && reviewErr?.alertId === alertAtFrame.id ? reviewErr.message : undefined}
          onRetryReview={() => alertAtFrame && reviewErr && review(alertAtFrame, reviewErr.decision)}
          onReview={(d) => alertAtFrame && review(alertAtFrame, d)}
          onFeedback={(f) => act(addFeedback({ gameId: game.id, frameIndex: frame.index, ...f }))}
          existing={gameFeedback.filter((f) => f.frameIndex === frame.index).map((f) => ({ id: f.id, kind: f.kind, defect: f.defect ?? undefined }))}
          onRemove={(fid) => act(removeFeedback(fid))}
          onStep={(d) => select(Math.max(0, Math.min(visible - 1, frame.index + d)))}
        />
      )}

      {/* Feedback log */}
      <section>
        <h2 className="mb-2 font-display text-base font-bold uppercase tracking-wide">Feedback</h2>
        {actionErr && <div className="mb-2 text-xs text-red-400">{actionErr}</div>}
        {gameFeedback.length === 0 ? (
          <div className="rounded-xl border border-border-subtle bg-bg-card p-4 text-center text-sm text-text-muted">No feedback yet.</div>
        ) : (
          <div className="overflow-hidden rounded-xl border border-border-subtle bg-bg-card">
            <table className="w-full text-xs">
              <thead className="bg-bg-card text-left text-[10px] uppercase tracking-wide text-text-muted">
                <tr className="border-b border-border-subtle">
                  <th className="px-4 py-2 font-medium">Time</th>
                  <th className="px-4 py-2 font-medium">Label</th>
                  <th className="px-4 py-2 font-medium">Defect</th>
                  <th className="px-4 py-2 text-right font-medium">Severity</th>
                  <th className="px-4 py-2 font-medium">Note</th>
                  <th className="px-4 py-2 font-medium">Logged</th>
                  {canReview && <th className="px-4 py-2"></th>}
                </tr>
              </thead>
              <tbody>
                {gameFeedback.map((f) => (
                  <tr key={f.id} className="border-b border-border-subtle last:border-0 transition-colors hover:bg-bg-card-hover">
                    <td className="px-4 py-2 tabular-nums"><button className="underline-offset-2 hover:underline" onClick={() => select(f.frameIndex)}>{clockLabel(f.frameIndex * FRAME_INTERVAL_SEC)}</button></td>
                    <td className="px-4 py-2">
                      {f.kind === 'correct' && <Pill tone="green">correct</Pill>}
                      {f.kind === 'incorrect' && <Pill tone="red">wrong</Pill>}
                      {f.kind === 'missed' && <Pill tone="yellow">missed</Pill>}
                    </td>
                    <td className="px-4 py-2">{f.defect ?? <span className="text-text-muted">—</span>}</td>
                    <td className="px-4 py-2 text-right tabular-nums">{f.severity ?? <span className="text-text-muted">—</span>}</td>
                    <td className="max-w-xs truncate px-4 py-2 text-text-secondary">{f.note || <span className="text-text-muted">—</span>}</td>
                    <td className="px-4 py-2 text-text-muted">{timeLabel(f.createdAt)}{f.reviewer ? ` · ${f.reviewer}` : ''}</td>
                    {canReview && <td className="px-4 py-2 text-right"><button className={btnGhostRow} onClick={() => act(removeFeedback(f.id))}>Undo</button></td>}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  )
}

function Stat({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className={cardCls}>
      <Eyebrow>{label}</Eyebrow>
      <div className="mt-1 font-display text-3xl font-bold tabular-nums">{value}</div>
      {sub && <div className="mt-1 text-[11px] text-text-muted">{sub}</div>}
    </div>
  )
}

interface DetailProps {
  frame: Frame
  game: Game
  isImage: boolean
  /** Reviewer+: Confirm / Dismiss and feedback controls. */
  canReview: boolean
  alertId?: string
  alertRaisedAt?: string
  alertStatus?: 'open' | 'reviewed'
  alertDecision?: 'confirmed' | 'dismissed'
  reviewError?: string
  onRetryReview: () => void
  onReview: (d: 'confirmed' | 'dismissed') => void
  onFeedback: (f: { kind: 'correct' | 'incorrect' | 'missed'; defect?: DefectType; severity?: number | null; region?: { x: number; y: number }; note?: string }) => void
  existing: { id: string; kind: string; defect?: string }[]
  onRemove: (id: string) => void
  onStep: (d: number) => void
}

function FrameDetail({ frame, game, isImage, canReview, alertId, alertRaisedAt, alertStatus, alertDecision, reviewError, onRetryReview, onReview, onFeedback, existing, onRemove, onStep }: DetailProps) {
  const [heat, setHeat] = useState(false)
  const [mode, setMode] = useState<'none' | 'incorrect' | 'missed'>('none')
  const [defect, setDefect] = useState<DefectType>('Blur')
  const [severity, setSeverity] = useState(3)
  const [note, setNote] = useState('')
  const [mark, setMark] = useState<{ x: number; y: number } | null>(null)
  const [wrongReason, setWrongReason] = useState<'false-positive' | 'wrong-type' | 'wrong-severity'>('false-positive')

  const stretch = frame.stretch
  // The API decides: overlay image if one was rendered, else the peak circle; unsupported/failed = none.
  const hm = frame.heatmap
  const heatShape = hm?.heat ?? frame.heat ?? null
  const heatAvailable = hm?.status === 'available' && (!!hm.overlayUrl || !!heatShape)
  const region = stretch?.region || hm?.locationText || frame.detections.find((d) => d.locationText)?.locationText || null
  const t = frame.tSec
  const hasDetections = frame.detections.length > 0
  const heatNote = heatAvailable || !hasDetections ? null : hm?.status === 'failed' ? 'Heat map failed' : 'No heat map for this defect'
  const verdict = existing.find((e) => e.kind === 'correct' || e.kind === 'incorrect')
  const missedHere = existing.filter((e) => e.kind === 'missed')

  const reset = () => { setMode('none'); setNote(''); setMark(null) }
  const submitIncorrect = () => {
    onFeedback({ kind: 'incorrect', defect: frame.detections[0]?.type, severity: frame.detections[0]?.severity, note: `${wrongReason}${note ? ` · ${note}` : ''}` })
    reset()
  }
  const submitMissed = () => {
    onFeedback({ kind: 'missed', defect, severity, region: mark ?? undefined, note: note || undefined })
    reset()
  }

  return (
    <section className={cardCls}>
      <div className="mb-3 flex flex-wrap items-center gap-3">
        <h2
          className="font-display text-base font-bold uppercase tracking-wide tabular-nums"
          title={[isImage ? null : `Frame ${frame.index}`, isImage ? null : wallClock(game, t), frame.modelId].filter(Boolean).join(' · ') || undefined}
        >
          {isImage ? 'Image' : clockLabel(t)}
        </h2>
        {alertId && (
          <span title={alertRaisedAt ? `Raised ${dateTimeLabel(alertRaisedAt)}` : undefined}>
            {alertStatus === 'open' ? <Pill tone="yellow">open alert</Pill> : <Pill tone={alertDecision === 'confirmed' ? 'green' : 'neutral'}>{alertDecision}</Pill>}
          </span>
        )}
        {!isImage && (
          <div className="ml-auto flex gap-1">
            <button className={btnGhostRow} onClick={() => onStep(-1)} aria-label="Previous frame">‹</button>
            <button className={btnGhostRow} onClick={() => onStep(1)} aria-label="Next frame">›</button>
          </div>
        )}
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-5">
        {/* Frame */}
        <div className="lg:col-span-3">
          <div className="relative aspect-video overflow-hidden rounded-lg border border-border-subtle bg-bg-primary">
            <FrameThumb
              heat={heatShape}
              showHeat={heat && heatAvailable}
              imageUrl={frame.imageUrl}
              overlayUrl={hm?.overlayUrl}
              marker={mark}
              onClickFrame={mode === 'missed' ? setMark : undefined}
              label={isImage ? 'Uploaded image' : `Frame at ${clockLabel(t)}`}
            />
            {mode === 'missed' && (
              <div className="absolute bottom-2 right-2 rounded-md bg-bg-primary/85 px-1.5 py-0.5 text-[10px] text-ground-truth">{mark ? 'Region marked' : 'Click to mark region'}</div>
            )}
          </div>
          <div className="mt-3 flex flex-wrap items-center gap-3">
            <span title={heatAvailable ? `${hm?.method ? `${hm.method.replace(/_/g, ' ')} · ` : ''}not validated against location labels` : undefined}>
              <Toggle on={heat && heatAvailable} onChange={setHeat} label="Heat Map" />
            </span>
            {heatNote && <span className="text-[11px] text-text-muted">{heatNote}</span>}
          </div>
        </div>

        {/* Detail + review */}
        <div className="flex flex-col gap-5 lg:col-span-2">
          <div>
            <Eyebrow>Defects</Eyebrow>
            {hasDetections ? (
              <div className="mt-1.5 flex flex-wrap gap-2">{frame.detections.map((d) => <DefectPill key={d.type} d={d} long />)}</div>
            ) : (
              <div className="mt-1.5"><span title={`Score ${frame.score.toFixed(2)}`}><Pill tone="green">good frame</Pill></span></div>
            )}
            {frame.explanation && <p className="mt-2 text-sm text-text-secondary">{frame.explanation}</p>}
            {region && hasDetections && <div className="mt-2 text-sm">Region: {region}</div>}
          </div>

          {alertId && alertStatus !== 'open' && reviewError && <div className="text-xs text-red-400">{reviewError}</div>}
          {canReview && alertId && alertStatus === 'open' && (
            <div>
              <Eyebrow>Alert</Eyebrow>
              <div className="mt-1.5 flex items-center gap-2">
                <button className={btnPrimarySm} onClick={() => onReview('confirmed')}>Confirm</button>
                <button className={btnGhost} onClick={() => onReview('dismissed')}>Dismiss</button>
              </div>
              {reviewError && (
                <div className="mt-2 flex items-center gap-2 text-xs text-red-400">
                  <span>{reviewError}</span>
                  <button className={btnGhostRow} onClick={onRetryReview}>Retry</button>
                </div>
              )}
            </div>
          )}

          {/* Supervised feedback (viewers see existing labels only) */}
          {(canReview || existing.length > 0) && <div className="border-t border-border-subtle pt-4">
            <Eyebrow>Feedback</Eyebrow>

            {hasDetections && (
              <div className="mt-2">
                {verdict ? (
                  <div className="mt-1.5 flex items-center gap-2 text-xs">
                    {verdict.kind === 'correct' ? <Pill tone="green">marked correct</Pill> : <Pill tone="red">marked wrong</Pill>}
                    {canReview && <button className="text-text-secondary underline hover:text-text-primary" onClick={() => onRemove(verdict.id)}>undo</button>}
                  </div>
                ) : canReview && (
                  <div className="mt-1.5 flex items-center gap-2">
                    <button className={`${btnGhost} inline-flex items-center gap-1.5`} onClick={() => { onFeedback({ kind: 'correct', defect: frame.detections[0].type, severity: frame.detections[0].severity }); setMode('none') }}>
                      <IconThumb />Correct
                    </button>
                    <button className={`${btnGhost} inline-flex items-center gap-1.5 ${mode === 'incorrect' ? 'border-text-muted text-text-primary' : ''}`} onClick={() => setMode(mode === 'incorrect' ? 'none' : 'incorrect')}>
                      <IconThumb down />Incorrect
                    </button>
                  </div>
                )}
                {mode === 'incorrect' && (
                  <div className="mt-3 flex flex-col gap-2 rounded-lg border border-border-subtle p-3">
                    <label className="flex flex-col gap-1">
                      <span className="text-[10px] uppercase tracking-wide text-text-muted">What's wrong</span>
                      <select value={wrongReason} onChange={(e) => setWrongReason(e.target.value as typeof wrongReason)} className={inputCls}>
                        <option value="false-positive">False positive, the frame is fine</option>
                        <option value="wrong-type">Wrong defect type</option>
                        <option value="wrong-severity">Severity is off</option>
                      </select>
                    </label>
                    <label className="flex flex-col gap-1">
                      <span className="text-[10px] uppercase tracking-wide text-text-muted">Note</span>
                      <input value={note} onChange={(e) => setNote(e.target.value)} placeholder="Optional" className={inputCls} />
                    </label>
                    <div className="flex gap-2">
                      <button className={btnPrimarySm} onClick={submitIncorrect}>Save</button>
                      <button className={btnGhost} onClick={reset}>Cancel</button>
                    </div>
                  </div>
                )}
              </div>
            )}

            <div className="mt-3">
              {missedHere.length > 0 && (
                <div className="mt-1.5 flex flex-wrap gap-1.5">
                  {missedHere.map((m) => <Pill key={m.id} tone="yellow">missed: {m.defect}</Pill>)}
                </div>
              )}
              {!canReview ? null : mode !== 'missed' ? (
                <button className={`${btnGhost} mt-1.5 inline-flex items-center gap-1.5`} onClick={() => setMode('missed')}>
                  <IconFlag />Flag Missed
                </button>
              ) : (
                <div className="mt-2 flex flex-col gap-2 rounded-lg border border-border-subtle p-3">
                  <div className="grid grid-cols-2 gap-2">
                    <label className="flex flex-col gap-1">
                      <span className="text-[10px] uppercase tracking-wide text-text-muted">Defect</span>
                      <select value={defect} onChange={(e) => setDefect(e.target.value as DefectType)} className={inputCls}>
                        {DEFECT_TYPES.map((d) => <option key={d} value={d}>{d}</option>)}
                      </select>
                    </label>
                    <label className="flex flex-col gap-1">
                      <span className="text-[10px] uppercase tracking-wide text-text-muted">Severity</span>
                      <select value={severity} onChange={(e) => setSeverity(Number(e.target.value))} className={inputCls}>
                        {[1, 2, 3, 4, 5].map((s) => <option key={s} value={s}>{s} {s === 1 ? '· minimal' : s === 5 ? '· extreme' : ''}</option>)}
                      </select>
                    </label>
                  </div>
                  <label className="flex flex-col gap-1">
                    <span className="text-[10px] uppercase tracking-wide text-text-muted">Note</span>
                    <input value={note} onChange={(e) => setNote(e.target.value)} placeholder="Optional" className={inputCls} />
                  </label>
                  <div className="flex gap-2">
                    <button className={btnPrimarySm} onClick={submitMissed}>Save</button>
                    <button className={btnGhost} onClick={reset}>Cancel</button>
                  </div>
                </div>
              )}
            </div>
          </div>}
        </div>
      </div>
    </section>
  )
}

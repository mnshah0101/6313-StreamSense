import { useEffect, useRef, useState, type DragEvent, type FormEvent, type ReactNode } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { CAMERAS, SPORTS, jobActive, type Job } from '../data/types'
import { clockLabel, dateTimeLabel, mbLabel, todayIso, jobStatusLine } from '../data/format'
import { useStore } from '../store'
import { ApiError, api, errorMessage, uploadCaps, type UploadProgress } from '../api'
import FrameThumb from '../components/FrameThumb'
import { Eyebrow, Pill, Spinner, btnGhost, btnGhostRow, btnPrimary, cardCls, inputCls } from '../components/ui'

/** Accepted uploads, by MIME type and by extension (some browsers leave File.type empty for .mov). */
const TYPES: Record<string, string> = { mp4: 'video/mp4', mov: 'video/quicktime', jpg: 'image/jpeg', jpeg: 'image/jpeg', png: 'image/png' }
const ACCEPT = [...new Set(Object.values(TYPES))]
// Defaults match the API (10 GB, 10 h); the live values come from GET /model.
const DEFAULT_LIMITS = { maxBytes: 10 * 1024 ** 3, maxVideoSec: 10 * 3600 }
const gbLabel = (bytes: number) => `${Math.round(bytes / 1024 ** 3)} GB`
const hoursLabel = (sec: number) => `${Math.round(sec / 3600)} h`

interface Picked {
  file: File
  kind: 'video' | 'image'
  /** Video length from the browser's metadata; null = the browser could not read it (the API still checks). */
  durationSec: number | null
  previewUrl: string | null
}

/** Duration of a video file from a detached <video> element's metadata (no upload needed). */
function videoDuration(file: File): Promise<number | null> {
  return new Promise((resolve) => {
    const url = URL.createObjectURL(file)
    const v = document.createElement('video')
    v.preload = 'metadata'
    v.muted = true
    const done = (d: number | null) => { URL.revokeObjectURL(url); v.removeAttribute('src'); v.load(); resolve(d) }
    v.onloadedmetadata = () => done(Number.isFinite(v.duration) ? v.duration : null)
    v.onerror = () => done(null)
    window.setTimeout(() => done(null), 15000)
    v.src = url
  })
}

/** "19:30" (time input) → "7:30 PM" (the API's start_time format). */
function to12h(hhmm: string): string {
  const [h, m] = hhmm.split(':').map(Number)
  if (!Number.isFinite(h) || !Number.isFinite(m)) return ''
  return `${h % 12 === 0 ? 12 : h % 12}:${String(m).padStart(2, '0')} ${h >= 12 ? 'PM' : 'AM'}`
}

export default function NewAnalysis() {
  const { jobs, gamesById, refreshJobs, addAnalysis } = useStore()
  const nav = useNavigate()
  const fileRef = useRef<HTMLInputElement>(null)
  const [picked, setPicked] = useState<Picked | null>(null)
  const [checking, setChecking] = useState(false)
  const [fileErr, setFileErr] = useState<string | null>(null)
  const [drag, setDrag] = useState(false)
  const [meta, setMeta] = useState({ home: '', away: '', sport: '', league: '', venue: '', camera: '', date: todayIso(), time: '' })
  const [progress, setProgress] = useState<UploadProgress | null>(null)
  const [submitErr, setSubmitErr] = useState<string | null>(null)
  const abortRef = useRef<AbortController | null>(null)
  const pickSeq = useRef(0) // drops a stale duration check when another file is picked meanwhile
  const uploading = progress !== null

  useEffect(() => { void refreshJobs() }, [refreshJobs])
  // Leaving the page cancels an upload in flight.
  useEffect(() => () => abortRef.current?.abort(), [])
  useEffect(() => () => { if (picked?.previewUrl) URL.revokeObjectURL(picked.previewUrl) }, [picked])

  const [limits, setLimits] = useState({ ...DEFAULT_LIMITS, direct: false })
  useEffect(() => {
    void uploadCaps().then((c) => setLimits({ maxBytes: c.maxUploadMb * 1024 ** 2, maxVideoSec: c.maxVideoSec, direct: c.directUpload }))
  }, [])
  const take = async (f: File | undefined) => {
    const seq = ++pickSeq.current
    setFileErr(null); setSubmitErr(null); setPicked(null); setChecking(false)
    if (fileRef.current) fileRef.current.value = ''
    if (!f) return
    const ext = f.name.split('.').pop()?.toLowerCase() ?? ''
    const type = ACCEPT.includes(f.type) ? f.type : !f.type || f.type === 'application/octet-stream' ? TYPES[ext] : undefined
    if (!type) { setFileErr(`Unsupported file type (${f.type || ext || 'unknown'}). Use MP4, MOV, JPG or PNG.`); return }
    if (f.size > limits.maxBytes) { setFileErr(`File is ${mbLabel(f.size)}; the limit is ${gbLabel(limits.maxBytes)}.`); return }
    if (f.size === 0) { setFileErr('File is empty.'); return }
    // Re-wrap with the inferred type so the multipart part carries a Content-Type the API accepts.
    const file = f.type === type ? f : new File([f], f.name, { type, lastModified: f.lastModified })
    if (type.startsWith('image/')) {
      setPicked({ file, kind: 'image', durationSec: null, previewUrl: URL.createObjectURL(file) })
      return
    }
    setChecking(true)
    const d = await videoDuration(file)
    if (seq !== pickSeq.current) return
    setChecking(false)
    if (d !== null && d > limits.maxVideoSec) { setFileErr(`Video is ${(d / 3600).toFixed(1)} h; the limit is ${hoursLabel(limits.maxVideoSec)}. Trim it and try again.`); return }
    setPicked({ file, kind: 'video', durationSec: d, previewUrl: null })
  }
  const onDrop = (e: DragEvent) => { e.preventDefault(); setDrag(false); if (!uploading) void take(e.dataTransfer.files[0]) }
  const set = (k: keyof typeof meta) => (v: string) => setMeta((m) => ({ ...m, [k]: v }))

  const missing = [!picked && 'a file', !meta.home.trim() && 'home team', !meta.away.trim() && 'away team', !meta.sport.trim() && 'sport'].filter(Boolean) as string[]

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    if (!picked || missing.length || uploading) return
    setSubmitErr(null)
    const ctrl = new AbortController()
    abortRef.current = ctrl
    setProgress({ loaded: 0, total: picked.file.size })
    try {
      const a = await api.createAnalysis(
        picked.file,
        { home: meta.home, away: meta.away, sport: meta.sport, league: meta.league, venue: meta.venue, camera: meta.camera, date: meta.date, startTime: meta.time ? to12h(meta.time) : undefined },
        setProgress,
        ctrl.signal,
      )
      addAnalysis(a)
      nav(`/games/${a.game.id}`)
    } catch (err) {
      if (!(err instanceof ApiError && err.code === 'aborted')) setSubmitErr(errorMessage(err))
      setProgress(null)
    } finally {
      abortRef.current = null
    }
  }

  const pct = progress && progress.total ? Math.min(100, (progress.loaded / progress.total) * 100) : 0
  const sent = progress !== null && progress.total > 0 && progress.loaded >= progress.total

  return (
    <div className="flex flex-col gap-6">
      <div>
        <Link to="/" className="text-xs text-text-secondary hover:text-text-primary">← Games</Link>
        <h1 className="mt-1 font-display text-xl font-bold uppercase tracking-wide">New Analysis</h1>
      </div>

      <form onSubmit={submit} className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <div
          onDragOver={(e) => { e.preventDefault(); if (!uploading) setDrag(true) }}
          onDragLeave={() => setDrag(false)}
          onDrop={onDrop}
          className={`flex min-h-72 flex-col items-center justify-center gap-2 rounded-xl border border-dashed bg-bg-card p-6 text-center transition-colors lg:col-span-2 ${drag ? 'border-text-primary' : 'border-border-subtle'}`}
        >
          {picked?.previewUrl && (
            <div className="mb-2 aspect-video w-full max-w-sm overflow-hidden rounded-lg border border-border-subtle">
              <FrameThumb imageUrl={picked.previewUrl} label={`Preview of ${picked.file.name}`} />
            </div>
          )}
          <div className="font-display text-base font-bold uppercase tracking-wide">{picked ? 'File selected' : 'Drop a video or image'}</div>
          <div className="text-xs text-text-muted">MP4 / MOV up to {hoursLabel(limits.maxVideoSec)} · JPG / PNG · {gbLabel(limits.maxBytes)} max</div>
          <button type="button" className={`${btnGhost} mt-2`} disabled={uploading} onClick={() => fileRef.current?.click()}>{picked ? 'Replace…' : 'Choose File…'}</button>
          <input ref={fileRef} type="file" accept={[...ACCEPT, '.mp4', '.mov', '.jpg', '.jpeg', '.png'].join(',')} className="hidden" onChange={(e) => void take(e.target.files?.[0])} />
          {checking && <div className="mt-3 inline-flex items-center gap-2 text-xs text-text-secondary"><Spinner />Checking…</div>}
          {picked && (
            <div className="mt-3 flex flex-wrap items-center justify-center gap-2 text-xs">
              <Pill tone="green">{picked.kind}</Pill>
              <span className="max-w-xs truncate text-text-primary">{picked.file.name}</span>
              <span className="text-text-muted">{mbLabel(picked.file.size)}</span>
              {picked.kind === 'video' && <span className="text-text-muted">{picked.durationSec !== null ? clockLabel(picked.durationSec) : 'length unknown'}</span>}
              {!uploading && <button type="button" className="text-text-secondary underline hover:text-text-primary" onClick={() => setPicked(null)}>remove</button>}
            </div>
          )}
          {fileErr && <div className="mt-3 text-xs text-red-400">{fileErr}</div>}
        </div>

        <fieldset disabled={uploading} className={`${cardCls} flex flex-col gap-3 p-5`}>
          <legend className="sr-only">Game details</legend>
          <div className="font-display text-base font-bold uppercase tracking-wide">Details</div>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Home team" required><input value={meta.home} onChange={(e) => set('home')(e.target.value)} maxLength={120} required className={inputCls} /></Field>
            <Field label="Away team" required><input value={meta.away} onChange={(e) => set('away')(e.target.value)} maxLength={120} required className={inputCls} /></Field>
            <Field label="Sport" required>
              <input value={meta.sport} onChange={(e) => set('sport')(e.target.value)} list="ss-sports" maxLength={60} required className={inputCls} />
            </Field>
            <Field label="Camera">
              <input value={meta.camera} onChange={(e) => set('camera')(e.target.value)} list="ss-cameras" maxLength={60} className={inputCls} />
            </Field>
            <Field label="League"><input value={meta.league} onChange={(e) => set('league')(e.target.value)} maxLength={120} className={inputCls} /></Field>
            <Field label="Venue"><input value={meta.venue} onChange={(e) => set('venue')(e.target.value)} maxLength={120} className={inputCls} /></Field>
            <Field label="Date"><input type="date" value={meta.date} onChange={(e) => set('date')(e.target.value || todayIso())} className={inputCls} /></Field>
            <Field label="Start time"><input type="time" value={meta.time} onChange={(e) => set('time')(e.target.value)} className={inputCls} /></Field>
          </div>
          <datalist id="ss-sports">{SPORTS.map((s) => <option key={s} value={s} />)}</datalist>
          <datalist id="ss-cameras">{CAMERAS.map((c) => <option key={c} value={c} />)}</datalist>
        </fieldset>

        <div className="flex flex-col gap-3 lg:col-span-3">
          {progress ? (
            <div className={`${cardCls} flex flex-col gap-2`}>
              <div className="flex items-center gap-3 text-xs">
                {sent ? <span className="inline-flex items-center gap-2 text-text-primary"><Spinner />Queuing…</span>
                  : <span className="truncate text-text-primary">Uploading {picked?.file.name}</span>}
                <span className="ml-auto tabular-nums text-text-secondary">{mbLabel(progress.loaded)} / {mbLabel(progress.total)} · {Math.floor(pct)}%</span>
                <button type="button" className={btnGhostRow} onClick={() => abortRef.current?.abort()}>Cancel</button>
              </div>
              <div className="h-2 rounded-sm bg-border-subtle" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.floor(pct)} aria-label="Upload progress">
                <div className="h-2 rounded-sm bg-text-primary transition-[width]" style={{ width: `${pct}%` }} />
              </div>
            </div>
          ) : (
            <div className="flex flex-wrap items-center gap-3">
              <button type="submit" className={btnPrimary} disabled={missing.length > 0 || checking}>Run Analysis</button>
              {missing.length > 0 && <span className="text-xs text-text-muted">Needs {missing.join(', ')}</span>}
            </div>
          )}
          {submitErr && <div className="text-xs text-red-400" role="alert">{submitErr}</div>}
        </div>
      </form>

      <section>
        <h2 className="mb-2 font-display text-base font-bold uppercase tracking-wide">Recent</h2>
        {jobs.length === 0 ? (
          <div className="text-sm text-text-muted">No analyses yet.</div>
        ) : (
          <ul className="divide-y divide-border-subtle overflow-hidden rounded-xl border border-border-subtle bg-bg-card">
            {jobs.slice(0, 10).map((j) => <RecentRow key={j.id} job={j} poster={(j.gameId && gamesById[j.gameId]?.posterUrl) || j.posterUrl} />)}
          </ul>
        )}
      </section>
    </div>
  )
}

function Field({ label, required = false, children }: { label: string; required?: boolean; children: ReactNode }) {
  return (
    <label className="flex min-w-0 flex-col gap-1">
      <Eyebrow>{label}{required && <span className="text-accent"> *</span>}</Eyebrow>
      {children}
    </label>
  )
}

function RecentRow({ job: j, poster }: { job: Job; poster: string | null | undefined }) {
  const active = jobActive(j)
  const st = active ? jobStatusLine(j) : null
  const pct = st ? (st.progress ?? 0) * 100 : j.totalFrames ? Math.min(100, (j.doneFrames / j.totalFrames) * 100) : 0
  const body = (
    <div className="flex items-center gap-3 px-4 py-2 text-xs">
      <div className="aspect-video w-16 shrink-0 overflow-hidden rounded border border-border-subtle">
        <FrameThumb imageUrl={poster} pending={jobActive(j)} label={`Poster for ${j.label}`} />
      </div>
      <div className="min-w-0 flex-1">
        <div className="truncate text-text-primary">{j.label}</div>
        <div className="text-[11px] text-text-muted">{dateTimeLabel(j.createdAt)}</div>
      </div>
      <div className="w-56 shrink-0">
        <div className="flex items-center justify-between gap-2">
          {st && <span className={`inline-flex min-w-0 items-center gap-1.5 ${st.stale ? 'text-text-muted' : 'text-yellow-400'}`} title={st.text}><Spinner /><span className="truncate">{st.text}</span></span>}
          {j.status === 'done' && <span className="text-green-400">complete</span>}
          {j.status === 'failed' && <span className="truncate text-red-400" title={j.error ?? undefined}>failed{j.error ? `: ${j.error}` : ''}</span>}
          {j.status === 'cancelled' && <span className="text-text-muted">cancelled</span>}
          {!active && <span className="tabular-nums text-text-secondary">{j.doneFrames} / {j.totalFrames}</span>}
        </div>
        <div className="mt-1 h-1 rounded-sm bg-border-subtle"><div className="h-1 rounded-sm bg-text-secondary" style={{ width: `${pct}%` }} /></div>
      </div>
      <div className="w-24 shrink-0 text-right text-text-secondary">
        {j.status === 'done' ? (j.flaggedFrames ? `${j.flaggedFrames} flagged` : 'no defects') : ''}
      </div>
    </div>
  )
  return (
    <li className="transition-colors hover:bg-bg-card-hover">
      {j.gameId ? <Link to={`/games/${j.gameId}`} className="block focus:outline-none focus:ring-1 focus:ring-inset focus:ring-accent" aria-label={`Open match analysis for ${j.label}`}>{body}</Link> : body}
    </li>
  )
}

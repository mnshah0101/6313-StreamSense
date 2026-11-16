import { useCallback, useEffect, useId, useRef, useState, type ReactNode } from 'react'
import { api, errorMessage } from '../api'
import type { GpuLive, StatusRange, SystemStatus } from '../data/types'
import { usePoll } from '../store'
import { BarChart, ChartCard, LineChart, type Series } from '../components/charts'
import { Segmented, cardCls } from '../components/ui'

const REFRESH_MS = 15000
const RANGES: { value: StatusRange; label: string }[] = [
  { value: '24h', label: '24h' },
  { value: '7d', label: '7d' },
  { value: '30d', label: '30d' },
]
/** Label every n-th bucket: 24h hourly -> every 6 h; 7d 6-hourly -> daily; 30d daily -> weekly. */
const X_TICK_EVERY: Record<StatusRange, number> = { '24h': 6, '7d': 4, '30d': 7 }

/* ---------- formatting (plain language; "—" for no data) ---------- */

const DASH = '—'
const trim = (x: number, d: number) => String(+x.toFixed(d))

function fmtSpeed(x: number | null): string {
  if (x === null) return DASH
  return `${x >= 10 ? Math.round(x) : trim(x, 1)}×`
}
function fmtLatency(ms: number | null): string {
  if (ms === null) return DASH
  if (ms < 100) return `${Math.round(ms)} ms`
  const s = ms / 1000
  return `${s >= 10 ? Math.round(s) : trim(s, s < 1 ? 2 : 1)} s`
}
function fmtDuration(sec: number | null): string {
  if (sec === null) return DASH
  if (sec < 60) return `${Math.round(sec)} s`
  if (sec < 3600) return `${trim(sec / 60, sec < 600 ? 1 : 0)} min`
  if (sec < 86400) return `${trim(sec / 3600, 1)} h`
  return `${trim(sec / 86400, 1)} d`
}
function fmtHours(h: number | null): string {
  if (h === null) return DASH
  if (h === 0) return '0 h'
  if (h < 1) return `${Math.max(1, Math.round(h * 60))} min`
  return `${trim(h, h < 10 ? 1 : 0)} h`
}
function fmtCount(n: number | null): string {
  if (n === null) return DASH
  if (n < 10000) return n.toLocaleString('en-US', { maximumFractionDigits: 0 })
  if (n < 1e6) return `${trim(n / 1e3, n < 1e5 ? 1 : 0)}K`
  return `${trim(n / 1e6, 1)}M`
}
const fmtPct = (r: number | null) => (r === null ? DASH : `${trim(r * 100, r < 0.995 && r > 0.98 ? 1 : 0)}%`)
const plural = (n: number, w: string) => `${fmtCount(n)} ${w}${n === 1 ? '' : 's'}`

/** "1 h of video ≈ 5 min" from × real time. */
function hourTakes(speedX: number | null): string | null {
  if (!speedX) return null
  return `1 h of video ≈ ${fmtDuration(3600 / speedX)}`
}

/** Known GPU memory sizes for the "of 24 GB" hint. */
function gpuMemGb(hw: string): number | null {
  const h = hw.toUpperCase()
  if (/\bL4\b/.test(h) || h.includes('A10G') || h.includes('A10')) return 24
  if (h.includes('T4')) return 16
  if (h.includes('L40')) return 48
  if (h.includes('H100')) return 80
  if (h.includes('A100')) return h.includes('80') ? 80 : 40
  return null
}

/* ---------- time labels for the chosen range ---------- */

function timeFormats(range: StatusRange, times: Date[], bucketSec: number) {
  const hour = (d: Date) => d.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' })
  const day = (d: Date) => d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
  const xFormat = range === '24h'
    ? (d: Date) => d.toLocaleTimeString('en-US', { hour: 'numeric' })
    : range === '7d'
      ? (d: Date) => d.toLocaleDateString('en-US', { weekday: 'short' })
      : day
  const timeLabel = (i: number) => {
    const a = times[i]
    const b = new Date(a.getTime() + bucketSec * 1000)
    if (range === '30d') return a.toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' })
    return `${day(a)}, ${hour(a)} – ${hour(b)}`
  }
  return { xFormat, timeLabel }
}

/* ---------- small pieces ---------- */

/** Dotted-underlined term with an explanation on hover / keyboard focus. */
function Hint({ tip, children, align = 'left' }: { tip: ReactNode; children: ReactNode; align?: 'left' | 'right' }) {
  const id = useId()
  return (
    <span tabIndex={0} aria-describedby={id} className="group relative inline-flex cursor-help underline decoration-text-muted decoration-dotted underline-offset-4 focus:outline-none focus-visible:ring-1 focus-visible:ring-accent rounded-sm">
      {children}
      <span
        id={id} role="tooltip"
        className={`pointer-events-none invisible absolute top-full z-30 mt-1.5 w-60 rounded-lg border border-border-subtle bg-bg-primary px-3 py-2 text-left text-xs font-normal normal-case leading-relaxed tracking-normal text-text-secondary opacity-0 shadow-lg transition-opacity group-hover:visible group-hover:opacity-100 group-focus:visible group-focus:opacity-100 ${align === 'right' ? 'right-0' : 'left-0'}`}
      >
        {tip}
      </span>
    </span>
  )
}

const TIPS = {
  speed: '× real time: how many seconds of video are analyzed per second. 12× means an hour of video takes about 5 minutes. Median across jobs.',
  latency: 'How long the model takes to look at one frame. The typical frame (p50, median); p95 means 95% of frames are faster than that.',
  queue: 'How long a video waits for a free GPU before analysis starts. Typical wait (p50); p95 means 95% of videos waited less.',
  video: 'Total length of video analyzed in this range.',
  success: 'Share of analysis jobs that finished without an error.',
  throughput: 'Frames analyzed per minute by one job (fps × 60). Median across jobs.',
  busy: 'Share of this time range the GPU spent analyzing video.',
  mem: (hw: string) => {
    const cap = gpuMemGb(hw)
    return `Highest GPU memory used by a job${cap ? `, of ${cap} GB on ${hw}` : ''}.`
  },
}

function Dot({ color }: { color: string }) {
  return <span className="inline-block h-2 w-2 shrink-0 rounded-full" style={{ background: color }} aria-hidden />
}

const STATE: Record<string, { color: string; label: string }> = {
  busy: { color: 'var(--color-good)', label: 'Busy' },
  idle: { color: 'var(--color-text-muted)', label: 'Idle' },
  starting: { color: 'var(--color-sev-2)', label: 'Starting' },
}

function GpuRow({ g }: { g: GpuLive }) {
  const st = STATE[g.state] ?? { color: 'var(--color-text-muted)', label: g.state }
  const pct = g.jobProgress === null ? null : Math.round(g.jobProgress * 100)
  return (
    <li className="flex min-w-0 flex-col gap-1.5 rounded-lg bg-bg-primary px-3 py-2" title={g.modelId ? `Model ${g.modelId} · worker ${g.id}` : `Worker ${g.id}`}>
      <div className="flex items-center justify-between gap-3 text-xs">
        <span className="truncate font-medium text-text-primary">{g.hardware}</span>
        <span className="inline-flex shrink-0 items-center gap-1.5 text-text-secondary"><Dot color={st.color} />{st.label}</span>
      </div>
      {g.state === 'busy' && (
        <div className="flex items-center gap-2 text-[11px] text-text-muted">
          <span className="min-w-0 flex-1 truncate">{g.jobLabel ?? 'Analyzing'}</span>
          {pct !== null && (
            <>
              <span className="h-1 w-16 shrink-0 overflow-hidden rounded-full bg-border-subtle" role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100} aria-label="Job progress">
                <span className="block h-full rounded-full" style={{ width: `${pct}%`, background: 'var(--color-series-1)' }} />
              </span>
              <span className="w-8 shrink-0 text-right tabular-nums text-text-secondary">{pct}%</span>
            </>
          )}
        </div>
      )}
    </li>
  )
}

function Tile({ label, tip, value, sub }: { label: string; tip: string; value: string; sub?: ReactNode }) {
  return (
    <div className={cardCls}>
      <div className="text-xs text-text-secondary"><Hint tip={tip}>{label}</Hint></div>
      <div className="mt-2 text-3xl font-semibold leading-none text-text-primary">{value}</div>
      <div className="mt-2 min-h-4 text-xs text-text-muted">{sub}</div>
    </div>
  )
}

/* ---------- page ---------- */

export default function Status() {
  const [range, setRange] = useState<StatusRange>('24h')
  const [data, setData] = useState<SystemStatus | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const latest = useRef(0)

  const load = useCallback(async (r: StatusRange) => {
    const seq = ++latest.current
    setLoading(true)
    try {
      const d = await api.status(r)
      if (seq !== latest.current) return
      setData(d); setErr(null)
    } catch (e) {
      if (seq === latest.current) setErr(errorMessage(e))
    } finally {
      if (seq === latest.current) setLoading(false)
    }
  }, [])

  useEffect(() => { void load(range) }, [range, load])
  usePoll(() => load(range), REFRESH_MS)
  // Catch up as soon as the tab is visible again (polling pauses while hidden).
  useEffect(() => {
    const onVis = () => { if (!document.hidden) void load(range) }
    document.addEventListener('visibilitychange', onVis)
    return () => document.removeEventListener('visibilitychange', onVis)
  }, [range, load])

  // Refetch keeps the frame: the old render dims while a new range loads.
  const stale = loading && data !== null && data.range !== range

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-center gap-4">
        <h1 className="font-display text-xl font-bold uppercase tracking-wide">Status</h1>
        <Segmented value={range} options={RANGES} onChange={setRange} />
        <div className="ml-auto text-[11px] text-text-muted" aria-live="polite">
          {err ? <span className="text-red-400">{err}</span> : data ? `Updated ${new Date(data.generatedAt).toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', second: '2-digit' })}` : null}
        </div>
      </div>

      {!data ? (
        !err && <div className="text-sm text-text-muted">Loading…</div>
      ) : (
        <div className={`flex flex-col gap-6 transition-opacity ${stale ? 'opacity-50' : ''}`}>
          <Live data={data} />
          <Tiles data={data} />
          <Charts data={data} range={data.range} />
          <GpuTable data={data} />
        </div>
      )}
    </div>
  )
}

function Live({ data }: { data: SystemStatus }) {
  const { gpus, queued, running, oldestWaitSec } = data.live
  return (
    <div className="grid gap-4 md:grid-cols-[2fr_1fr]">
      <section className={cardCls} aria-label="GPUs online">
        <div className="mb-3 flex items-baseline gap-2">
          <span className="text-2xl font-semibold leading-none">{gpus.length}</span>
          <span className="text-xs text-text-secondary">GPU{gpus.length === 1 ? '' : 's'} online</span>
        </div>
        {gpus.length === 0 ? (
          <div className="flex items-center gap-2 text-xs text-text-muted"><Dot color="var(--color-text-muted)" />No GPU online</div>
        ) : (
          <ul className="grid gap-2 sm:grid-cols-2">
            {gpus.map((g) => <GpuRow key={g.id} g={g} />)}
          </ul>
        )}
      </section>
      <section className={cardCls} aria-label="Queue">
        <div className="mb-3 flex items-baseline gap-2">
          <span className="text-2xl font-semibold leading-none">{queued}</span>
          <span className="text-xs text-text-secondary">waiting</span>
          <span className="ml-3 text-2xl font-semibold leading-none">{running}</span>
          <span className="text-xs text-text-secondary">running</span>
        </div>
        <div className="text-xs text-text-muted">
          {queued > 0 && oldestWaitSec !== null ? `Oldest waiting ${fmtDuration(oldestWaitSec)}` : 'Nothing waiting'}
        </div>
      </section>
    </div>
  )
}

function Tiles({ data }: { data: SystemStatus }) {
  const s = data.summary
  const total = s.jobsDone + s.jobsFailed
  return (
    <div className="grid grid-cols-2 gap-4 md:grid-cols-3 xl:grid-cols-5">
      <Tile label="Speed" tip={TIPS.speed} value={s.speedX === null ? DASH : `${fmtSpeed(s.speedX)} real time`} sub={hourTakes(s.speedX)} />
      <Tile label="Per-frame latency" tip={TIPS.latency} value={fmtLatency(s.latencyP50Ms)} sub={s.latencyP95Ms !== null && `p95 ${fmtLatency(s.latencyP95Ms)}`} />
      <Tile label="Queue wait" tip={TIPS.queue} value={fmtDuration(s.queueWaitP50Sec)} sub={s.queueWaitP95Sec !== null && `p95 ${fmtDuration(s.queueWaitP95Sec)}`} />
      <Tile label="Video analyzed" tip={TIPS.video} value={fmtHours(s.videoHours)} sub={`${fmtCount(s.frames)} frames · ${plural(s.jobsDone, 'job')}`} />
      <Tile
        label="Success" tip={TIPS.success} value={fmtPct(s.successRate)}
        sub={total === 0 ? null : s.jobsFailed === 0 ? (
          <span className="inline-flex items-center gap-1.5"><IconCheck color="var(--color-good)" />No failures</span>
        ) : (
          <span className="inline-flex items-center gap-1.5"><IconWarn color="var(--color-sev-2)" />{fmtCount(s.jobsFailed)} failed</span>
        )}
      />
    </div>
  )
}

function Charts({ data, range }: { data: SystemStatus; range: StatusRange }) {
  const times = data.series.map((p) => new Date(p.t))
  const { xFormat, timeLabel } = timeFormats(range, times, data.bucketSec)
  const col = (k: keyof (typeof data.series)[number], f: (v: number) => number = (v) => v) =>
    data.series.map((p) => (p[k] === null ? null : f(p[k] as number)))
  const blue = 'var(--color-series-1)'
  const common = { times, xFormat, timeLabel, xTickEvery: X_TICK_EVERY[range] }

  const speed: Series[] = [{ key: 'speed', name: 'Speed', color: blue, values: col('speedX') }]
  const thr: Series[] = [{ key: 'fpm', name: 'Frames/min', color: blue, values: col('fps', (v) => v * 60) }]
  const lat: Series[] = [
    { key: 'p50', name: 'p50', color: blue, values: col('latencyP50Ms', (v) => v / 1000) },
    { key: 'p95', name: 'p95', color: 'var(--color-series-2)', values: col('latencyP95Ms', (v) => v / 1000) },
  ]
  const wait: Series[] = [{ key: 'wait', name: 'Queue wait', color: blue, values: col('queueWaitSec') }]
  const vid: Series[] = [{ key: 'video', name: 'Video analyzed', color: blue, values: col('videoHours') }]

  const axisSec = (v: number) => (v === 0 ? '0' : `${trim(v, v < 1 ? 2 : 1)}s`)
  const axisDur = (v: number) => (v === 0 ? '0' : v < 60 ? `${trim(v, 1)}s` : v < 3600 ? `${trim(v / 60, 1)}m` : `${trim(v / 3600, 1)}h`)
  const axisHours = (v: number) => (v === 0 ? '0' : v < 1 ? `${trim(v * 60, 0)}m` : `${trim(v, 1)}h`)
  const secValue = (v: number) => fmtLatency(v * 1000)

  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <ChartCard title={<Hint tip={TIPS.speed}>Speed (× real time)</Hint>} hint="Higher is faster" times={times} series={speed} valueFormat={(v) => `${fmtSpeed(v)} real time`} timeLabel={timeLabel}>
        <LineChart {...common} series={speed} label="Speed over time, times real time" yFormat={(v) => `${trim(v, 1)}×`} valueFormat={(v) => `${fmtSpeed(v)} real time`} />
      </ChartCard>
      <ChartCard title={<Hint tip={TIPS.throughput}>Throughput (frames/min)</Hint>} hint="Higher is faster" times={times} series={thr} valueFormat={fmtCount} timeLabel={timeLabel}>
        <LineChart {...common} series={thr} label="Frames analyzed per minute over time" yFormat={fmtCount} />
      </ChartCard>
      <ChartCard title={<Hint tip={TIPS.latency}>Per-frame latency (s)</Hint>} hint="Lower is faster" times={times} series={lat} valueFormat={secValue} timeLabel={timeLabel}>
        <LineChart {...common} series={lat} label="Per-frame latency over time, p50 and p95, seconds" yFormat={axisSec} valueFormat={secValue} />
      </ChartCard>
      <ChartCard title={<Hint tip={TIPS.queue}>Queue wait (s)</Hint>} hint="Typical wait before a GPU picks a video up" times={times} series={wait} valueFormat={fmtDuration} timeLabel={timeLabel}>
        <LineChart {...common} series={wait} label="Typical queue wait over time" yFormat={axisDur} valueFormat={fmtDuration} />
      </ChartCard>
      <ChartCard title={<Hint tip={TIPS.video}>Video analyzed (h)</Hint>} hint={`Per ${range === '24h' ? 'hour' : range === '7d' ? '6 hours' : 'day'}`} times={times} series={vid} valueFormat={fmtHours} timeLabel={timeLabel}>
        <BarChart {...common} series={vid} label="Hours of video analyzed per time bucket" yFormat={axisHours} valueFormat={fmtHours} />
      </ChartCard>
    </div>
  )
}

function GpuTable({ data }: { data: SystemStatus }) {
  const rows = data.byGpu
  const th = 'px-3 py-2 font-normal text-right'
  return (
    <section className={cardCls} aria-label="By GPU">
      <h3 className="mb-3 text-sm font-medium">By GPU</h3>
      {rows.length === 0 ? (
        <div className="py-4 text-center text-xs text-text-muted">No finished jobs in this range</div>
      ) : (
        <div>
          <table className="w-full text-xs tabular-nums">
            <thead className="text-text-muted">
              <tr>
                <th className="py-2 pr-3 text-left font-normal">GPU</th>
                <th className={th}>Jobs</th>
                <th className={th}><Hint tip={TIPS.speed} align="right">Speed</Hint></th>
                <th className={th}><Hint tip={TIPS.throughput} align="right">Frames/min</Hint></th>
                <th className={th}><Hint tip={TIPS.latency} align="right">Latency p50 / p95</Hint></th>
                <th className={th}><Hint tip="Highest GPU memory used by a job, out of the card's total (an L4 has 24 GB)." align="right">Peak memory</Hint></th>
                <th className={`${th} pr-0`}><Hint tip={TIPS.busy} align="right">Busy</Hint></th>
              </tr>
            </thead>
            <tbody className="text-text-primary">
              {rows.map((g) => {
                const cap = gpuMemGb(g.hardware)
                return (
                  <tr key={g.hardware} className="border-t border-border-subtle">
                    <td className="py-2 pr-3 text-left font-medium">{g.hardware}</td>
                    <td className="px-3 py-2 text-right">{fmtCount(g.jobs)}</td>
                    <td className="px-3 py-2 text-right">{fmtSpeed(g.speedX)}</td>
                    <td className="px-3 py-2 text-right">{g.fps === null ? DASH : fmtCount(g.fps * 60)}</td>
                    <td className="px-3 py-2 text-right">{fmtLatency(g.latencyP50Ms)} <span className="text-text-muted">/ {fmtLatency(g.latencyP95Ms)}</span></td>
                    <td className="px-3 py-2 text-right" title={TIPS.mem(g.hardware)}>
                      {g.peakGpuMemGb === null ? DASH : `${trim(g.peakGpuMemGb, 1)} GB`}
                      {g.peakGpuMemGb !== null && cap && <span className="text-text-muted"> of {cap}</span>}
                    </td>
                    <td className="py-2 pl-3 text-right">{g.busyPct === null ? DASH : `${Math.round(g.busyPct)}%`}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}

function IconCheck({ color }: { color: string }) {
  return <svg viewBox="0 0 16 16" className="h-3.5 w-3.5" fill="none" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden><path d="M3.5 8.5l3 3 6-7" /></svg>
}
function IconWarn({ color }: { color: string }) {
  return <svg viewBox="0 0 16 16" className="h-3.5 w-3.5" fill="none" stroke={color} strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" aria-hidden><path d="M8 2.5l6 11H2z" /><path d="M8 7v3M8 12h0" /></svg>
}

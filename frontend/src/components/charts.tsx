/**
 * Hand-rolled SVG time charts (no chart dependency). Follows the dataviz rules: one y-axis,
 * 2px lines, hairline recessive grid, crosshair + tooltip (lines) / per-bar hover (bars),
 * a legend only for 2+ series, text in text tokens (never series colors), gaps for nulls.
 */
import { useEffect, useId, useRef, useState, type KeyboardEvent, type PointerEvent, type ReactNode } from 'react'

export interface Series {
  key: string
  name: string
  /** CSS color, e.g. "var(--color-series-1)". Only marks wear it. */
  color: string
  /** One value per time bucket; null = no data (a gap, never a zero). */
  values: (number | null)[]
}

interface TimeChartProps {
  times: Date[]
  series: Series[]
  /** Y-axis tick label. */
  yFormat: (v: number) => string
  /** Tooltip / table value (defaults to yFormat). */
  valueFormat?: (v: number) => string
  /** X-axis tick label. */
  xFormat: (d: Date) => string
  /** Tooltip / table time label for bucket i. */
  timeLabel: (i: number) => string
  /** Label every n-th bucket on the x axis. */
  xTickEvery: number
  /** Accessible name. */
  label: string
  /** Shown over the plot when every value is null / zero. */
  emptyText?: string
  height?: number
}

const PLOT_TOP = 10
const X_BAND = 22 // x-axis label band (inside the SVG, so the card never clips it)
const TICK_FONT = 10

function useWidth<T extends HTMLElement>() {
  const ref = useRef<T>(null)
  const [w, setW] = useState(0)
  useEffect(() => {
    const el = ref.current
    if (!el) return
    const ro = new ResizeObserver(([e]) => setW(Math.floor(e.contentRect.width)))
    ro.observe(el)
    return () => ro.disconnect()
  }, [])
  return [ref, w] as const
}

/** 0..max in ~4 clean steps (1, 2, 2.5, 5 x 10^n). */
function niceTicks(max: number): number[] {
  if (!(max > 0)) return [0, 1]
  const raw = max / 4
  const mag = 10 ** Math.floor(Math.log10(raw))
  const step = ([1, 2, 2.5, 5, 10].find((m) => m * mag >= raw) ?? 10) * mag
  const out: number[] = []
  for (let v = 0; v <= max + step * 1e-9; v += step) out.push(+v.toFixed(10))
  if (out[out.length - 1] < max) out.push(+(out[out.length - 1] + step).toFixed(10))
  return out
}

function geometry(width: number, height: number, series: Series[], yFormat: (v: number) => string, rightPad: number, n: number) {
  const max = Math.max(0, ...series.flatMap((s) => s.values.filter((v): v is number => v !== null)))
  const ticks = niceTicks(max)
  const top = ticks[ticks.length - 1]
  const left = Math.max(...ticks.map((t) => yFormat(t).length)) * 6 + 10
  const plotW = Math.max(10, width - left - rightPad)
  const plotH = height - PLOT_TOP - X_BAND
  const band = plotW / Math.max(1, n)
  return {
    ticks, left, plotW, plotH, band,
    x: (i: number) => left + (i + 0.5) * band,
    y: (v: number) => PLOT_TOP + plotH - (v / top) * plotH,
    baseline: PLOT_TOP + plotH,
    isEmpty: max <= 0,
  }
}

type Geo = ReturnType<typeof geometry>

function Axes({ g, width, times, xFormat, xTickEvery, yFormat }: { g: Geo; width: number; times: Date[]; xFormat: (d: Date) => string; xTickEvery: number; yFormat: (v: number) => string }) {
  const n = times.length
  // Label from the right edge back, so the most recent bucket always has a tick.
  const xs: number[] = []
  for (let i = n - 1; i >= 0; i -= xTickEvery) xs.push(i)
  return (
    <g fontSize={TICK_FONT} fill="var(--color-text-muted)" style={{ fontVariantNumeric: 'tabular-nums' }}>
      {g.ticks.map((t) => (
        <g key={t}>
          <line x1={g.left} x2={width - 4} y1={g.y(t)} y2={g.y(t)} stroke={t === 0 ? 'var(--color-chart-axis)' : 'var(--color-chart-grid)'} strokeWidth={1} shapeRendering="crispEdges" />
          <text x={g.left - 8} y={g.y(t)} dy="0.32em" textAnchor="end">{yFormat(t)}</text>
        </g>
      ))}
      {xs.map((i) => {
        const x = g.x(i)
        const anchor = x < g.left + 24 ? 'start' : x > width - 24 ? 'end' : 'middle'
        return <text key={i} x={x} y={g.baseline + 15} textAnchor={anchor}>{xFormat(times[i])}</text>
      })}
    </g>
  )
}

function Tooltip({ x, width, title, rows }: { x: number; width: number; title: string; rows: { key: string; color: string; name: string; value: string; mark: 'line' | 'rect' }[] }) {
  const flip = x > width / 2
  return (
    <div
      className="pointer-events-none absolute top-0 z-10 min-w-36 rounded-lg border border-border-subtle bg-bg-primary px-3 py-2 text-xs shadow-lg"
      style={flip ? { right: width - x + 10 } : { left: x + 10 }}
      role="status"
    >
      <div className="mb-1 whitespace-nowrap text-text-muted">{title}</div>
      {rows.map((r) => (
        <div key={r.key} className="flex items-center gap-2 whitespace-nowrap">
          {r.mark === 'line'
            ? <span className="inline-block h-0.5 w-3 rounded-full" style={{ background: r.color }} aria-hidden />
            : <span className="inline-block h-2 w-2 rounded-sm" style={{ background: r.color }} aria-hidden />}
          <span className="font-semibold text-text-primary tabular-nums">{r.value}</span>
          <span className="text-text-secondary">{r.name}</span>
        </div>
      ))}
    </div>
  )
}

/** Legend for 2+ series (line keys mirror the marks). */
export function Legend({ series }: { series: Pick<Series, 'key' | 'name' | 'color'>[] }) {
  if (series.length < 2) return null
  return (
    <div className="flex flex-wrap items-center gap-3 text-xs text-text-secondary">
      {series.map((s) => (
        <span key={s.key} className="inline-flex items-center gap-1.5">
          <span className="inline-block h-0.5 w-3.5 rounded-full" style={{ background: s.color }} aria-hidden />
          {s.name}
        </span>
      ))}
    </div>
  )
}

/** Keyboard: arrow keys move the readout like the pointer does. */
function useCursor(n: number, defaultIdx: () => number) {
  const [idx, setIdx] = useState<number | null>(null)
  const onKeyDown = (e: KeyboardEvent) => {
    if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight' && e.key !== 'Home' && e.key !== 'End') return
    e.preventDefault()
    setIdx((cur) => {
      const c = cur ?? defaultIdx()
      if (e.key === 'Home') return 0
      if (e.key === 'End') return n - 1
      return Math.min(n - 1, Math.max(0, c + (e.key === 'ArrowRight' ? 1 : -1)))
    })
  }
  return { idx, setIdx, keyProps: { tabIndex: 0, onKeyDown, onFocus: () => setIdx(defaultIdx()), onBlur: () => setIdx(null) } }
}

function lastIndex(series: Series[]): number {
  let last = -1
  for (const s of series) s.values.forEach((v, i) => { if (v !== null && i > last) last = i })
  return last >= 0 ? last : Math.max(0, (series[0]?.values.length ?? 1) - 1)
}

function EmptyNote({ children }: { children: ReactNode }) {
  return <div className="pointer-events-none absolute inset-0 flex items-center justify-center pb-6 text-xs text-text-muted">{children}</div>
}

/** Line chart over time buckets. Nulls break the line; a lone point is drawn as a dot. */
export function LineChart({ times, series, yFormat, valueFormat = yFormat, xFormat, timeLabel, xTickEvery, label, emptyText = 'No jobs in this range', height = 200 }: TimeChartProps) {
  const [ref, width] = useWidth<HTMLDivElement>()
  const n = times.length
  const multi = series.length > 1
  const { idx, setIdx, keyProps } = useCursor(n, () => lastIndex(series))
  const g = geometry(width, height, series, yFormat, multi ? 40 : 12, n)

  const onMove = (e: PointerEvent<SVGSVGElement>) => {
    const r = e.currentTarget.getBoundingClientRect()
    const i = Math.floor((e.clientX - r.left - g.left) / g.band)
    setIdx(i >= 0 && i < n ? i : null)
  }

  // Direct end-labels (2+ series) only when they don't collide; the legend always carries identity.
  const ends = series.map((s) => {
    let i = s.values.length - 1
    while (i >= 0 && s.values[i] === null) i--
    return i >= 0 ? { s, i, y: g.y(s.values[i] as number) } : null
  })
  const showEnds = multi && ends.every(Boolean) && ends.every((a, k) => ends.every((b, j) => j === k || Math.abs(a!.y - b!.y) >= 12))

  return (
    <div className="flex flex-col gap-2">
      <Legend series={series} />
      <div ref={ref} className="relative" style={{ height }}>
        {width > 0 && (
          <svg
            width={width} height={height} role="img" aria-label={label}
            className="block rounded-md focus:outline-none focus-visible:ring-1 focus-visible:ring-accent"
            onPointerMove={onMove} onPointerLeave={() => setIdx(null)}
            {...keyProps}
          >
            <Axes g={g} width={width} times={times} xFormat={xFormat} xTickEvery={xTickEvery} yFormat={yFormat} />
            {idx !== null && (
              <line x1={g.x(idx)} x2={g.x(idx)} y1={PLOT_TOP} y2={g.baseline} stroke="var(--color-text-muted)" strokeWidth={1} shapeRendering="crispEdges" />
            )}
            {series.map((s) => {
              const segs: string[] = []
              const dots: number[] = []
              let run: number[] = []
              const flush = () => {
                if (run.length === 1) dots.push(run[0])
                else if (run.length > 1) segs.push(run.map((i, k) => `${k ? 'L' : 'M'}${g.x(i).toFixed(1)},${g.y(s.values[i] as number).toFixed(1)}`).join(''))
                run = []
              }
              s.values.forEach((v, i) => { if (v === null) flush(); else run.push(i) })
              flush()
              return (
                <g key={s.key}>
                  {segs.map((d, k) => <path key={k} d={d} fill="none" stroke={s.color} strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />)}
                  {dots.map((i) => <circle key={i} cx={g.x(i)} cy={g.y(s.values[i] as number)} r={4} fill={s.color} stroke="var(--color-chart-surface)" strokeWidth={2} />)}
                </g>
              )
            })}
            {idx !== null && series.map((s) => {
              const v = s.values[idx]
              return v === null ? null : <circle key={s.key} cx={g.x(idx)} cy={g.y(v)} r={4.5} fill={s.color} stroke="var(--color-chart-surface)" strokeWidth={2} />
            })}
            {showEnds && ends.map((e) => e && (
              <text key={e.s.key} x={g.x(e.i) + 7} y={e.y} dy="0.32em" fontSize={TICK_FONT} fill="var(--color-text-secondary)">{e.s.name}</text>
            ))}
          </svg>
        )}
        {width > 0 && g.isEmpty && <EmptyNote>{emptyText}</EmptyNote>}
        {width > 0 && idx !== null && (
          <Tooltip
            x={g.x(idx)} width={width} title={timeLabel(idx)}
            rows={series.map((s) => ({ key: s.key, color: s.color, name: s.name, mark: 'line', value: s.values[idx] === null ? 'No jobs' : valueFormat(s.values[idx] as number) }))}
          />
        )}
      </div>
    </div>
  )
}

/** Column chart over time buckets (one series). Each column's band is its hover target. */
export function BarChart({ times, series, yFormat, valueFormat = yFormat, xFormat, timeLabel, xTickEvery, label, emptyText = 'No jobs in this range', height = 200 }: TimeChartProps) {
  const [ref, width] = useWidth<HTMLDivElement>()
  const n = times.length
  const s = series[0]
  const { idx, setIdx, keyProps } = useCursor(n, () => lastIndex(series))
  const g = geometry(width, height, series, yFormat, 12, n)
  const bw = Math.max(1, Math.min(24, g.band - 2)) // <= 24px, 2px surface gap between neighbors

  return (
    <div ref={ref} className="relative" style={{ height }}>
      {width > 0 && (
        <svg
          width={width} height={height} role="img" aria-label={label}
          className="block rounded-md focus:outline-none focus-visible:ring-1 focus-visible:ring-accent"
          onPointerLeave={() => setIdx(null)}
          {...keyProps}
        >
          <Axes g={g} width={width} times={times} xFormat={xFormat} xTickEvery={xTickEvery} yFormat={yFormat} />
          {s.values.map((v, i) => {
            const x = g.x(i) - bw / 2
            const hit = <rect key={`h${i}`} x={g.left + i * g.band} y={PLOT_TOP} width={g.band} height={g.plotH} fill="transparent" onPointerEnter={() => setIdx(i)} />
            if (!v) return hit
            const y = g.y(v)
            const r = Math.min(4, bw / 2, g.baseline - y)
            // Rounded data end (top), square at the baseline.
            const d = `M${x},${g.baseline}V${y + r}Q${x},${y} ${x + r},${y}H${x + bw - r}Q${x + bw},${y} ${x + bw},${y + r}V${g.baseline}Z`
            return (
              <g key={i}>
                <path d={d} fill={s.color} opacity={idx === null || idx === i ? 1 : 0.55} />
                {hit}
              </g>
            )
          })}
        </svg>
      )}
      {width > 0 && g.isEmpty && <EmptyNote>{emptyText}</EmptyNote>}
      {width > 0 && idx !== null && (
        <Tooltip
          x={g.x(idx)} width={width} title={timeLabel(idx)}
          rows={[{ key: s.key, color: s.color, name: s.name, mark: 'rect', value: valueFormat(s.values[idx] ?? 0) }]}
        />
      )}
    </div>
  )
}

/** Card wrapper: title (+ hint), and a Chart / Table toggle so every value is readable without hover. */
export function ChartCard({ title, hint, times, series, valueFormat, timeLabel, children }: {
  title: ReactNode
  hint?: ReactNode
  times: Date[]
  series: Series[]
  valueFormat: (v: number) => string
  timeLabel: (i: number) => string
  children: ReactNode
}) {
  const [table, setTable] = useState(false)
  const id = useId()
  return (
    <section className="rounded-xl border border-border-subtle bg-bg-card p-4" aria-labelledby={id}>
      <div className="mb-3 flex items-start justify-between gap-3">
        <div>
          <h3 id={id} className="text-sm font-medium text-text-primary">{title}</h3>
          {hint && <div className="mt-0.5 text-xs text-text-muted">{hint}</div>}
        </div>
        <button
          onClick={() => setTable((t) => !t)}
          aria-pressed={table}
          className="shrink-0 rounded-md px-2 py-0.5 text-[11px] text-text-muted transition-colors hover:bg-bg-card-hover hover:text-text-primary focus:outline-none focus:ring-1 focus:ring-accent"
        >
          {table ? 'Chart' : 'Table'}
        </button>
      </div>
      {table ? (
        <div className="max-h-[200px] overflow-auto">
          <table className="w-full text-xs tabular-nums">
            <thead className="sticky top-0 bg-bg-card text-text-muted">
              <tr>
                <th className="py-1 pr-3 text-left font-normal">Time</th>
                {series.map((s) => <th key={s.key} className="py-1 pl-3 text-right font-normal">{s.name}</th>)}
              </tr>
            </thead>
            <tbody className="text-text-secondary">
              {times.map((_, i) => (
                <tr key={i} className="border-t border-border-subtle">
                  <td className="py-1 pr-3">{timeLabel(i)}</td>
                  {series.map((s) => <td key={s.key} className="py-1 pl-3 text-right text-text-primary">{s.values[i] === null ? '—' : valueFormat(s.values[i] as number)}</td>)}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : children}
    </section>
  )
}

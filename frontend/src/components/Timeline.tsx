import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { worstSev, type Frame, type Feedback } from '../data/types'
import { FRAME_INTERVAL_SEC, clockLabel } from '../data/format'

interface Props {
  frames: Frame[]
  visible: number
  selected: number | null
  onSelect: (i: number) => void
  feedback: Feedback[]
  threshold: number
}

const H = 48
// Zoom = pixels per sampled frame; 0 means "fit the whole match in view".
const LEVELS = [0, 3, 6, 12, 24]
const TICK_STEPS = [15, 30, 60, 120, 300, 600, 900, 1800, 3600]
const ZOOM_KEY = 'streamsense.timelineZoom'

function loadZoom(): number {
  try {
    const z = Number(localStorage.getItem(ZOOM_KEY))
    return LEVELS.includes(z) ? z : 0
  } catch {
    return 0
  }
}

export default function Timeline({ frames, visible, selected, onSelect, feedback, threshold }: Props) {
  const n = frames.length
  const [hover, setHover] = useState<number | null>(null)
  const [zoom, setZoom] = useState(loadZoom)
  const [viewW, setViewW] = useState(0)
  const scroller = useRef<HTMLDivElement>(null)
  // Frame index (fractional) to keep under the given viewport x after a zoom change.
  const anchor = useRef<{ frame: number; x: number } | null>(null)

  useEffect(() => {
    try { localStorage.setItem(ZOOM_KEY, String(zoom)) } catch { /* per-viewer convenience only */ }
  }, [zoom])

  useEffect(() => {
    const el = scroller.current
    if (!el) return
    const ro = new ResizeObserver(() => setViewW(el.clientWidth))
    ro.observe(el)
    setViewW(el.clientWidth)
    return () => ro.disconnect()
  }, [])

  // Zooming in never makes bars narrower than "fit".
  const fitPx = n > 0 && viewW > 0 ? viewW / n : 1
  const px = zoom === 0 || zoom <= fitPx ? fitPx : zoom
  const innerW = n * px
  const zoomed = innerW > viewW + 1

  const changeZoom = (dir: 1 | -1, x?: number) => {
    const el = scroller.current
    const i = LEVELS.indexOf(zoom)
    let j = Math.min(LEVELS.length - 1, Math.max(0, i + dir))
    // Skip levels that would look identical to "fit" on this screen.
    while (dir > 0 && j < LEVELS.length - 1 && LEVELS[j] <= fitPx) j++
    if (dir < 0 && j > 0 && LEVELS[j] <= fitPx) j = 0
    if (j === i || !el) return
    const vx = x ?? (selected !== null ? Math.min(Math.max(selected * px - el.scrollLeft, 0), el.clientWidth) : el.clientWidth / 2)
    anchor.current = { frame: (el.scrollLeft + vx) / px, x: vx }
    setZoom(LEVELS[j])
  }

  useLayoutEffect(() => {
    const el = scroller.current
    if (!el || !anchor.current) return
    el.scrollLeft = anchor.current.frame * px - anchor.current.x
    anchor.current = null
  }, [px])

  // Keep the selected frame on screen.
  useEffect(() => {
    const el = scroller.current
    if (!el || selected === null || !zoomed) return
    const left = selected * px
    if (left < el.scrollLeft + 20 || left + px > el.scrollLeft + el.clientWidth - 20) {
      el.scrollTo({ left: left - el.clientWidth / 2, behavior: 'smooth' })
    }
  }, [selected, px, zoomed])

  // Ctrl/⌘ + wheel (and trackpad pinch) zooms around the cursor; plain wheel scrolls as usual.
  useEffect(() => {
    const el = scroller.current
    if (!el) return
    const onWheel = (e: WheelEvent) => {
      if (!(e.ctrlKey || e.metaKey) || Math.abs(e.deltaY) < 2) return
      e.preventDefault()
      changeZoom(e.deltaY < 0 ? 1 : -1, e.clientX - el.getBoundingClientRect().left)
    }
    el.addEventListener('wheel', onWheel, { passive: false })
    return () => el.removeEventListener('wheel', onWheel)
  })

  const onKey = (e: React.KeyboardEvent) => {
    if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return
    e.preventDefault()
    const cur = selected ?? (e.key === 'ArrowRight' ? -1 : visible)
    const next = Math.min(visible - 1, Math.max(0, cur + (e.key === 'ArrowRight' ? 1 : -1)))
    if (next !== selected && frames[next] && !frames[next].pending) onSelect(next)
  }

  const totalSec = (frames[n - 1]?.tSec ?? 0) + FRAME_INTERVAL_SEC
  const ticks = useMemo(() => {
    const pxPerSec = innerW / Math.max(totalSec, 1)
    const step = TICK_STEPS.find((s) => s * pxPerSec >= 72) ?? 3600
    const out: number[] = []
    for (let t = 0; t < totalSec; t += step) out.push(t)
    return out
  }, [innerW, totalSec])
  const missed = feedback.filter((f) => f.kind === 'missed')
  const stretch = selected !== null ? frames[selected]?.stretch : undefined
  const btn = 'h-6 min-w-6 rounded-md border border-border-subtle px-1.5 text-xs text-text-secondary hover:bg-bg-card-hover disabled:opacity-40'
  const maxed = zoom === LEVELS[LEVELS.length - 1] || fitPx >= LEVELS[LEVELS.length - 1]

  return (
    <div>
      <div className="mb-1 flex items-center justify-end gap-1.5 text-[11px] text-text-muted">
        <span className="mr-1 hidden sm:inline">{zoomed ? 'Ctrl/⌘ + scroll to zoom · ← → to step' : 'Zoom in to make bars easier to click'}</span>
        <button className={btn} onClick={() => changeZoom(-1)} disabled={!zoomed} aria-label="Zoom out">−</button>
        <button className={btn} onClick={() => changeZoom(1)} disabled={maxed} aria-label="Zoom in">+</button>
        <button className={btn} onClick={() => { anchor.current = null; setZoom(0) }} disabled={!zoomed}>Fit</button>
      </div>
      <div
        ref={scroller}
        tabIndex={0}
        onKeyDown={onKey}
        className={`relative pt-7 outline-none focus-visible:ring-1 focus-visible:ring-border-subtle ${zoomed ? 'overflow-x-auto pb-1' : 'overflow-x-hidden'}`}
        aria-label="Timeline: use left and right arrow keys to step between frames"
      >
        <div className="relative" style={{ width: zoomed ? `${innerW}px` : '100%' }}>
          <svg viewBox={`0 0 ${n} ${H + 10}`} preserveAspectRatio="none" className="block h-[88px] w-full" role="list" aria-label="Sampled frames along the match clock">
            {frames.map((f) => {
              const avail = f.index < visible && !f.pending
              const bad = avail && f.detections.length > 0
              const sev = bad ? worstSev(f.detections) : 0
              const h = avail ? 10 + f.score * (H - 10) : 6
              const sel = selected === f.index
              const inStretch = stretch && f.index >= stretch.start && f.index <= stretch.end
              // Severity-coded, washed out; at/above the alert threshold slightly stronger.
              let fill = 'var(--color-border-subtle)'
              let opacity = 1
              if (avail && bad) {
                fill = `var(--color-sev-${Math.min(5, Math.max(1, sev || 1))})`
                opacity = sev >= threshold ? 0.9 : 0.6
              } else if (avail) {
                fill = 'var(--color-good)'
                opacity = 0.45
              }
              if (sel) { fill = 'var(--color-accent)'; opacity = 1 }
              if (hover === f.index && !sel) opacity = 1
              return (
                <g key={f.index} role="listitem">
                  {inStretch && <rect x={f.index} y={0} width={1} height={H} fill="var(--color-bg-card-hover)" />}
                  <rect x={f.index + 0.15} y={H - h} width={0.7} height={h} fill={fill} opacity={opacity} rx={0.1} />
                  {avail && (
                    <rect
                      x={f.index}
                      y={0}
                      width={1}
                      height={H + 10}
                      fill="transparent"
                      className="cursor-pointer"
                      onMouseEnter={() => setHover(f.index)}
                      onMouseLeave={() => setHover(null)}
                      onClick={() => onSelect(f.index)}
                    >
                      <title>{`${clockLabel(f.tSec)}${bad ? ` · ${f.detections.map((d) => `${d.type} sev ${d.severity ?? '—'}`).join(', ')}` : ' · good'}`}</title>
                    </rect>
                  )}
                </g>
              )
            })}
            {missed.map((m) => (
              <rect key={m.id} x={m.frameIndex} y={H + 3} width={1} height={5} fill="var(--color-ground-truth)">
                <title>{`Missed: ${m.defect}`}</title>
              </rect>
            ))}
            {visible < n && <rect x={visible} y={0} width={n - visible} height={H} fill="var(--color-bg-primary)" opacity={0.5} />}
          </svg>
          {selected !== null && selected < n && (
            // Always-visible marker for the selected frame (a bar can be < 1 px wide at "fit").
            <div className="pointer-events-none absolute top-0 h-[88px] w-[3px] -translate-x-1/2 rounded-sm bg-accent" style={{ left: `${((selected + 0.5) / n) * 100}%` }} aria-hidden>
              <div className="absolute -top-1.5 left-1/2 h-0 w-0 -translate-x-1/2 border-x-[5px] border-t-[6px] border-x-transparent border-t-accent" />
            </div>
          )}
          {hover !== null && (
            <div className="pointer-events-none absolute -top-7 whitespace-nowrap rounded-md border border-border-subtle bg-bg-primary px-2 py-0.5 text-[11px] text-text-primary" style={{ left: `${((hover + 0.5) / n) * 100}%`, transform: 'translateX(-50%)' }}>
              {clockLabel(frames[hover].tSec)}
            </div>
          )}
          <div className="relative mt-1 h-4 text-[10px] text-text-muted">
            {ticks.map((t) => (
              <span key={t} className="absolute -translate-x-1/2 tabular-nums first:translate-x-0" style={{ left: `${(t / totalSec) * 100}%` }}>{clockLabel(t)}</span>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}

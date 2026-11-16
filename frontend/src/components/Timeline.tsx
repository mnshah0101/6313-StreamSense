import { useMemo, useState } from 'react'
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

export default function Timeline({ frames, visible, selected, onSelect, feedback, threshold }: Props) {
  const n = frames.length
  const [hover, setHover] = useState<number | null>(null)
  const ticks = useMemo(() => {
    const total = frames[n - 1]?.tSec ?? 0
    const step = total > 1800 ? 600 : 300
    const out: number[] = []
    for (let t = 0; t <= total; t += step) out.push(t)
    return out
  }, [frames, n])
  const totalSec = (frames[n - 1]?.tSec ?? 0) + FRAME_INTERVAL_SEC
  const missed = feedback.filter((f) => f.kind === 'missed')
  const stretch = selected !== null ? frames[selected]?.stretch : undefined

  return (
    <div>
      <div className="relative">
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
        {hover !== null && (
          <div className="pointer-events-none absolute -top-7 rounded-md border border-border-subtle bg-bg-primary px-2 py-0.5 text-[11px] text-text-primary" style={{ left: `${(hover / n) * 100}%`, transform: 'translateX(-50%)' }}>
            {clockLabel(frames[hover].tSec)}
          </div>
        )}
      </div>
      <div className="relative mt-1 h-4 text-[10px] text-text-muted">
        {ticks.map((t) => (
          <span key={t} className="absolute -translate-x-1/2 tabular-nums" style={{ left: `${(t / totalSec) * 100}%` }}>{clockLabel(t)}</span>
        ))}
      </div>
    </div>
  )
}

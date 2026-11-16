import { useId, useState, type MouseEvent } from 'react'
import { mediaUrl } from '../api'
import { Spinner } from './ui'

interface Props {
  /** API-relative image path (frame, thumb or poster). Without one a neutral empty frame shows. */
  imageUrl?: string | null
  /** API-relative heat-map overlay (RGBA PNG, same size as the frame); used instead of the `heat` circle. */
  overlayUrl?: string | null
  /** Peak of the heat map (0..1 coords), drawn as a soft circle when there is no overlay image. */
  heat?: { cx: number; cy: number; r: number } | null
  showHeat?: boolean
  /** Not analyzed yet: show a spinner instead of "no image". */
  pending?: boolean
  /** Optional marker placed by the reviewer (0..1 coords). */
  marker?: { x: number; y: number } | null
  onClickFrame?: (p: { x: number; y: number }) => void
  label?: string
  cornerLabel?: string
  className?: string
  /** Load immediately (the main frame view); thumbnails load only when scrolled into view. */
  eager?: boolean
}

/** A sampled frame from the API, with optional heat-map overlay and reviewer marker. */
export default function FrameThumb({ imageUrl, overlayUrl, heat, showHeat, pending, marker, onClickFrame, label, cornerLabel, className = '', eager = false }: Props) {
  const [broken, setBroken] = useState<string | null>(null)
  const gid = useId()
  const src = mediaUrl(imageUrl)
  const photo = src && broken !== src ? src : undefined
  const overlay = mediaUrl(overlayUrl)

  const handleClick = (e: MouseEvent<SVGSVGElement>) => {
    if (!onClickFrame) return
    const rect = e.currentTarget.getBoundingClientRect()
    onClickFrame({ x: (e.clientX - rect.left) / rect.width, y: (e.clientY - rect.top) / rect.height })
  }

  return (
    <div className={`relative h-full w-full bg-bg-primary ${className}`}>
      {photo ? (
        <img src={photo} alt="" loading={eager ? 'eager' : 'lazy'} decoding="async" onError={() => setBroken(photo)} className="absolute inset-0 h-full w-full object-fill" draggable={false} />
      ) : (
        <div className="absolute inset-0 flex items-center justify-center gap-2 text-[10px] uppercase tracking-wide text-text-muted">
          {pending ? <><Spinner />processing</> : 'no image'}
        </div>
      )}
      {photo && overlay && showHeat && (
        <img src={overlay} alt="" loading={eager ? 'eager' : 'lazy'} decoding="async" className="pointer-events-none absolute inset-0 h-full w-full object-fill" draggable={false} />
      )}
      <svg
        viewBox="0 0 320 180"
        preserveAspectRatio="none"
        className={`relative block h-full w-full ${onClickFrame ? 'cursor-crosshair' : ''}`}
        role="img"
        aria-label={label ?? 'Sampled frame'}
        onClick={handleClick}
      >
        <defs>
          <radialGradient id={gid}>
            <stop offset="0%" stopColor="#ffffff" stopOpacity="0.75" />
            <stop offset="55%" stopColor="#ffffff" stopOpacity="0.3" />
            <stop offset="100%" stopColor="#ffffff" stopOpacity="0" />
          </radialGradient>
        </defs>
        {showHeat && heat && !(photo && overlay) && (
          <circle cx={heat.cx * 320} cy={heat.cy * 180} r={heat.r * 320} fill={`url(#${CSS.escape(gid)})`} />
        )}
        {marker && (
          <g transform={`translate(${marker.x * 320} ${marker.y * 180})`}>
            <circle r="10" fill="none" stroke="var(--color-ground-truth)" strokeWidth="2" />
            <circle r="2" fill="var(--color-ground-truth)" />
          </g>
        )}
      </svg>
      {cornerLabel && (
        <div className="pointer-events-none absolute left-2 top-2 rounded-md bg-bg-primary/85 px-1.5 py-0.5 text-[10px] text-text-primary">{cornerLabel}</div>
      )}
    </div>
  )
}

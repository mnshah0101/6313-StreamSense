/** Initials from a team name: "Pine Ridge" → "PR", "Westview" → "WE". */
export function initials(name: string): string {
  const words = name.trim().split(/\s+/).filter(Boolean)
  if (words.length === 0) return '?'
  if (words.length === 1) return words[0].slice(0, 2).toUpperCase()
  return (words[0][0] + words[1][0]).toUpperCase()
}

/** Neutral initials badge for a team (no logos or colors are known for uploaded games). */
export default function TeamCrest({ team, size = 48, className = '' }: { team: string; size?: number; className?: string }) {
  return (
    <svg width={size} height={size} viewBox="0 0 100 100" className={className} role="img" aria-label={team}>
      <circle cx="50" cy="50" r="46" fill="var(--color-bg-card-hover)" stroke="var(--color-border-subtle)" strokeWidth="4" />
      <text x="50" y="63" textAnchor="middle" fontSize="36" fontWeight="700" fontFamily="var(--font-display)" fill="var(--color-text-primary)" letterSpacing="1">
        {initials(team)}
      </text>
    </svg>
  )
}

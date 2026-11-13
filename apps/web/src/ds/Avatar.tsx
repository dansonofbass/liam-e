export function Avatar({ name, address, colorIndex, size = 'md' }: { name: string; address?: string; colorIndex: number; size?: 'md' | 'lg' }) {
  const initials = name.trim().split(/\s+/).filter(Boolean).slice(0, 2).map((word) => Array.from(word)[0]).join('').toLocaleUpperCase('de') || (address?.trim().charAt(0).toLocaleUpperCase('de') ?? '')
  return <span className={`le-avatar le-avatar--a${((colorIndex % 4 + 4) % 4) + 1}${size === 'lg' ? ' le-avatar--lg' : ''}`} aria-hidden="true">{initials}</span>
}

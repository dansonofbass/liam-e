const letters = (text: string) => text.match(/[\p{L}\p{N}]/gu) ?? []
// Two words give one letter each ("Hausverwaltung Kurz" is "HK"); a single word, an address included, gives its first two letters ("privat@example.com" is "PR").
export function initialsOf(name: string, address?: string): string {
  const words = (name.trim() || address?.trim() || '').split(/\s+/).map(word => letters(word.split('@')[0] ?? '')).filter(word => word.length > 0)
  const chosen = words.length > 1 ? [words[0]?.[0], words[1]?.[0]] : words[0]?.slice(0, 2) ?? []
  return chosen.join('').toLocaleUpperCase('de')
}
export function Avatar({ name, address, colorIndex, size = 'md' }: { name: string; address?: string; colorIndex: number; size?: 'md' | 'lg' }) {
  return <span className={`le-avatar le-avatar--a${((colorIndex % 4 + 4) % 4) + 1}${size === 'lg' ? ' le-avatar--lg' : ''}`} aria-hidden="true">{initialsOf(name, address)}</span>
}

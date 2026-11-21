// i18n-exempt: local storage key and browser event name.
import { useCallback, useEffect, useState } from 'react'

export const SKILL_FAVORITES_STORAGE_KEY = 'liam-e-skill-favorites'
const FAVORITES_EVENT = 'liam-skill-favorites-changed'

function normalizeIds(raw: unknown): string[] {
  if (!Array.isArray(raw)) return []
  const unique: string[] = []
  const seen = new Set<string>()
  for (const item of raw) {
    if (typeof item !== 'string') continue
    const trimmed = item.trim()
    if (!trimmed || seen.has(trimmed)) continue
    seen.add(trimmed)
    unique.push(trimmed)
  }
  return unique
}

export function readFavoriteSkillIds(): string[] {
  if (typeof window === 'undefined') return []
  try {
    const raw = window.localStorage.getItem(SKILL_FAVORITES_STORAGE_KEY)
    if (!raw) return []
    return normalizeIds(JSON.parse(raw))
  } catch {
    return []
  }
}

export function writeFavoriteSkillIds(ids: string[]): string[] {
  const clean = normalizeIds(ids)
  if (typeof window === 'undefined') return clean
  try {
    window.localStorage.setItem(SKILL_FAVORITES_STORAGE_KEY, JSON.stringify(clean))
  } catch {
    // Storage may be disabled in private browsing.
  }
  window.dispatchEvent(new Event(FAVORITES_EVENT))
  return clean
}

export function useFavoriteSkills() {
  const [favoriteIds, setFavoriteIds] = useState<string[]>([])

  useEffect(() => {
    const refresh = () => setFavoriteIds(readFavoriteSkillIds())
    refresh()
    const onStorage = (event: StorageEvent) => {
      if (event.key === null || event.key === SKILL_FAVORITES_STORAGE_KEY) refresh()
    }
    window.addEventListener('storage', onStorage)
    window.addEventListener(FAVORITES_EVENT, refresh)
    return () => {
      window.removeEventListener('storage', onStorage)
      window.removeEventListener(FAVORITES_EVENT, refresh)
    }
  }, [])

  const isFavorite = useCallback((id: string) => favoriteIds.includes(id), [favoriteIds])

  const toggleFavorite = useCallback((id: string) => {
    const current = readFavoriteSkillIds()
    const next = current.includes(id) ? current.filter(item => item !== id) : [...current, id]
    setFavoriteIds(writeFavoriteSkillIds(next))
  }, [])

  const removeFavorite = useCallback((id: string) => {
    const current = readFavoriteSkillIds()
    if (!current.includes(id)) return
    setFavoriteIds(writeFavoriteSkillIds(current.filter(item => item !== id)))
  }, [])

  return { favoriteIds, isFavorite, toggleFavorite, removeFavorite }
}

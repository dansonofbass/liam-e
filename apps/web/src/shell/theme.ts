import { useSyncExternalStore } from 'react'

/**
 * The reader's choice between the light theme, the dark theme or following the system setting.
 * `tokens.css` does the colouring: `data-theme` on `<html>` forces a theme, its absence follows
 * `prefers-color-scheme`. The choice lives in this browser only; "system" is stored as no entry.
 */
export type ThemeChoice = 'light' | 'dark' | 'system'
export const THEME_STORAGE_KEY = 'liam-e-theme' // i18n-exempt

/** Runs inline in `<head>` before the first paint, so a stored theme never flashes the other one. */
export const themeScript = `try{var t=localStorage.getItem(${JSON.stringify(THEME_STORAGE_KEY)});if(t==="light"||t==="dark")document.documentElement.setAttribute("data-theme",t)}catch(e){}` // i18n-exempt

const listeners = new Set<() => void>()
// A choice that storage refused (blocked or full) still holds for this page.
let unsaved: ThemeChoice | null = null

export function readTheme(): ThemeChoice {
  if (unsaved) return unsaved
  try {
    const stored = window.localStorage.getItem(THEME_STORAGE_KEY)
    return stored === 'light' || stored === 'dark' ? stored : 'system'
  } catch {
    return 'system'
  }
}

export function applyTheme(choice: ThemeChoice) {
  const root = document.documentElement
  if (choice === 'system') root.removeAttribute('data-theme')
  else root.setAttribute('data-theme', choice)
}

export function setTheme(choice: ThemeChoice) {
  try {
    if (choice === 'system') window.localStorage.removeItem(THEME_STORAGE_KEY)
    else window.localStorage.setItem(THEME_STORAGE_KEY, choice)
    unsaved = null
  } catch {
    // Storage can be blocked (private window); the theme still applies for this page.
    unsaved = choice
  }
  applyTheme(choice)
  listeners.forEach(listener => listener())
}

function subscribe(listener: () => void) {
  listeners.add(listener)
  // Another tab changed the choice: follow it here too.
  const onStorage = (event: StorageEvent) => {
    if (event.key !== THEME_STORAGE_KEY && event.key !== null) return
    applyTheme(readTheme())
    listener()
  }
  window.addEventListener('storage', onStorage)
  return () => {
    listeners.delete(listener)
    window.removeEventListener('storage', onStorage)
  }
}

export function useTheme(): ThemeChoice {
  return useSyncExternalStore(subscribe, readTheme, () => 'system' as const)
}

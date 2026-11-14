import { useSyncExternalStore } from 'react'

const queries = ['(min-width: 640px)', '(min-width: 1024px)', '(min-width: 1440px)', '(pointer: coarse)'] as const
function subscribe(callback: () => void) {
  const lists = queries.map(query => window.matchMedia(query))
  lists.forEach(list => list.addEventListener('change', callback))
  return () => lists.forEach(list => list.removeEventListener('change', callback))
}
function breakpoint(): 'mobile' | 'tablet' | 'desktop' | 'wide' {
  if (window.matchMedia(queries[2]).matches) return 'wide'
  if (window.matchMedia(queries[1]).matches) return 'desktop'
  if (window.matchMedia(queries[0]).matches) return 'tablet'
  return 'mobile'
}
export function useBreakpoint() { return useSyncExternalStore(subscribe, breakpoint, () => 'desktop' as const) }
export function useCoarsePointer() { return useSyncExternalStore(subscribe, () => window.matchMedia(queries[3]).matches, () => false) }

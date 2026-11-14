import { useEffect } from 'react'
import { useBreakpoint } from '../shell/useBreakpoint'

type Handlers = { onNext(): void; onPrev(): void; onOpen(): void; onArchive(): void; onToggleRead(): void; onTrash(): void }

export function useInboxKeys(handlers: Handlers) {
  const breakpoint = useBreakpoint()
  useEffect(() => {
    if (breakpoint !== 'desktop' && breakpoint !== 'wide') return
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.ctrlKey || event.metaKey || event.altKey || event.isComposing) return
      const target = event.target instanceof Element ? event.target : null
      if (target?.closest('input, textarea, select, [contenteditable], [role="menu"], [role="dialog"]')) return
      // An open dialog blocks the list even when the focus is not inside it (its focused element was removed).
      if (document.querySelector('[aria-modal="true"]')) return
      if (event.key === 'Enter' && target?.closest('button, a')) return
      const action = ({ j: handlers.onNext, k: handlers.onPrev, Enter: handlers.onOpen, e: handlers.onArchive, u: handlers.onToggleRead, '#': handlers.onTrash, Delete: handlers.onTrash } as Record<string, (() => void) | undefined>)[event.key]
      if (action) { event.preventDefault(); action() }
    }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [breakpoint, handlers])
}

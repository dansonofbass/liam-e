import { useEffect, useRef, type ReactNode } from 'react'
export function Drawer({ open, onClose, label, children }: { open: boolean; onClose: () => void; label: string; children: ReactNode }) {
  const ref = useRef<HTMLDivElement>(null)
  const closeRef = useRef(onClose)
  closeRef.current = onClose
  useEffect(() => {
    if (!open) return
    const previous = document.activeElement as HTMLElement | null
    const focusable = () => Array.from(ref.current?.querySelectorAll<HTMLElement>('a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])') ?? [])
    ;(focusable()[0] ?? ref.current)?.focus()
    const keydown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') { event.preventDefault(); closeRef.current(); return }
      if (event.key !== 'Tab') return
      const nodes = focusable()
      if (!nodes.length) { event.preventDefault(); ref.current?.focus(); return }
      const index = nodes.indexOf(document.activeElement as HTMLElement)
      if (event.shiftKey && index <= 0) { event.preventDefault(); nodes[nodes.length - 1]?.focus() }
      else if (!event.shiftKey && (index === nodes.length - 1 || index === -1)) { event.preventDefault(); nodes[0]?.focus() }
    }
    document.addEventListener('keydown', keydown)
    return () => { document.removeEventListener('keydown', keydown); previous?.focus() }
  }, [open])
  if (!open) return null
  return <div className="le-scrim" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose() }}><div className="le-drawer" role="dialog" aria-modal="true" aria-label={label} tabIndex={-1} ref={ref}>{children}</div></div>
}

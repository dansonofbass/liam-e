import type { ReactNode } from 'react'
import { useFocusTrap } from './useFocusTrap'
export function Drawer({ open, onClose, label, children }: { open: boolean; onClose: () => void; label: string; children: ReactNode }) {
  const ref = useFocusTrap(open, onClose)
  if (!open) return null
  return <div className="le-scrim" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose() }}><div className="le-drawer" role="dialog" aria-modal="true" aria-label={label} tabIndex={-1} ref={ref}>{children}</div></div>
}

import { useEffect, useId, useRef, useState, type CSSProperties, type ReactNode, type ButtonHTMLAttributes, type Ref } from 'react'
import { createPortal } from 'react-dom'
import { useFloating, type Align, type Side } from './floating'
import { Icon, type IconName } from './Icon'
type TriggerProps = ButtonHTMLAttributes<HTMLButtonElement> & { ref: Ref<HTMLButtonElement> }
// A disabled item stays focusable (aria-disabled) and says why in its hint line.
// Items with `checked` form a choice (menuitemradio): the chosen one carries a check mark and takes the focus on opening.
// `placement` is the preferred side and edge: below (default) or above the trigger, aligned to its start or end. Like a
// tooltip the menu hangs in <body> with fixed coordinates from floating.ts: it flips, shifts into the viewport and
// scrolls within the room it has, and no scroll area or stacking context around the trigger can cut it off or cover
// it. Tab leaves it for the trigger, so the focus order stays that of the page.
type Placement = 'down-start' | 'down-end' | 'up-start' | 'up-end'
export function Menu({ trigger, items, placement = 'down-start' }: { trigger: (props: TriggerProps) => ReactNode; items: { label: string; icon?: IconName; onSelect: () => void; tone?: 'danger'; disabled?: boolean; hint?: string; checked?: boolean }[]; placement?: Placement }) {
  const [open, setOpen] = useState(false)
  const anchorRef = useRef<HTMLSpanElement>(null)
  const triggerRef = useRef<HTMLButtonElement>(null)
  const menuRef = useRef<HTMLDivElement>(null)
  const id = useId()
  const [vertical, edge] = placement.split('-') as ['down' | 'up', Align]
  const side: Side = vertical === 'up' ? 'top' : 'bottom'
  // Back to the trigger without scrolling to it: it may just have left the screen.
  const close = () => { setOpen(false); triggerRef.current?.focus({ preventScroll: true }) }
  // A trigger scrolled out of view closes its menu; focus inside the menu goes back to the trigger.
  const spot = useFloating(open, anchorRef, menuRef, side, edge, () => { if (menuRef.current?.contains(document.activeElement)) close(); else setOpen(false) })
  const placed = spot !== null
  const position = { left: spot?.left ?? 0, top: spot?.top ?? 0, visibility: placed ? 'visible' : 'hidden', '--le-menu-room': spot ? `${spot.maxHeight}px` : undefined } as CSSProperties
  // The focus moves in once the menu is placed: an element still hidden cannot take it.
  useEffect(() => {
    if (!open || !placed) return
    const first = menuRef.current?.querySelector<HTMLButtonElement>('[aria-checked="true"]') ?? menuRef.current?.querySelector<HTMLButtonElement>('[role^="menuitem"]')
    first?.focus()
  }, [open, placed])
  useEffect(() => {
    if (!open) return
    const onPointerDown = (event: PointerEvent) => {
      const target = event.target as Node | null
      if (!menuRef.current?.contains(target) && !triggerRef.current?.contains(target)) setOpen(false)
    }
    const onOtherMenuOpen = () => setOpen(false)
    document.addEventListener('pointerdown', onPointerDown)
    document.addEventListener('liam-menu-open', onOtherMenuOpen)
    return () => {
      document.removeEventListener('pointerdown', onPointerDown)
      document.removeEventListener('liam-menu-open', onOtherMenuOpen)
    }
  }, [open])
  return <span ref={anchorRef} className="le-menu-anchor">{trigger({ ref: triggerRef, 'aria-haspopup': 'menu', 'aria-expanded': open, 'aria-controls': open ? id : undefined, onClick: () => { if (!open) document.dispatchEvent(new Event('liam-menu-open')); setOpen(!open) } })}{open && createPortal(<div ref={menuRef} id={id} role="menu" className={`le-menu le-rise le-menu--${placement}`} style={position} onKeyDown={(event) => {
    if (event.key === 'Escape') { event.preventDefault(); close() }
    // No preventDefault: the browser moves on from the trigger, as if the menu had never been open.
    if (event.key === 'Tab') close()
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault()
      const nodes = Array.from(menuRef.current?.querySelectorAll<HTMLButtonElement>('[role^="menuitem"]') ?? [])
      const index = nodes.indexOf(document.activeElement as HTMLButtonElement)
      nodes[(index + (event.key === 'ArrowDown' ? 1 : -1) + nodes.length) % nodes.length]?.focus()
    }
  }}>{items.map((item, index) => <button type="button" role={item.checked === undefined ? 'menuitem' : 'menuitemradio'} aria-checked={item.checked} className={`le-menu-item${item.tone === 'danger' ? ' le-menu-item--danger' : ''}`} key={index} aria-disabled={item.disabled || undefined} onClick={() => { if (item.disabled) return; close(); item.onSelect() }}><span className="le-menu-title">{item.label}</span>{item.checked ? <Icon name="check" /> : item.icon && <Icon name={item.icon} />}{item.hint && <span className="le-menu-sub">{item.hint}</span>}</button>)}</div>, document.body)}</span>
}

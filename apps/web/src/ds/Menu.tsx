import { useEffect, useRef, useState, type ReactNode, type ButtonHTMLAttributes, type Ref } from 'react'
import { Icon, type IconName } from './Icon'
type TriggerProps = ButtonHTMLAttributes<HTMLButtonElement> & { ref: Ref<HTMLButtonElement> }
// A disabled item stays focusable (aria-disabled) and says why in its hint line.
export function Menu({ trigger, items }: { trigger: (props: TriggerProps) => ReactNode; items: { label: string; icon?: IconName; onSelect: () => void; tone?: 'danger'; disabled?: boolean; hint?: string }[] }) {
  const [open, setOpen] = useState(false)
  const triggerRef = useRef<HTMLButtonElement>(null)
  const menuRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!open) return
    menuRef.current?.querySelector<HTMLButtonElement>('[role="menuitem"]')?.focus()
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
  const close = () => { setOpen(false); triggerRef.current?.focus() }
  return <span className="le-menu-anchor">{trigger({ ref: triggerRef, 'aria-haspopup': 'menu', 'aria-expanded': open, onClick: () => { if (!open) document.dispatchEvent(new Event('liam-menu-open')); setOpen(!open) } })}{open && <div ref={menuRef} role="menu" className="le-menu le-rise" onKeyDown={(event) => {
    if (event.key === 'Escape') { event.preventDefault(); close() }
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault()
      const nodes = Array.from(menuRef.current?.querySelectorAll<HTMLButtonElement>('[role="menuitem"]') ?? [])
      const index = nodes.indexOf(document.activeElement as HTMLButtonElement)
      nodes[(index + (event.key === 'ArrowDown' ? 1 : -1) + nodes.length) % nodes.length]?.focus()
    }
  }}>{items.map((item, index) => <button type="button" role="menuitem" className={`le-menu-item${item.tone === 'danger' ? ' le-menu-item--danger' : ''}`} key={index} aria-disabled={item.disabled || undefined} onClick={() => { if (item.disabled) return; close(); item.onSelect() }}><span className="le-menu-title">{item.label}</span>{item.icon && <Icon name={item.icon} />}{item.hint && <span className="le-menu-sub">{item.hint}</span>}</button>)}</div>}</span>
}

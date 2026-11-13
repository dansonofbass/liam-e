import { useEffect, useRef, useState, type ReactNode, type ButtonHTMLAttributes, type Ref } from 'react'
import { Icon, type IconName } from './Icon'
type TriggerProps = ButtonHTMLAttributes<HTMLButtonElement> & { ref: Ref<HTMLButtonElement> }
export function Menu({ trigger, items }: { trigger: (props: TriggerProps) => ReactNode; items: { label: string; icon?: IconName; onSelect: () => void; tone?: 'danger' }[] }) {
  const [open, setOpen] = useState(false)
  const triggerRef = useRef<HTMLButtonElement>(null)
  const menuRef = useRef<HTMLDivElement>(null)
  useEffect(() => { if (open) menuRef.current?.querySelector<HTMLButtonElement>('[role="menuitem"]')?.focus() }, [open])
  const close = () => { setOpen(false); triggerRef.current?.focus() }
  return <span className="le-menu-anchor">{trigger({ ref: triggerRef, 'aria-haspopup': 'menu', 'aria-expanded': open, onClick: () => setOpen(!open) })}{open && <div ref={menuRef} role="menu" className="le-menu le-rise" onKeyDown={(event) => {
    if (event.key === 'Escape') { event.preventDefault(); close() }
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault()
      const nodes = Array.from(menuRef.current?.querySelectorAll<HTMLButtonElement>('[role="menuitem"]') ?? [])
      const index = nodes.indexOf(document.activeElement as HTMLButtonElement)
      nodes[(index + (event.key === 'ArrowDown' ? 1 : -1) + nodes.length) % nodes.length]?.focus()
    }
  }}>{items.map((item, index) => <button type="button" role="menuitem" className={`le-menu-item${item.tone === 'danger' ? ' le-menu-item--danger' : ''}`} key={index} onClick={() => { close(); item.onSelect() }}><span className="le-menu-title">{item.label}</span>{item.icon && <Icon name={item.icon} />}</button>)}</div>}</span>
}

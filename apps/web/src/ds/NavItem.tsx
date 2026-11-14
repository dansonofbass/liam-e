import { Link } from '@tanstack/react-router'
import { Icon, type IconName } from './Icon'
import { Badge } from './Chip'
import { Tooltip } from './Tooltip'
// Collapsed (tablet bar), the badge sits on the icon's corner and its meaning moves into the link's name, e.g. "Posteingang, 47 ungelesen".
export function NavItem({ to, icon, label, badge, badgeLabel, collapsed, tip, current }: { to: string; icon: IconName; label: string; badge?: number; badgeLabel?: string; collapsed?: boolean; tip?: string; current?: boolean }) {
  const name = collapsed ? (badge !== undefined && badgeLabel ? `${label}, ${badgeLabel}` : label) : undefined
  const link = <Link to={to} className="le-nav-item" activeProps={{ 'aria-current': 'page' }} aria-current={current ? 'page' : undefined} aria-label={name}><Icon name={icon} />{!collapsed && label}{badge !== undefined && (collapsed ? <span className="le-nav-badge" aria-hidden="true"><Badge>{badge}</Badge></span> : <Badge>{badge}</Badge>)}</Link>
  return <Tooltip content={tip ?? label} pos="right">{link}</Tooltip>
}
// A navigation entry that opens something instead of leading to a page, drawn like the links around it.
export function NavButton({ icon, label, tip, collapsed, onClick }: { icon: IconName; label: string; tip?: string; collapsed?: boolean; onClick?: () => void }) {
  return <Tooltip content={tip ?? label} pos="right"><button type="button" className="le-nav-item" aria-haspopup="dialog" aria-label={collapsed ? label : undefined} onClick={onClick}><Icon name={icon} />{!collapsed && label}</button></Tooltip>
}

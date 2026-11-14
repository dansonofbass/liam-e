import { Link } from '@tanstack/react-router'
import { Icon, type IconName } from './Icon'
import { Badge } from './Chip'
import { Tooltip } from './Tooltip'
export function NavItem({ to, icon, label, badge, collapsed, tip }: { to: string; icon: IconName; label: string; badge?: number; collapsed?: boolean; tip?: string }) {
  const link = <Link to={to} className="le-nav-item" activeProps={{ 'aria-current': 'page' }} aria-label={collapsed ? label : undefined}><Icon name={icon} />{!collapsed && label}{badge !== undefined && !collapsed && <Badge>{badge}</Badge>}</Link>
  return <Tooltip content={tip ?? label} pos="right">{link}</Tooltip>
}

import { Icon, type IconName } from './Icon'
import { Tooltip } from './Tooltip'
export function QuickAction({ icon, title, sub, tip, onClick }: { icon: IconName; title: string; sub: string; tip?: string; onClick: () => void }) {
  const tile = <button type="button" className="le-qa" onClick={onClick}><span className="le-qa-icon"><Icon name={icon} /></span><span className="le-qa-title">{title}</span><span className="le-qa-sub">{sub}</span></button>
  return tip ? <Tooltip content={tip}>{tile}</Tooltip> : tile
}

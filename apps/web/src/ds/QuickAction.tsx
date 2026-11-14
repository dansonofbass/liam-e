import { Icon, type IconName } from './Icon'
export function QuickAction({ icon, title, sub, onClick }: { icon: IconName; title: string; sub: string; onClick: () => void }) {
  return <button type="button" className="le-qa" onClick={onClick}><span className="le-qa-icon"><Icon name={icon} /></span><span className="le-qa-title">{title}</span><span className="le-qa-sub">{sub}</span></button>
}

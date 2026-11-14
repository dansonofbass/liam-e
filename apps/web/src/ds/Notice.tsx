import type { ReactNode } from 'react'
import { Icon } from './Icon'
export function Notice({ tone, children, action }: { tone: 'info' | 'success' | 'danger'; children: ReactNode; action?: { label: string; onClick: () => void } }) {
  return <div role={tone === 'danger' ? 'alert' : 'status'} className={`le-notice le-notice--${tone === 'info' ? 'neutral' : tone} le-rise`}><Icon name={tone === 'success' ? 'check' : tone === 'danger' ? 'circle-alert' : 'info'} />{children}{action && <button type="button" className="le-link" onClick={action.onClick}>{action.label}</button>}</div>
}

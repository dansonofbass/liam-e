import { useLayoutEffect, useRef } from 'react'
import { de } from '../i18n/de'
import { Icon } from './Icon'
import { Chip } from './Chip'
import { Menu } from './Menu'
import { Tooltip } from './Tooltip'
export function Composer({ value, onChange, onSubmit, onStop, busy, scope, accounts, onScopeChange, placeholder }: { value: string; onChange: (value: string) => void; onSubmit: () => void; onStop: () => void; busy: boolean; scope: string | null; accounts: { id: string; label: string }[]; onScopeChange: (scope: string | null) => void; placeholder: string }) {
  const textarea = useRef<HTMLTextAreaElement>(null)
  useLayoutEffect(() => { const el = textarea.current; if (el) { el.style.height = 'auto'; el.style.height = `${Math.min(el.scrollHeight, 200)}px` } }, [value])
  const send = () => { if (!busy && value.trim()) onSubmit() }
  return <div className="le-composer"><textarea ref={textarea} rows={1} aria-label={placeholder} placeholder={placeholder} value={value} onChange={event => onChange(event.target.value)} onKeyDown={event => { if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); send() } }} /><div className="le-composer-bar"><Menu trigger={props => <Chip {...props} quiet>{accounts.find(account => account.id === scope)?.label ?? de.controls.allAccounts}<Icon name="chevron-down" size="sm" /></Chip>} items={[{ label: de.controls.allAccounts, onSelect: () => onScopeChange(null) }, ...accounts.map(account => ({ label: account.label, onSelect: () => onScopeChange(account.id) }))]} /><span className="le-composer-spacer" />{busy ? <Tooltip content={de.controls.stop}><button type="button" className="le-send le-send--stop" aria-label={de.controls.stop} onClick={onStop}><Icon name="square" /></button></Tooltip> : <Tooltip content={de.controls.sendTip}><button type="button" className="le-send" aria-label={de.controls.send} disabled={!value.trim()} onClick={send}><Icon name="arrow-up" /></button></Tooltip>}</div></div>
}

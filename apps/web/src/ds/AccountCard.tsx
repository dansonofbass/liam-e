import { useEffect, useRef, useState } from 'react'
import type { AccountOut } from '../api/generated/types.gen'
import { de } from '../i18n/de'
import { formatTime } from '../i18n/format'
import { Avatar } from './Avatar'
import { Badge, Tag } from './Chip'
import { Button } from './Button'
import { Icon } from './Icon'
import { IconButton } from './IconButton'
import { Menu } from './Menu'
import { Tooltip } from './Tooltip'
import { TextField } from './TextField'

export function AccountCard({ account, onSync, onReconnect, onRename, onRemove, onSaveName, syncPending = false, coarse = false }: { account: AccountOut; onSync: () => void; onReconnect: () => void; onRename: () => void; onRemove: () => void; onSaveName?: (name: string) => Promise<string | undefined>; syncPending?: boolean; coarse?: boolean }) {
  const [editing, setEditing] = useState(false), [value, setValue] = useState(''), [fieldError, setFieldError] = useState<string>(), [saving, setSaving] = useState(false)
  const formRef = useRef<HTMLFormElement>(null), actionsRef = useRef<HTMLDivElement>(null), restoreFocus = useRef(false), savingRef = useRef(false)
  useEffect(() => { if (editing) { const input = formRef.current?.querySelector('input'); input?.focus(); input?.select() } else if (restoreFocus.current) { restoreFocus.current = false; actionsRef.current?.querySelector<HTMLButtonElement>('[aria-haspopup="menu"]')?.focus() } }, [editing])
  const cancelRename = () => { if (!savingRef.current) { restoreFocus.current = true; setEditing(false) } }
  const saveName = async () => {
    if (savingRef.current || !onSaveName) return
    const name = value.trim()
    if (!name || name.length > 80) { setFieldError(de.accounts.renameInvalid); return }
    savingRef.current = true; setSaving(true); setFieldError(undefined)
    try {
      const failure = await onSaveName(name)
      if (failure) setFieldError(failure)
      else { restoreFocus.current = true; setEditing(false) }
    } finally { savingRef.current = false; setSaving(false) }
  }
  const error = account.state === 'error' || account.state === 'auth_expired'
  const login = account.state === 'auth_expired' || account.error_code === 'auth_expired'
  const domain = account.email_address.split('@')[1] ?? ''
  const lower = domain.toLowerCase()
  const provider = ['google', 'gmail', 'google_mail'].includes(account.provider) ? de.accountCard.providers.google : ['microsoft', 'outlook'].includes(account.provider) ? de.accountCard.providers.microsoft : account.provider === 'imap' ? ['icloud.com', 'me.com', 'mac.com'].includes(lower) ? de.accountCard.providers.icloud : ['yahoo.com', 'ymail.com', 'rocketmail.com'].includes(lower) ? de.accountCard.providers.yahoo : domain : account.provider
  const errors: Record<string, unknown> = de.errors
  const codeText = errors[account.error_code]
  const status = account.state === 'auth_expired' ? de.accounts.state.auth_expired : account.state === 'error' ? typeof codeText === 'string' ? codeText : de.accounts.state.unknownError : account.state === 'syncing' ? de.accounts.state.syncing : account.state === 'ok' && account.last_sync_at ? de.accounts.state.stand(formatTime(new Date(account.last_sync_at))) : de.accounts.state.never
  const title = account.display_name || account.email_address
  const busy = account.state === 'syncing' || syncPending
  const reconnectTip = account.connection === 'connector' ? de.accounts.reconnectConnectorTip : account.connection === 'imap' ? de.accounts.reconnectImapTip : de.accounts.reconnectOauthTip(provider === de.accountCard.providers.microsoft ? 'Microsoft' : 'Google') // i18n-exempt
  return <div className="le-account"><Avatar name={title} address={account.email_address} colorIndex={account.color_index} size="lg" /><div className="le-account-content">{editing ? <form ref={formRef} className="le-account-rename" onSubmit={event => { event.preventDefault(); void saveName() }} onKeyDown={event => { if (event.key === 'Escape') { event.preventDefault(); cancelRename() } }}><TextField label={de.accounts.renameLabel} value={value} onChange={event => setValue(event.target.value)} error={fieldError} disabled={saving} /><div className="le-account-rename-actions"><Button variant="primary" type="submit" className="le-btn--sm" disabled={saving}>{de.accounts.renameSave}</Button><Button variant="ghost" className="le-btn--sm" disabled={saving} onClick={cancelRename}>{de.controls.cancel}</Button></div></form> : <div className="le-account-name" title={title}>{title}</div>}{title !== account.email_address && <small className="le-account-address le-muted" title={account.email_address}>{account.email_address}</small>}<div className="le-account-meta"><Tag tone="on-surface" dot={account.color_index}>{provider}</Tag><span className={`le-status le-status--${error ? 'error' : account.state === 'syncing' ? 'syncing' : 'ok'}`}>{account.state === 'syncing' ? <span className="le-spinner" /> : <Icon name={error ? 'circle-alert' : 'check'} size="sm" />}{status}</span><span className="le-num">{de.accountCard.messages(account.message_count)}</span>{account.unread > 0 && <Badge>{account.unread}</Badge>}<span>{de.accounts.connection[account.connection]}</span></div></div><div className="le-account-actions" ref={actionsRef}>{login ? <Tooltip content={reconnectTip}><Button variant="secondary" className="le-btn--sm" onClick={onReconnect}>{de.accountCard.reconnect}</Button></Tooltip> : <IconButton label={busy ? de.accounts.syncingLabel : de.accountCard.sync(account.email_address)} tip={de.accounts.syncTip} icon="refresh-cw" size={coarse ? 'lg' : 'md'} disabled={busy} onClick={onSync} />}<Menu trigger={props => <IconButton {...props} label={de.controls.moreAccount(title)} tip={de.accounts.moreTip} size={coarse ? 'lg' : 'md'} icon="more-horizontal" />} items={[{ label: de.accountCard.rename, icon: 'pencil', onSelect: () => { onRename(); if (onSaveName) { setValue(title); setFieldError(undefined); setEditing(true) } } }, { label: de.accountCard.remove, icon: 'trash-2', tone: 'danger', onSelect: onRemove }]} /></div></div>
}

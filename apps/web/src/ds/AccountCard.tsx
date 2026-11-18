import { useEffect, useRef, useState } from 'react'
import type { AccountOut } from '../api/generated/types.gen'
import { useI18n } from '../i18n/I18n'
import { formatTime } from '../i18n/format'
import { Avatar } from './Avatar'
import { Tag } from './Chip'
import { Button } from './Button'
import { Icon } from './Icon'
import { IconButton } from './IconButton'
import { Menu } from './Menu'
import { Tooltip } from './Tooltip'
import { TextField } from './TextField'
import { providerLabel } from './providerLabel'

export function AccountCard({ account, onSync, onReconnect, onRename, onRemove, onSaveName, syncPending = false, coarse = false }: { account: AccountOut; onSync: () => void; onReconnect: () => void; onRename: () => void; onRemove: () => void; onSaveName?: (name: string) => Promise<string | undefined>; syncPending?: boolean; coarse?: boolean }) {
  const { texts, locale } = useI18n()
  const [editing, setEditing] = useState(false), [value, setValue] = useState(''), [fieldError, setFieldError] = useState<string>(), [saving, setSaving] = useState(false)
  const formRef = useRef<HTMLFormElement>(null), actionsRef = useRef<HTMLDivElement>(null), restoreFocus = useRef(false), savingRef = useRef(false)
  useEffect(() => { if (editing) { const input = formRef.current?.querySelector('input'); input?.focus(); input?.select() } else if (restoreFocus.current) { restoreFocus.current = false; actionsRef.current?.querySelector<HTMLButtonElement>('[aria-haspopup="menu"]')?.focus() } }, [editing])
  const cancelRename = () => { if (!savingRef.current) { restoreFocus.current = true; setEditing(false) } }
  const saveName = async () => {
    if (savingRef.current || !onSaveName) return
    const name = value.trim()
    if (!name || name.length > 80) { setFieldError(texts.accounts.renameInvalid); return }
    savingRef.current = true; setSaving(true); setFieldError(undefined)
    try {
      const failure = await onSaveName(name)
      if (failure) setFieldError(failure)
      else { restoreFocus.current = true; setEditing(false) }
    } finally { savingRef.current = false; setSaving(false) }
  }
  const error = account.state === 'error' || account.state === 'auth_expired'
  const login = account.state === 'auth_expired' || account.error_code === 'auth_expired'
  const provider = providerLabel(account)
  const errors: Record<string, unknown> = texts.errors
  const codeText = errors[account.error_code]
  const status = account.state === 'auth_expired' ? account.connection === 'imap' ? texts.accounts.state.imapAuthExpired : texts.accounts.state.auth_expired : account.state === 'error' ? typeof codeText === 'string' ? codeText : texts.accounts.state.unknownError : account.state === 'syncing' ? texts.accounts.state.syncing : account.state === 'ok' && account.last_sync_at ? texts.accounts.state.stand(formatTime(new Date(account.last_sync_at), undefined, locale)) : texts.accounts.state.never
  const title = account.display_name || account.email_address
  const busy = account.state === 'syncing' || syncPending
  const reconnectTip = account.connection === 'connector' ? texts.accounts.reconnectConnectorTip : account.connection === 'imap' ? texts.accounts.reconnectImapTip : texts.accounts.reconnectOauthTip(['microsoft', 'outlook'].includes(account.provider) ? 'Microsoft' : 'Google') // i18n-exempt
  return <div className="le-account"><Avatar name={title} address={account.email_address} colorIndex={account.color_index} size="lg" /><div className="le-account-content">{editing ? <form ref={formRef} className="le-account-rename" onSubmit={event => { event.preventDefault(); void saveName() }} onKeyDown={event => { if (event.key === 'Escape') { event.preventDefault(); cancelRename() } }}><TextField label={texts.accounts.renameLabel} value={value} onChange={event => setValue(event.target.value)} error={fieldError} disabled={saving} /><div className="le-account-rename-actions"><Button variant="primary" type="submit" className="le-btn--sm" disabled={saving}>{texts.accounts.renameSave}</Button><Button variant="ghost" className="le-btn--sm" disabled={saving} onClick={cancelRename}>{texts.controls.cancel}</Button></div></form> : <div className="le-account-name" title={title}>{title}</div>}{title !== account.email_address && <small className="le-account-address le-muted" title={account.email_address}>{account.email_address}</small>}<div className="le-account-meta"><Tag tone="on-surface" dot={account.color_index}>{provider}</Tag><span className={`le-status le-status--${error ? 'error' : account.state === 'syncing' ? 'syncing' : 'ok'}`}>{account.state === 'syncing' ? <span className="le-spinner" /> : <Icon name={error ? 'circle-alert' : 'check'} size="sm" />}{status}</span><span className="le-num">{texts.accountCard.messages(account.message_count)}</span><span>{texts.accounts.connection[account.connection]}</span></div>{account.state === 'auth_expired' && account.connection === 'imap' && <p className="le-hint">{texts.accounts.state.imapAuthExplanation}</p>}</div><div className="le-account-actions" ref={actionsRef}>{login ? <Tooltip content={reconnectTip}><Button variant="secondary" className="le-btn--sm" onClick={onReconnect}>{texts.accountCard.reconnect}</Button></Tooltip> : <IconButton label={busy ? texts.accounts.syncingLabel : texts.accountCard.sync(account.email_address)} tip={texts.accounts.syncTip} icon="refresh-cw" size={coarse ? 'lg' : 'md'} disabled={busy} onClick={onSync} />}<Menu trigger={props => <IconButton {...props} label={texts.controls.moreAccount(title)} tip={texts.accounts.moreTip} size={coarse ? 'lg' : 'md'} icon="more-horizontal" />} items={[{ label: texts.accountCard.rename, icon: 'pencil', onSelect: () => { onRename(); if (onSaveName) { setValue(title); setFieldError(undefined); setEditing(true) } } }, { label: texts.accountCard.remove, icon: 'trash-2', tone: 'danger', onSelect: onRemove }]} /></div></div>
}

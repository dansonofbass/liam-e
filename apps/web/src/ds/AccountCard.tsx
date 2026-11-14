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

export function AccountCard({ account, onSync, onReconnect, onRename, onRemove, syncPending = false, coarse = false }: { account: AccountOut; onSync: () => void; onReconnect: () => void; onRename: () => void; onRemove: () => void; syncPending?: boolean; coarse?: boolean }) {
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
  return <div className="le-account"><Avatar name={title} address={account.email_address} colorIndex={account.color_index} size="lg" /><div className="le-account-content"><div className="le-account-name" title={title}>{title}</div>{title !== account.email_address && <small className="le-account-address le-muted" title={account.email_address}>{account.email_address}</small>}<div className="le-account-meta"><Tag tone="on-surface" dot={account.color_index}>{provider}</Tag><span className={`le-status le-status--${error ? 'error' : account.state === 'syncing' ? 'syncing' : 'ok'}`}>{account.state === 'syncing' ? <span className="le-spinner" /> : <Icon name={error ? 'circle-alert' : 'check'} size="sm" />}{status}</span><span className="le-num">{de.accountCard.messages(account.message_count)}</span>{account.unread > 0 && <Badge>{account.unread}</Badge>}<span>{de.accounts.connection[account.connection]}</span></div></div><div className="le-account-actions">{login ? <Tooltip content={reconnectTip}><Button variant="secondary" className="le-btn--sm" onClick={onReconnect}>{de.accountCard.reconnect}</Button></Tooltip> : <IconButton label={busy ? de.accounts.syncingLabel : de.accountCard.sync(account.email_address)} tip={de.accounts.syncTip} icon="refresh-cw" size={coarse ? 'lg' : 'md'} disabled={busy} onClick={onSync} />}<Menu trigger={props => <IconButton {...props} label={de.controls.moreAccount(title)} tip={de.accounts.moreTip} size={coarse ? 'lg' : 'md'} icon="more-horizontal" />} items={[{ label: de.accountCard.rename, icon: 'pencil', onSelect: onRename }, { label: de.accountCard.remove, icon: 'trash-2', tone: 'danger', onSelect: onRemove }]} /></div></div>
}

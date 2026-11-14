import type { AccountOut } from '../api/generated/types.gen'
import { de } from '../i18n/de'
import { formatTime } from '../i18n/format'
import { Avatar } from './Avatar'
import { Badge, Tag } from './Chip'
import { Button } from './Button'
import { Icon } from './Icon'
import { IconButton } from './IconButton'
import { Menu } from './Menu'
export function AccountCard({ account, onSync, onReconnect, onRename, onRemove }: { account: AccountOut; onSync: () => void; onReconnect: () => void; onRename: () => void; onRemove: () => void }) {
  const error = account.state === 'error' || account.state === 'auth_expired'
  const login = error && (account.state === 'auth_expired' || account.error_code === 'auth_expired')
  const errors: Record<string, string> = { auth_expired: de.errors.auth_expired, unreachable: de.errors.unreachable, host_not_allowed: de.errors.host_not_allowed, provider_error: de.errors.provider_error }
  const provider = de.accountCard.providers[account.provider as keyof typeof de.accountCard.providers] ?? account.provider
  const status = error ? (errors[account.error_code] ?? (login ? de.errors.auth_expired : de.accountCard.unknownError)) : account.state === 'syncing' ? de.accountCard.syncing : account.last_sync_at ? de.accountCard.stand(formatTime(new Date(account.last_sync_at))) : de.accountCard.never
  return <div className="le-account"><Avatar name={account.display_name} address={account.email_address} colorIndex={account.color_index} size="lg" /><div><div className="le-account-name">{account.email_address}</div><div className="le-account-meta"><Tag>{provider}</Tag><span className={`le-status le-status--${error ? 'error' : account.state === 'syncing' ? 'syncing' : 'ok'}`}>{account.state === 'syncing' ? <span className="le-spinner" /> : <Icon name={error ? 'circle-alert' : 'check'} size="sm" />}{status}</span><span>{de.accountCard.messages(account.message_count)}</span>{account.unread > 0 && <Badge>{account.unread}</Badge>}</div></div><div className="le-account-actions">{login ? <Button variant="secondary" className="le-btn--sm" onClick={onReconnect}>{de.accountCard.reconnect}</Button> : <IconButton label={de.accountCard.sync} icon="refresh-cw" disabled={account.state === 'syncing'} onClick={onSync} />}<Menu trigger={props => <IconButton {...props} label={de.controls.moreAccount(account.display_name || account.email_address)} icon="more-horizontal" />} items={[{ label: de.accountCard.rename, icon: 'pencil', onSelect: onRename }, { label: de.accountCard.remove, icon: 'trash-2', tone: 'danger', onSelect: onRemove }]} /></div></div>
}

import type { MailRefOut } from '../api/generated/types.gen'
import { de } from '../i18n/de'
import { formatRelativeDay, formatDeadline } from '../i18n/format'
import { Tag } from './Chip'
import { IconButton } from './IconButton'
export function MailReference({ mail, accountLabel, onOpen }: { mail: MailRefOut; accountLabel?: string; onOpen: () => void }) {
  return <div className="le-mailref le-rise"><div className="le-mailref-body"><div className="le-mailref-head"><strong>{mail.sender_name}</strong>{accountLabel && <Tag tone="on-surface" dot={mail.color_index}>{accountLabel}</Tag>}{mail.internal_date && <small>{formatRelativeDay(new Date(mail.internal_date), new Date())}</small>}</div><p>{de.mail.subjectText(mail.subject)}</p>{mail.deadline && <Tag tone="warm" icon="clock">{de.controls.deadline(formatDeadline(mail.deadline))}</Tag>}</div><div className="le-mailref-actions"><IconButton label={de.controls.openMail} icon="external-link" onClick={onOpen} /></div></div>
}

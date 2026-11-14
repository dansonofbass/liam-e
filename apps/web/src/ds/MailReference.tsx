import type { MailRefOut } from '../api/generated/types.gen'
import { de } from '../i18n/de'
import { formatListDate, formatDeadline } from '../i18n/format'
import { Tag } from './Chip'
import { IconButton } from './IconButton'
import { Tooltip } from './Tooltip'
// One muted line of the mail's opening text follows the subject.
// The warm dot marks a flagged mail; it names itself "Dringend" and shows that as a tooltip. Its place stays empty otherwise, so cards line up. The pencil asks for a draft and only shows when the card can start one.
export function MailReference({ mail, accountLabel, onOpen, onDraft, draftDisabled }: { mail: MailRefOut; accountLabel?: string; onOpen: () => void; onDraft?: () => void; draftDisabled?: boolean }) {
  return <div className="le-mailref le-rise">{mail.is_flagged ? <Tooltip content={de.controls.urgent}><span role="img" aria-label={de.controls.urgent} className="le-dot le-dot--warm le-mailref-dot" /></Tooltip> : <span className="le-dot le-dot--warm le-mailref-dot le-mailref-dot--none" aria-hidden="true" />}<div className="le-mailref-body"><div className="le-mailref-head"><strong>{mail.sender_name}</strong>{accountLabel && <Tag tone="on-surface" dot={mail.color_index}>{accountLabel}</Tag>}{mail.internal_date && <time className="caption le-muted le-num" dateTime={mail.internal_date}>{formatListDate(new Date(mail.internal_date), new Date())}</time>}</div><p>{de.mail.subjectText(mail.subject)}</p>{mail.snippet && <p className="small le-muted le-mailref-snippet">{mail.snippet}</p>}{mail.deadline && <Tag tone="warm" icon="clock">{de.controls.deadline(formatDeadline(mail.deadline))}</Tag>}</div><div className="le-mailref-actions"><IconButton label={de.controls.openMail} icon="external-link" onClick={onOpen} />{onDraft && <IconButton label={de.mail.draftReply} tip={de.controls.draftReplyTip} icon="pencil" disabled={draftDisabled} onClick={onDraft} />}</div></div>
}

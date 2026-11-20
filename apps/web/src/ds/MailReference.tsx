import type { MailRefOut } from '../api/generated/types.gen'
import { useI18n } from '../i18n/I18n'
import { formatListDate, formatDeadline } from '../i18n/format'
import { Tag } from './Chip'
import { IconButton } from './IconButton'
import { Icon } from './Icon'
import { Tooltip } from './Tooltip'
// One muted line of the mail's opening text follows the subject.
// The warm dot marks a flagged mail; it names itself "Dringend" and shows that as a tooltip. Its place stays empty otherwise, so cards line up. The pencil asks for a draft and only shows when the card can start one.
export function MailReference({ mail, accountLabel, onOpen, onDraft, draftDisabled, compact }: { mail: MailRefOut; accountLabel?: string; onOpen: () => void; onDraft?: () => void; draftDisabled?: boolean; compact?: boolean }) {
  const { texts, locale } = useI18n()
  if (compact) return <button type="button" className="le-mailref le-mailref--compact" onClick={onOpen}>
    <span className="le-sr">{texts.controls.openMail}</span>
    <span className="le-mailref-body">
      <strong>{texts.mail.subjectText(mail.subject)}</strong>
      <small className="le-muted">{mail.sender_name}{mail.sender_name && accountLabel && ' · '}{accountLabel && <span>{accountLabel}</span>}</small>
    </span>
    <Icon name="external-link" size="sm" />
  </button>
  return <div className="le-mailref le-rise">{mail.is_flagged ? <Tooltip content={texts.controls.urgent}><span role="img" aria-label={texts.controls.urgent} className="le-dot le-dot--warm le-mailref-dot" /></Tooltip> : <span className="le-dot le-dot--warm le-mailref-dot le-mailref-dot--none" aria-hidden="true" />}<div className="le-mailref-body"><div className="le-mailref-head"><strong>{mail.sender_name}</strong>{accountLabel && <Tag tone="on-surface" dot={mail.color_index}>{accountLabel}</Tag>}{mail.internal_date && <time className="caption le-muted le-num" dateTime={mail.internal_date}>{formatListDate(new Date(mail.internal_date), new Date(), undefined, locale)}</time>}</div><p>{texts.mail.subjectText(mail.subject)}</p>{mail.snippet && <p className="small le-muted le-mailref-snippet">{mail.snippet}</p>}{mail.deadline && <Tag tone="warm" icon="clock">{texts.controls.deadline(formatDeadline(mail.deadline, undefined, locale))}</Tag>}</div><div className="le-mailref-actions"><IconButton label={texts.controls.openMail} icon="external-link" onClick={onOpen} />{onDraft && <IconButton label={texts.mail.draftReply} tip={texts.controls.draftReplyTip} icon="pencil" disabled={draftDisabled} onClick={onDraft} />}</div></div>
}

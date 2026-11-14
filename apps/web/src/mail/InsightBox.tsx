import { useQuery } from '@tanstack/react-query'
import { insightQuery } from '../api/queries'
import { useChatSession } from '../chat/session'
import { Chip, Icon, Tag } from '../ds'
import { de } from '../i18n/de'
import { formatDeadline } from '../i18n/format'
import { useBreakpoint } from '../shell/useBreakpoint'

export function InsightBox({ id, onFollowup }: { id: string; onFollowup(text: string): void }) {
  const insight = useQuery({ ...insightQuery(id), retry: false })
  const { state } = useChatSession()
  const breakpoint = useBreakpoint()
  const busy = state.phase === 'working' || state.phase === 'streaming'
  const data = insight.data
  if (!insight.isPending && !insight.isError && data && !data.points.length && !data.deadline && !data.followups.length) return null
  return <section aria-label={de.mail.insightLabel} aria-busy={insight.isPending || undefined} className="le-insight">
    <div className="le-ai-meta"><span className="le-ai-mark"><Icon name="sparkle" size="sm" /></span>{de.mail.summary}{breakpoint !== 'mobile' && <small>{de.assistant.name}</small>}<span className="le-grow" />{data?.deadline && !insight.isError && <Tag tone="warm" icon="clock">{de.controls.deadline(formatDeadline(data.deadline))}</Tag>}</div>
    {insight.isPending && <><span className="le-sr" role="status">{de.mail.insightLoading}</span><div className="le-insight-placeholder" aria-hidden="true"><span className="le-insight-placeholder-line" /><span className="le-insight-placeholder-line" /><span className="le-insight-placeholder-line" /></div></>}
    {insight.isError && <div className="le-hint">{de.mail.insightError}</div>}
    {!insight.isError && data && <>{data.points.length > 0 && <ul className="le-insight-points">{data.points.slice(0, 3).map((point, index) => <li key={index}>{point}</li>)}</ul>}{data.followups.length > 0 && <div className="le-suggestions">{data.followups.slice(0, 2).map((text, index) => <Chip key={index} disabled={busy} onClick={() => onFollowup(text)}>{text}</Chip>)}</div>}</>}
  </section>
}

import { useQuery } from '@tanstack/react-query'
import { insightQuery } from '../api/queries'
import { useChatSession } from '../chat/session'
import { Chip, Icon, Tag } from '../ds'
import { useI18n } from '../i18n/I18n'
import { formatDeadline } from '../i18n/format'
import { useBreakpoint } from '../shell/useBreakpoint'

export function InsightBox({ id, onFollowup }: { id: string; onFollowup(text: string): void }) {
  const { texts, locale, browserLocale, localeReady } = useI18n()
  const insight = useQuery({ ...insightQuery(id, browserLocale), enabled: localeReady, retry: false })
  const { state } = useChatSession()
  const breakpoint = useBreakpoint()
  const busy = state.phase === 'working' || state.phase === 'streaming'
  const data = insight.data
  if (!insight.isPending && !insight.isError && data && !data.points.length && !data.deadline && !data.followups.length) return null
  return <section aria-label={texts.mail.insightLabel} aria-busy={insight.isPending || undefined} className="le-insight">
    <div className="le-ai-meta"><span className="le-ai-mark"><Icon name="sparkle" size="sm" /></span>{texts.mail.summary}{breakpoint !== 'mobile' && <small>{texts.assistant.name}</small>}<span className="le-grow" />{data?.deadline && !insight.isError && <Tag tone="warm" icon="clock">{texts.controls.deadline(formatDeadline(data.deadline, undefined, locale))}</Tag>}</div>
    {insight.isPending && <><span className="le-sr" role="status">{texts.mail.insightLoading}</span><div className="le-insight-placeholder" aria-hidden="true"><span className="le-insight-placeholder-line" /><span className="le-insight-placeholder-line" /><span className="le-insight-placeholder-line" /></div></>}
    {insight.isError && <div className="le-hint">{texts.mail.insightError}</div>}
    {!insight.isError && data && <>{data.points.length > 0 && <ul className="le-insight-points">{data.points.slice(0, 3).map((point, index) => <li key={index}>{point}</li>)}</ul>}{data.followups.length > 0 && <div className="le-suggestions">{data.followups.slice(0, 2).map((text, index) => <Chip key={index} disabled={busy} onClick={() => onFollowup(text)}>{text}</Chip>)}</div>}</>}
  </section>
}

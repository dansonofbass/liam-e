// i18n-exempt: CSS classes.
import type { SourceOut } from '../api/generated/types.gen'
import { Chip } from '../ds'
import { Dot } from '../ds/Chip'
import { Link } from '@tanstack/react-router'
import { useI18n } from '../i18n/I18n'
import { SourceStatus } from './CalendarPage'
import { covers, oldSource } from './state'

type Props = { sources: SourceOut[]; selected: string[]; onToggle(id: string): void; from: string; to: string }
export function SourceBar({ sources, selected, onToggle, from, to }: Props) {
  const { texts } = useI18n()
  const issues = sources.filter(s => !s.is_active || !!s.last_error || oldSource(s) || !covers(s, from, to))
  return <><div className="le-calendar-sources-row">{sources.filter(s => s.is_active).map((s, i) => <Chip quiet key={s.id} pressed={selected.includes(s.id)} onClick={() => onToggle(s.id)}><Dot colorIndex={i} />{s.name}</Chip>)}<Link to="/accounts" className="le-link le-calendar-manage">{texts.calendar.manage}</Link></div>
    {issues.length > 0 && <details className="le-calendar-issues"><summary>{texts.calendar.sourceDetails} ({issues.length})</summary>{issues.map(s => <SourceStatus key={s.id} source={s} from={from} to={to} />)}</details>}
  </>
}

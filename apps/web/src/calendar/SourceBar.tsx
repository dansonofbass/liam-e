// i18n-exempt: CSS classes.
import type { SourceOut } from '../api/generated/types.gen'
import { Chip } from '../ds'
import { de } from '../i18n/de'
import { SourceStatus } from './CalendarPage'
import { covers, oldSource } from './state'

type Props = { sources: SourceOut[]; selected: string[]; onToggle(id: string): void; from: string; to: string }
export function SourceBar({ sources, selected, onToggle, from, to }: Props) {
  const issues = sources.filter(s => !s.is_active || !!s.last_error || oldSource(s) || !covers(s, from, to))
  return <><div className="le-calendar-controls">{sources.filter(s => s.is_active).map((s, i) => <Chip key={s.id} pressed={selected.includes(s.id)} onClick={() => onToggle(s.id)}><span className={`le-source-dot le-source-dot--${i % 4 + 1}`} />{s.name}</Chip>)}</div>
    {issues.length > 0 && <details><summary>{de.calendar.sourceDetails} ({issues.length})</summary>{issues.map(s => <SourceStatus key={s.id} source={s} from={from} to={to} />)}</details>}
  </>
}

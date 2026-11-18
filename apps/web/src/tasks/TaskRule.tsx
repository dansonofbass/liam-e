// i18n-exempt: RFC 5545 fields and locale identifiers.
import { de } from '../i18n/de'
import { formatTaskRule } from './format'

/** Describe every supported rule field, including limits beyond the preview page. */
export function TaskRule({ rule }: { rule?: string | null }) {
  if (!rule) return <p>{de.tasks.recurrence}: {de.tasks.none}</p>
  const parts: Record<string, string | undefined> = Object.fromEntries(rule.split(';').map(value => value.split('=')))
  const days = ['MO', 'TU', 'WE', 'TH', 'FR', 'SA', 'SU']
  const until = parts.UNTIL
  const bound = until ? `${until.slice(6, 8)}.${until.slice(4, 6)}.${until.slice(0, 4)}${until.length > 8 ? ` · ${until.slice(9, 11)}:${until.slice(11, 13)} UTC` : ''}` : null
  return <section aria-label={de.tasks.recurrence}><p>{de.tasks.recurrence}: {formatTaskRule(rule)}</p><dl>
    <dt>{de.tasks.frequency}</dt><dd>{parts.FREQ === 'DAILY' ? de.tasks.daily : parts.FREQ === 'WEEKLY' ? de.tasks.weekly : de.tasks.monthly}</dd>
    <dt>{de.tasks.interval}</dt><dd>{parts.INTERVAL ?? '1'}</dd>
    {parts.BYDAY && <><dt>{de.tasks.weekdays}</dt><dd>{parts.BYDAY.split(',').map(day => de.tasks.days[days.indexOf(day)]).join(', ')}</dd></>}
    {parts.BYMONTHDAY && <><dt>{de.tasks.monthday}</dt><dd>{parts.BYMONTHDAY.split(',').map(day => Number(day) < 0 ? de.taskChat.monthEnd(-Number(day)) : de.tasks.dayNumber(Number(day))).join(', ')}</dd></>}
    {parts.BYMONTH && <><dt>{de.taskChat.months}</dt><dd>{parts.BYMONTH.split(',').map(month => new Intl.DateTimeFormat('de-DE', { month: 'long', timeZone: 'UTC' }).format(new Date(Date.UTC(2027, Number(month) - 1, 1)))).join(', ')}</dd></>}
    {parts.COUNT && <><dt>{de.tasks.count}</dt><dd>{parts.COUNT}</dd></>}
    {bound && <><dt>{de.taskChat.until}</dt><dd>{bound}</dd></>}
    {!parts.COUNT && !bound && <><dt>{de.tasks.end}</dt><dd>{de.tasks.noEnd}</dd></>}
  </dl></section>
}

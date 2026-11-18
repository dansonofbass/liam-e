// i18n-exempt: RFC 5545 fields and locale identifiers.
import { useI18n } from '../i18n/I18n'
import { formatTaskRule } from './format'

/** Describe every supported rule field, including limits beyond the preview page. */
export function TaskRule({ rule }: { rule?: string | null }) {
  const { texts, locale, localeTag } = useI18n()
  if (!rule) return <p>{texts.tasks.recurrence}: {texts.tasks.none}</p>
  const parts: Record<string, string | undefined> = Object.fromEntries(rule.split(';').map(value => value.split('=')))
  const days = ['MO', 'TU', 'WE', 'TH', 'FR', 'SA', 'SU']
  const until = parts.UNTIL
  const bound = until ? `${until.slice(6, 8)}.${until.slice(4, 6)}.${until.slice(0, 4)}${until.length > 8 ? ` · ${until.slice(9, 11)}:${until.slice(11, 13)} UTC` : ''}` : null
  return <section aria-label={texts.tasks.recurrence}><p>{texts.tasks.recurrence}: {formatTaskRule(rule, locale)}</p><dl>
    <dt>{texts.tasks.frequency}</dt><dd>{parts.FREQ === 'DAILY' ? texts.tasks.daily : parts.FREQ === 'WEEKLY' ? texts.tasks.weekly : texts.tasks.monthly}</dd>
    <dt>{texts.tasks.interval}</dt><dd>{parts.INTERVAL ?? '1'}</dd>
    {parts.BYDAY && <><dt>{texts.tasks.weekdays}</dt><dd>{parts.BYDAY.split(',').map(day => texts.tasks.days[days.indexOf(day)]).join(', ')}</dd></>}
    {parts.BYMONTHDAY && <><dt>{texts.tasks.monthday}</dt><dd>{parts.BYMONTHDAY.split(',').map(day => Number(day) < 0 ? texts.taskChat.monthEnd(-Number(day)) : texts.tasks.dayNumber(Number(day))).join(', ')}</dd></>}
    {parts.BYMONTH && <><dt>{texts.taskChat.months}</dt><dd>{parts.BYMONTH.split(',').map(month => new Intl.DateTimeFormat(localeTag, { month: 'long', timeZone: 'UTC' }).format(new Date(Date.UTC(2027, Number(month) - 1, 1)))).join(', ')}</dd></>}
    {parts.COUNT && <><dt>{texts.tasks.count}</dt><dd>{parts.COUNT}</dd></>}
    {bound && <><dt>{texts.taskChat.until}</dt><dd>{bound}</dd></>}
    {!parts.COUNT && !bound && <><dt>{texts.tasks.end}</dt><dd>{texts.tasks.noEnd}</dd></>}
  </dl></section>
}

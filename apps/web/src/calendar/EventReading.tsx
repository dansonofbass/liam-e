// i18n-exempt: CSS classes and Intl locale identifiers.
import type { LiveEvent } from '../api/generated/types.gen'
import { useI18n } from '../i18n/I18n'
import { catalogue } from '../i18n/catalogue'
import { REFERENCE_LOCALE, intlLocale, type Locale } from '../i18n/locales'
import { addDays, browserZone, calendarDate, calendarTime } from './state'

export function eventWhen(row: LiveEvent, locale: Locale = REFERENCE_LOCALE): string {
  const texts = catalogue(locale)
  const day = row.start_date ?? row.start_at
  if (!day) return texts.calendar.missing
  const weekday = new Intl.DateTimeFormat(intlLocale[locale], { weekday: 'long', timeZone: row.start_date ? 'UTC' : browserZone() }).format(new Date(day))
  if (row.start_date) return `${weekday}, ${calendarDate(row.start_date, undefined, locale)}${row.end_date && addDays(row.end_date, -1) !== row.start_date ? ` – ${calendarDate(addDays(row.end_date, -1), undefined, locale)}` : ''} · ${texts.calendar.allDay}`
  return `${weekday}, ${calendarDate(day, undefined, locale)} · ${calendarTime(day, undefined, locale)} – ${row.end_at ? `${calendarDate(row.end_at, undefined, locale)} ${calendarTime(row.end_at, undefined, locale)}` : ''}`
}
export function EventReading({ event }: { event: LiveEvent }) {
  const { locale } = useI18n()
  return <div className="le-event-reading"><strong>{event.title}</strong><p>{eventWhen(event, locale)}</p>{event.location && <p>{event.location}</p>}{event.description && <p className="le-event-description">{event.description}</p>}</div>
}

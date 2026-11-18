// i18n-exempt: CSS classes and Intl locale identifiers.
import type { LiveEvent } from '../api/generated/types.gen'
import { de } from '../i18n/de'
import { addDays, browserZone, calendarDate, calendarTime } from './state'

export function eventWhen(row: LiveEvent): string {
  const day = row.start_date ?? row.start_at
  if (!day) return de.calendar.missing
  const weekday = new Intl.DateTimeFormat('de-DE', { weekday: 'long', timeZone: row.start_date ? 'UTC' : browserZone() }).format(new Date(day))
  if (row.start_date) return `${weekday}, ${calendarDate(row.start_date)}${row.end_date && addDays(row.end_date, -1) !== row.start_date ? ` – ${calendarDate(addDays(row.end_date, -1))}` : ''} · ${de.calendar.allDay}`
  return `${weekday}, ${calendarDate(day)} · ${calendarTime(day)} – ${row.end_at ? `${calendarDate(row.end_at)} ${calendarTime(row.end_at)}` : ''}`
}
export function EventReading({ event }: { event: LiveEvent }) {
  return <div className="le-event-reading"><strong>{event.title}</strong><p>{eventWhen(event)}</p>{event.location && <p>{event.location}</p>}{event.description && <p className="le-event-description">{event.description}</p>}</div>
}

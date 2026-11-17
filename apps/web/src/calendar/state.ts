import type { SourceOut, ApiRoutersApiV1CalendarSchemasOccurrenceOut as OccurrenceOut } from '../api/generated/types.gen'

const DAY = 86_400_000
export const todayUTC = () => new Date().toISOString().slice(0, 10)
export const addDays = (date: string, count: number) => new Date(Date.parse(date) + count * DAY).toISOString().slice(0, 10)
export function validWindow(from: string, to: string) {
  const days = (Date.parse(to) - Date.parse(from)) / DAY
  return /^\d{4}-\d{2}-\d{2}$/.test(from) && /^\d{4}-\d{2}-\d{2}$/.test(to) && days > 0 && days <= 90
}
export function covers(source: SourceOut, from: string, to: string) {
  return source.is_active && !source.stale && !source.incomplete && !!source.last_success_at &&
    !!source.coverage_start && !!source.coverage_end && Date.parse(source.coverage_start) <= Date.parse(from) && Date.parse(source.coverage_end) >= Date.parse(to)
}
export const oldSource = (source: SourceOut, now = Date.now()) => !source.last_success_at || now - Date.parse(source.last_success_at) > DAY
// Use UTC days consistently with the API's date-window contract, not the browser zone.
export const occurrenceDay = (row: OccurrenceOut) => row.start_date ?? row.start_at?.slice(0, 10) ?? ''
export const calendarDate = (value: string) => new Intl.DateTimeFormat('de-DE', { dateStyle: 'medium', timeZone: 'UTC' }).format(new Date(value))
export const calendarTime = (value: string) => new Intl.DateTimeFormat('de-DE', { hour: '2-digit', minute: '2-digit', timeZone: 'UTC' }).format(new Date(value))

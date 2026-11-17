import type { SourceOut, ApiRoutersApiV1CalendarSchemasOccurrenceOut as OccurrenceOut } from '../api/generated/types.gen'

const DAY = 86_400_000
export const browserZone = () => Intl.DateTimeFormat().resolvedOptions().timeZone
export function localDay(value: string | Date, timeZone = browserZone()) {
  const parts = new Intl.DateTimeFormat('en-CA', { timeZone, year: 'numeric', month: '2-digit', day: '2-digit' }).formatToParts(new Date(value))
  const part = (type: string) => parts.find(p => p.type === type)!.value
  return `${part('year')}-${part('month')}-${part('day')}`
}
export const todayLocal = () => localDay(new Date())
export const addDays = (date: string, count: number) => new Date(Date.parse(date) + count * DAY).toISOString().slice(0, 10)
export function validWindow(from: string, to: string) {
  const days = (Date.parse(to) - Date.parse(from)) / DAY
  return /^\d{4}-\d{2}-\d{2}$/.test(from) && /^\d{4}-\d{2}-\d{2}$/.test(to) && days > 0 && days <= 90
}
/** Find the first instant of a local date, including shortened DST days. */
export function localBoundary(date: string, timeZone = browserZone()) {
  let low = Date.parse(date) - 2 * DAY, high = Date.parse(date) + 2 * DAY
  while (low < high) {
    const middle = Math.floor((low + high) / 2)
    if (localDay(new Date(middle), timeZone) < date) low = middle + 1
    else high = middle
  }
  return low
}
/** The API accepts whole UTC dates only. Cover local timed bounds AND all-day dates. */
export function queryWindows(from: string, to: string, timeZone = browserZone()) {
  if (!validWindow(from, to)) return []
  const start = Math.min(Date.parse(from), Math.floor(localBoundary(from, timeZone) / DAY) * DAY)
  const end = Math.max(Date.parse(to), Math.ceil(localBoundary(to, timeZone) / DAY) * DAY)
  const windows: { from: string; to: string }[] = []
  for (let at = start; at < end; at += 90 * DAY) windows.push({ from: new Date(at).toISOString().slice(0, 10), to: new Date(Math.min(at + 90 * DAY, end)).toISOString().slice(0, 10) })
  return windows
}
export function covers(source: SourceOut, from: string, to: string, timeZone = browserZone()) {
  if (!validWindow(from, to)) return false
  return source.is_active && !source.stale && !source.incomplete && !!source.last_success_at &&
    !!source.coverage_start && !!source.coverage_end &&
    Date.parse(source.coverage_start) <= Math.min(Date.parse(from), localBoundary(from, timeZone)) &&
    Date.parse(source.coverage_end) >= Math.max(Date.parse(to), localBoundary(to, timeZone))
}
export const oldSource = (source: SourceOut, now = Date.now()) => !source.last_success_at || now - Date.parse(source.last_success_at) > DAY
export const occurrenceDay = (row: OccurrenceOut, timeZone = browserZone()) => row.start_date ?? (row.start_at ? localDay(row.start_at, timeZone) : '')
export function inLocalWindow(row: OccurrenceOut, from: string, to: string, timeZone = browserZone()) {
  const day = occurrenceDay(row, timeZone)
  return day >= from && day < to
}
export const calendarDate = (value: string, timeZone = browserZone()) => new Intl.DateTimeFormat('de-DE', { dateStyle: 'medium', timeZone: /^\d{4}-\d{2}-\d{2}$/.test(value) ? 'UTC' : timeZone }).format(new Date(value))
export const calendarTime = (value: string, timeZone = browserZone()) => new Intl.DateTimeFormat('de-DE', { hour: '2-digit', minute: '2-digit', timeZone }).format(new Date(value))

import { REFERENCE_LOCALE, intlLocale, type Locale } from '../i18n/locales'
import type { ApiRoutersApiV1CalendarSchemasOccurrenceOut as OccurrenceOut } from '../api/generated/types.gen'
import { addDays, browserZone, localBoundary } from './state'
import type { CalendarView } from './url'
export type { CalendarView } from './url'

const DAY = 86_400_000
const monday = (date: string) => addDays(date, -((new Date(date).getUTCDay() + 6) % 7))
export function visibleRange(view: CalendarView, date: string): { from: string; to: string } {
  const from = view === 'month' ? monday(`${date.slice(0, 7)}-01`) : view === 'week' ? monday(date) : date
  return { from, to: addDays(from, view === 'month' ? 42 : view === 'day' ? 1 : 7) }
}
export function shift(view: CalendarView, date: string, step: -1 | 1): string {
  if (view !== 'month') return addDays(date, step * (view === 'day' ? 1 : 7))
  const d = new Date(`${date.slice(0, 7)}-01T00:00:00Z`)
  d.setUTCMonth(d.getUTCMonth() + step)
  const end = new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth() + 1, 0)).getUTCDate()
  d.setUTCDate(Math.min(Number(date.slice(8, 10)), end))
  return d.toISOString().slice(0, 10)
}
export function periodTitle(view: CalendarView, date: string, locale: Locale = REFERENCE_LOCALE): string {
  const format = (day: string, options: Intl.DateTimeFormatOptions) => new Intl.DateTimeFormat(intlLocale[locale], { ...options, timeZone: 'UTC' }).format(new Date(day))
  if (view === 'month') return format(date, { month: 'long', year: 'numeric' })
  if (view === 'day') return format(date, { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' })
  const { from, to } = visibleRange(view, date)
  const end = addDays(to, -1)
  return new Intl.DateTimeFormat(intlLocale[locale], { day: 'numeric', month: 'long', year: 'numeric', timeZone: 'UTC' }).formatRange(new Date(from), new Date(end)).replace(/\s*–\s*/, '–')
}
export function monthCells(date: string): { day: string; inMonth: boolean }[] {
  const { from } = visibleRange('month', date)
  return Array.from({ length: 42 }, (_, i) => { const day = addDays(from, i); return { day, inMonth: day.slice(0, 7) === date.slice(0, 7) } })
}
export type Placed = { row: OccurrenceOut; day: string; startMinute: number; endMinute: number; column: number; columns: number }
const wallClock = (timeZone: string) => new Intl.DateTimeFormat('de-DE', { hour: '2-digit', minute: '2-digit', hourCycle: 'h23', timeZone })
/** Minutes since local midnight on the wall clock, the scale of the hour gutter on every day. */
export function wallMinute(instant: number, timeZone = browserZone()) {
  const [hours, minutes] = wallClock(timeZone).format(instant).split(':').map(Number)
  return hours! * 60 + minutes!
}
/** Wall-clock hours that exist on a local day: a spring-forward day skips one. */
export function dayHours(day: string, timeZone = browserZone()): number[] {
  const start = localBoundary(day, timeZone), end = localBoundary(addDays(day, 1), timeZone)
  const clock = wallClock(timeZone)
  const hours = new Set<number>()
  for (let t = start; t < end; t += 15 * 60_000) {
    const time = clock.format(t)
    if (time.endsWith(':00')) hours.add(Number(time.slice(0, 2)))
  }
  return [...hours].sort((a, b) => a - b)
}
/**
 * Places timed appointments on the wall clock of one local day. Lanes use the drawn extent:
 * an appointment is drawn at least `minMinutes` tall, so a shorter one must not share a lane
 * with the next appointment inside that extent.
 */
export function layoutDay(rows: OccurrenceOut[], day: string, timeZone = browserZone(), minMinutes = 0): Placed[] {
  const start = localBoundary(day, timeZone), end = localBoundary(addDays(day, 1), timeZone)
  const placed: Placed[] = []
  for (const row of rows) {
    if (!row.start_at || !row.end_at || row.start_date) continue
    const a = Date.parse(row.start_at), b = Date.parse(row.end_at)
    if (!Number.isFinite(a) || !Number.isFinite(b) || b < a || a >= end || (b <= start && a !== b)) continue
    if (a === b && a < start) continue
    const startMinute = wallMinute(Math.max(a, start), timeZone)
    let endMinute = a === b ? Math.min(1440, startMinute + 15) : b >= end ? 1440 : wallMinute(b, timeZone)
    // Across the repeated hour of a fall-back day the wall clock runs backwards: keep the real length.
    if (a !== b && endMinute <= startMinute) endMinute = Math.min(1440, startMinute + (Math.min(b, end) - Math.max(a, start)) / 60_000)
    placed.push({ row, day, startMinute, endMinute, column: 0, columns: 1 })
  }
  placed.sort((a, b) => a.startMinute - b.startMinute || a.endMinute - b.endMinute)
  let group: Placed[] = [], ends: number[] = [], groupEnd = -1
  const finish = () => { for (const p of group) p.columns = ends.length }
  for (const p of placed) {
    const reach = Math.max(p.endMinute, p.startMinute + minMinutes)
    if (p.startMinute >= groupEnd) { finish(); group = []; ends = []; groupEnd = -1 }
    let col = ends.findIndex(endMinute => endMinute <= p.startMinute)
    if (col < 0) { col = ends.length; ends.push(reach) } else ends[col] = reach
    p.column = col; group.push(p); groupEnd = Math.max(groupEnd, reach)
  }
  finish()
  return placed
}
export function allDaySpans(rows: OccurrenceOut[], from: string, to: string): { row: OccurrenceOut; startCol: number; span: number }[] {
  return rows.flatMap(row => {
    if (!row.start_date || !row.end_date || row.start_date >= to || row.end_date <= from) return []
    const start = row.start_date < from ? from : row.start_date, end = row.end_date > to ? to : row.end_date
    return [{ row, startCol: (Date.parse(start) - Date.parse(from)) / DAY, span: (Date.parse(end) - Date.parse(start)) / DAY }]
  })
}

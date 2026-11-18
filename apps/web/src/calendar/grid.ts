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
export function periodTitle(view: CalendarView, date: string): string {
  const format = (day: string, options: Intl.DateTimeFormatOptions) => new Intl.DateTimeFormat('de-DE', { ...options, timeZone: 'UTC' }).format(new Date(day))
  if (view === 'month') return format(date, { month: 'long', year: 'numeric' })
  if (view === 'day') return format(date, { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' })
  const { from, to } = visibleRange(view, date)
  const end = addDays(to, -1)
  return new Intl.DateTimeFormat('de-DE', { day: 'numeric', month: 'long', year: 'numeric', timeZone: 'UTC' }).formatRange(new Date(from), new Date(end)).replace(/\s*–\s*/, '–')
}
export function monthCells(date: string): { day: string; inMonth: boolean }[] {
  const { from } = visibleRange('month', date)
  return Array.from({ length: 42 }, (_, i) => { const day = addDays(from, i); return { day, inMonth: day.slice(0, 7) === date.slice(0, 7) } })
}
export type Placed = { row: OccurrenceOut; day: string; startMinute: number; endMinute: number; column: number; columns: number }
export function layoutDay(rows: OccurrenceOut[], day: string, timeZone = browserZone()): Placed[] {
  const start = localBoundary(day, timeZone), end = localBoundary(addDays(day, 1), timeZone)
  const placed: Placed[] = []
  for (const row of rows) {
    if (!row.start_at || !row.end_at || row.start_date) continue
    const a = Date.parse(row.start_at), b = Date.parse(row.end_at)
    if (!Number.isFinite(a) || !Number.isFinite(b) || b < a || a >= end || (b <= start && a !== b)) continue
    if (a === b && a < start) continue
    const startMinute = (Math.max(a, start) - start) / 60_000
    const endMinute = a === b ? Math.min((end - start) / 60_000, startMinute + 15) : (Math.min(b, end) - start) / 60_000
    placed.push({ row, day, startMinute, endMinute, column: 0, columns: 1 })
  }
  placed.sort((a, b) => a.startMinute - b.startMinute || a.endMinute - b.endMinute)
  let group: Placed[] = [], ends: number[] = [], groupEnd = -1
  const finish = () => { for (const p of group) p.columns = ends.length }
  for (const p of placed) {
    if (p.startMinute >= groupEnd) { finish(); group = []; ends = []; groupEnd = -1 }
    let col = ends.findIndex(endMinute => endMinute <= p.startMinute)
    if (col < 0) { col = ends.length; ends.push(p.endMinute) } else ends[col] = p.endMinute
    p.column = col; group.push(p); groupEnd = Math.max(groupEnd, p.endMinute)
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

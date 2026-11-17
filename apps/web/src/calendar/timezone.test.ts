import { expect, test } from 'bun:test'
import type { ApiRoutersApiV1CalendarSchemasOccurrenceOut as OccurrenceOut } from '../api/generated/types.gen'
import { calendarDate, calendarTime, inLocalWindow, localBoundary, occurrenceDay, queryWindows, validWindow } from './state'

const timed = (start_at: string): OccurrenceOut => ({ id: 'test-only', source_id: 'test-only', event_id: 'test-only', title: 'Planung', start_date: null, end_date: null, start_at, end_at: start_at, timezone: 'UTC' })
for (const zone of ['Europe/Berlin', 'America/Los_Angeles']) {
  test(`${zone}: midnight, grouping and padded-window filtering`, () => {
    const boundary = localBoundary('2026-11-13', zone)
    const before = timed(new Date(boundary - 1000).toISOString())
    const after = timed(new Date(boundary + 1000).toISOString())
    expect(occurrenceDay(before, zone)).toBe('2026-11-12')
    expect(occurrenceDay(after, zone)).toBe('2026-11-13')
    expect(inLocalWindow(before, '2026-11-13', '2026-11-14', zone)).toBe(false)
    expect(inLocalWindow(after, '2026-11-13', '2026-11-14', zone)).toBe(true)
    expect(calendarTime(after.start_at!, zone)).toBe('00:00')
    expect(calendarDate(after.start_at!, zone)).toBe('13.11.2026')
    const allDay = { ...after, start_at: null, end_at: null, start_date: '2026-11-13', end_date: '2026-11-14' }
    expect(occurrenceDay(allDay, zone)).toBe('2026-11-13')
    expect(calendarDate(allDay.start_date, zone)).toBe('13.11.2026')
    expect(inLocalWindow(allDay, '2026-11-13', '2026-11-14', zone)).toBe(true)
    const windows = queryWindows('2026-11-13', '2026-11-14', zone)
    expect(Date.parse(windows[0]!.from)).toBeLessThanOrEqual(boundary)
    expect(Date.parse(windows.at(-1)!.to)).toBeGreaterThanOrEqual(localBoundary('2026-11-14', zone))
  })
  test(`${zone}: a 90-local-day selection uses bounded adjacent API windows`, () => {
    const windows = queryWindows('2026-01-01', '2026-04-01', zone)
    expect(windows).toHaveLength(2)
    expect(windows.every(w => validWindow(w.from, w.to))).toBe(true)
    expect(windows[0]!.to).toBe(windows[1]!.from)
  })
}
test('DST boundaries use actual instants rather than adding 24 hours', () => {
  expect(localBoundary('2026-03-30', 'Europe/Berlin') - localBoundary('2026-03-29', 'Europe/Berlin')).toBe(23 * 3600000)
  expect(localBoundary('2026-11-02', 'America/Los_Angeles') - localBoundary('2026-11-01', 'America/Los_Angeles')).toBe(25 * 3600000)
})
test('the same instant belongs to different local calendar days', () => {
  const row = timed('2026-11-13T00:30:00Z')
  expect(occurrenceDay(row, 'Europe/Berlin')).toBe('2026-11-13')
  expect(occurrenceDay(row, 'America/Los_Angeles')).toBe('2026-11-12')
})

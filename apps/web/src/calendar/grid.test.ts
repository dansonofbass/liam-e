import { expect, test } from 'bun:test'
import type { ApiRoutersApiV1CalendarSchemasOccurrenceOut as OccurrenceOut } from '../api/generated/types.gen'
import { allDaySpans, layoutDay, monthCells, periodTitle, shift, visibleRange } from './grid'

const timed = (id: string, start_at: string, end_at: string): OccurrenceOut => ({ id, event_id: id, source_id: 'test-only', title: 'Termin', start_at, end_at, start_date: null, end_date: null, timezone: 'Europe/Berlin' })

test('visible ranges, titles and navigation use calendar dates', () => {
  expect(visibleRange('week', '2026-11-18')).toEqual({ from: '2026-11-16', to: '2026-11-23' })
  expect(visibleRange('month', '2026-11-18')).toEqual({ from: '2026-10-26', to: '2026-12-07' })
  expect(monthCells('2026-11-18')).toHaveLength(42)
  expect(shift('week', '2026-12-30', 1)).toBe('2027-01-06')
  expect(periodTitle('week', '2026-11-18')).toBe('16.–22. November 2026')
})
test('overlap groups and midnight clipping', () => {
  const rows = [timed('a', '2026-11-18T08:00:00Z', '2026-11-18T10:00:00Z'), timed('b', '2026-11-18T09:00:00Z', '2026-11-18T11:00:00Z'), timed('c', '2026-11-18T12:00:00Z', '2026-11-18T13:00:00Z')]
  expect(layoutDay(rows, '2026-11-18', 'Europe/Berlin').map(p => p.columns)).toEqual([2, 2, 1])
  const overnight = timed('d', '2026-11-18T22:00:00Z', '2026-11-19T00:00:00Z')
  expect(layoutDay([overnight], '2026-11-18', 'Europe/Berlin')[0]).toMatchObject({ startMinute: 1380, endMinute: 1440 })
  expect(layoutDay([overnight], '2026-11-19', 'Europe/Berlin')[0]).toMatchObject({ startMinute: 0, endMinute: 60 })
})
test('day placement uses elapsed minutes on DST transitions', () => {
  const first = timed('a', '2026-10-25T00:30:00Z', '2026-10-25T00:45:00Z')
  const second = timed('b', '2026-10-25T01:30:00Z', '2026-10-25T01:45:00Z')
  expect(layoutDay([first, second], '2026-10-25', 'Europe/Berlin').map(p => p.startMinute)).toEqual([150, 210])
  expect(layoutDay([timed('c', '2026-03-29T01:00:00Z', '2026-03-29T01:15:00Z')], '2026-03-29', 'Europe/Berlin')[0]?.startMinute).toBe(120)
})
test('all-day spans clip to an exclusive range', () => {
  const row: OccurrenceOut = { ...timed('a', '', ''), start_at: null, end_at: null, start_date: '2026-11-20', end_date: '2026-11-23' }
  expect(allDaySpans([row], '2026-11-16', '2026-11-23')).toEqual([{ row, startCol: 4, span: 3 }])
})

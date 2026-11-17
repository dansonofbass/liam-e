import { expect, test } from 'bun:test'
import type { SourceOut } from '../api/generated/types.gen'
import { addDays, covers, oldSource, validWindow, occurrenceDay } from './state'

const source: SourceOut = { id: 'test-only', name: 'Arbeit', provider: 'google', timezone: 'UTC', is_active: true, capabilities: ['read'], coverage_start: '2026-11-01T00:00:00Z', coverage_end: '2026-12-01T00:00:00Z', last_success_at: '2026-11-13T10:00:00Z', stale: false, incomplete: false }
test('calendar windows are bounded and exclusive', () => {
  expect(validWindow('2026-11-01', addDays('2026-11-01', 90))).toBe(true)
  expect(validWindow('2026-11-01', addDays('2026-11-01', 91))).toBe(false)
  expect(validWindow('2026-11-01', '2026-11-01')).toBe(false)
  expect(validWindow('', '2026-11-01')).toBe(false)
})
test('absence requires successful active complete coverage for either provider', () => {
  for (const provider of ['ics', 'google']) {
    expect(covers({ ...source, provider }, '2026-11-01', '2026-12-01')).toBe(true)
    for (const patch of [{ is_active: false }, { stale: true }, { incomplete: true }, { last_success_at: null }, { coverage_start: null }]) {
      expect(covers({ ...source, provider, ...patch }, '2026-11-01', '2026-12-01')).toBe(false)
    }
  }
  expect(covers(source, '2026-11-01', '2026-12-02')).toBe(false)
})
test('age is distinct from index completeness', () => {
  expect(oldSource(source, Date.parse('2026-11-15T10:00:00Z'))).toBe(true)
  expect(covers(source, '2026-11-13', '2026-11-14')).toBe(true)
})
test('all-day dates are not shifted by browser timezone', () => {
  expect(occurrenceDay({ id: 'test-only', source_id: source.id, event_id: 'test-only', title: 'Planung', start_date: '2026-11-13', end_date: '2026-11-14', start_at: null, end_at: null, timezone: null })).toBe('2026-11-13')
})

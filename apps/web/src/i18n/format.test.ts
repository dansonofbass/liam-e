import { expect, test } from 'bun:test'
import { plural, formatTime, formatDayShort, formatRelativeDay, formatBytes, formatStand } from './format'

test('formats German dates, numbers and plurals', () => {
  const tz = 'Europe/Berlin' // i18n-exempt
  expect(formatDayShort(new Date('2026-11-20T10:00:00+01:00'), tz)).toBe('Fr., 20.11.')
  expect(formatTime(new Date('2026-11-13T08:57:00+01:00'), tz)).toBe('08:57')
  expect(plural(1, { one: '# Konto', other: '# Konten' })).toBe('1 Konto')
  expect(plural(4, { one: '# Konto', other: '# Konten' })).toBe('4 Konten')
  expect(formatBytes(217088)).toBe('212 KB')
  expect(formatStand(4, new Date('2026-11-13T08:57:00+01:00'), tz)).toBe('4 Konten · Stand 08:57')
})

test('formats weekdays and older dates in the requested time zone', () => {
  const tz = 'Europe/Berlin' // i18n-exempt
  const now = new Date('2026-11-13T10:00:00+01:00')
  expect(formatRelativeDay(new Date('2026-11-11T09:00:00+01:00'), now, tz)).toBe('Mi.')
  expect(formatRelativeDay(new Date('2026-11-09T09:00:00+01:00'), now, tz)).toBe('Mo.')
})

test('formats older dates and preserves New Year relative days', () => {
  const tz = 'Europe/Berlin' // i18n-exempt
  const now = new Date('2026-11-13T10:00:00+01:00')
  expect(formatRelativeDay(new Date('2026-11-07T09:00:00+01:00'), now, tz)).toBe('7.11.')
  expect(formatRelativeDay(new Date('2025-12-31T09:00:00+01:00'), new Date('2026-01-05T10:00:00+01:00'), tz)).toBe('31.12.2025')
  expect(formatRelativeDay(new Date('2025-12-31T20:00:00+01:00'), new Date('2026-01-01T10:00:00+01:00'), tz)).toBe('Gestern')
  expect(formatRelativeDay(new Date('2025-12-29T09:00:00+01:00'), new Date('2026-01-02T10:00:00+01:00'), tz)).toBe('Mo.')
  expect(formatRelativeDay(new Date('2025-12-31T23:30:00Z'), new Date('2026-01-05T10:00:00+01:00'), tz)).toBe('1.1.')
})

test('uses calendar days in the requested time zone', () => {
  const now = new Date('2026-11-13T00:10:00+01:00')
  expect(formatRelativeDay(new Date('2026-11-12T23:50:00+01:00'), now, 'Europe/Berlin')).toBe('Gestern')
  expect(formatRelativeDay(new Date('2026-11-13T00:05:00+01:00'), now, 'Europe/Berlin')).toBe('Heute')
})

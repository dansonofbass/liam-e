import { expect, test } from 'bun:test'
import { plural, formatTime, formatDayShort, formatRelativeDay, formatBytes, formatStand } from './format'

test('formats German dates, numbers and plurals', () => {
  const tz = 'Europe/Berlin' // i18n-exempt
  expect(formatDayShort(new Date('2026-11-20T10:00:00+01:00'), tz)).toBe('Fr., 20.11.')
  expect(formatTime(new Date('2026-11-13T08:57:00+01:00'), tz)).toBe('08:57')
  expect(plural(1, { one: '# Konto', other: '# Konten' })).toBe('1 Konto')
  expect(plural(4, { one: '# Konto', other: '# Konten' })).toBe('4 Konten')
  expect(formatBytes(217088)).toBe('212 KB')
  expect(formatStand(4, new Date('2026-11-13T08:57:00+01:00'), tz)).toBe('4 Konten · Stand 08:57')
})

test('uses calendar days in the requested time zone', () => {
  const now = new Date('2026-11-13T00:10:00+01:00')
  expect(formatRelativeDay(new Date('2026-11-12T23:50:00+01:00'), now, 'Europe/Berlin')).toBe('Gestern')
  expect(formatRelativeDay(new Date('2026-11-13T00:05:00+01:00'), now, 'Europe/Berlin')).toBe('Heute')
})

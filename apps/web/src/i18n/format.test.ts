import { expect, test } from 'bun:test'
import { de } from './de'
import { plural, formatTime, formatMailTime, formatDayShort, formatRelativeDay, formatListDate, formatDeadline, formatBytes, formatStand } from './format'

test('formats list dates for today and yesterday in the requested time zone', () => {
  const now = new Date('2026-11-13T10:00:00+01:00')
  expect(formatListDate(new Date('2026-11-13T08:57:00+01:00'), now, 'Europe/Berlin')).toBe('08:57')
  expect(formatListDate(new Date('2026-11-12T08:57:00+01:00'), now, 'Europe/Berlin')).toBe('Gestern')
})

test('formats date-only deadlines without a time zone shift', () => {
  expect(formatDeadline('2026-11-21', new Date('2026-01-01'))).toBe('Sa., 21.11.')
  expect(formatDeadline('2027-01-08', new Date('2026-01-01'))).toBe('Fr., 8.1.2027')
})

test('formats German dates, numbers and plurals', () => {
  const tz = 'Europe/Berlin' // i18n-exempt
  expect(formatDayShort(new Date('2026-11-20T10:00:00+01:00'), tz)).toBe('Fr., 20.11.')
  expect(formatTime(new Date('2026-11-13T08:57:00+01:00'), tz)).toBe('08:57')
  const forms = { zero: 'keine Konten', one: '# Konto', other: '# Konten' }
  expect(plural(0, forms)).toBe('keine Konten')
  expect(plural(1, forms)).toBe('1 Konto')
  expect(plural(2, forms)).toBe('2 Konten')
  expect(plural(2314, forms)).toBe('2.314 Konten')
  expect(plural(4, { one: '# Konto', other: '# Konten' })).toBe('4 Konten')
  expect(formatBytes(217088)).toBe('212 KB')
  expect(formatStand(4, new Date('2026-11-13T08:57:00+01:00'), tz)).toBe('4 Konten · Stand 08:57')
})

test('formats zero, singular and plural catalog strings and subjects', () => {
  expect([0, 1, 2].map(de.shell.accountCount)).toEqual(['kein Konto', '1 Konto', '2 Konten'])
  expect([0, 1, 2].map(de.accountCard.messages)).toEqual(['keine Mails', '1 Mail', '2 Mails'])
  expect(de.chat.stand(0, 4, '08:57')).toBe('Keine ungelesenen Mails in 4 Konten · Stand 08:57')
  expect(de.inbox.unreadStand(2314)).toBe('2.314 ungelesen')
  expect(de.inbox.done.archive('')).toBe('„Ohne Betreff“ archiviert.')
  expect(de.inbox.done.trash('x'.repeat(80))).toBe(`„${'x'.repeat(59)}…“ in den Papierkorb gelegt.`)
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


test('formats mail time for today, yesterday, this week and an older date', () => {
  const now = new Date('2026-11-13T10:00:00+01:00')
  const tz = 'Europe/Berlin'
  expect(formatMailTime(new Date('2026-11-13T08:57:00+01:00'), now, tz)).toBe('Heute, 08:57')
  expect(formatMailTime(new Date('2026-11-12T14:03:00+01:00'), now, tz)).toBe('Gestern, 14:03')
  expect(formatMailTime(new Date('2026-11-09T08:57:00+01:00'), now, tz)).toBe('Mo., 08:57')
  expect(formatMailTime(new Date('2026-11-07T08:57:00+01:00'), now, tz)).toBe('7.11., 08:57')
})

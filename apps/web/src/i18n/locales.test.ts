import { expect, test } from 'bun:test'
import { apiErrorMessage, errorCode } from '../api/unwrap'
import { formatBytes, formatDeadline, formatMailTime, formatTime, plural } from './format'
import { de } from './de'
import { en } from './en'
import { browserLocale, requestLocale } from './locales'

function catalogueShape(value: unknown): unknown {
  if (!value || typeof value !== 'object') return typeof value
  return Object.fromEntries(Object.entries(value).sort(([a], [b]) => a.localeCompare(b)).map(([key, child]) => [key, catalogueShape(child)]))
}

test('English and German have the same message keys and value types', () => {
  expect(catalogueShape(en)).toEqual(catalogueShape(de))
})

test('language negotiation follows browser priority and falls back to English', () => {
  expect(browserLocale(['fr-FR', 'de-AT', 'en-GB'])).toBe('de')
  expect(browserLocale(['en-AU', 'de-DE'])).toBe('en')
  expect(browserLocale(['ja-JP'])).toBe('en')
  expect(requestLocale(undefined)).toBe('en')
  expect(requestLocale('es-MX, DE-de;q=0.6,en-US;q=0.3')).toBe('de')
  expect(requestLocale('de;q=0, en;q=0.8')).toBe('en')
  expect(requestLocale('de;q=0.2,en')).toBe('en')
})

test('formats dates, times, numbers, and plurals in each locale', () => {
  const date = new Date('2026-11-19T17:30:00Z')
  expect(formatTime(date, 'UTC', 'de')).toBe('17:30')
  expect(formatTime(date, 'UTC', 'en')).toBe('05:30 PM')
  expect(formatMailTime(date, date, 'UTC', 'en')).toBe('Today, 05:30 PM')
  expect(formatDeadline('2026-11-20', date, 'de')).toBe('Fr., 20.11.')
  expect(formatDeadline('2026-11-20', date, 'en')).toBe('Fri, 11/20')
  expect(formatBytes(1536, 'de')).toBe('1,5\u00a0KB')
  expect(formatBytes(1536, 'en')).toBe('1.5\u00a0KB')
  expect(plural(2314, { one: '# email', other: '# emails' }, 'en')).toBe('2,314 emails')
  expect(en.shell.accountCount(1)).toBe('1 account')
})

test('known codes use the selected catalogue and unknown codes keep the supplied fallback', () => {
  const refusal = { detail: { code: 'ui_settings_conflict', message: 'Server wording' } }
  expect(apiErrorMessage(refusal, de)).toBe(de.errors.ui_settings_conflict)
  expect(apiErrorMessage(refusal, en)).toBe(en.errors.ui_settings_conflict)
  expect(errorCode(refusal)).toBe('ui_settings_conflict')
  expect(apiErrorMessage({ detail: 'calendar_feed_invalid' }, en)).toBe(en.errors.calendar_feed_invalid)
  expect(apiErrorMessage({ detail: { code: 'unrecognized', message: 'Server wording' } }, en)).toBe('Server wording')
})

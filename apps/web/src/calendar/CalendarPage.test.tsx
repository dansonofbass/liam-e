import { afterEach, expect, test } from 'bun:test'
import { cleanup, render, screen } from '@testing-library/react'
import type { SourceOut } from '../api/generated/types.gen'
import { SourceStatus } from './CalendarPage'
import { de } from '../i18n/de'

afterEach(cleanup)

test('the agenda back link has a token-sized touch target even without the desktop container', async () => {
  const css = await Bun.file(new URL('./calendar.css', import.meta.url)).text()
  const rule = css.match(/^\.le-calendar-detail > \.le-link \{ ([^{}]+) \}$/mu)
  expect(rule).toBeTruthy()
  expect(rule?.[1]).toContain('display: inline-flex')
  expect(rule?.[1]).toContain('align-items: center')
  expect(rule?.[1]).toContain('min-height: var(--control-height-lg)')
  expect(rule?.[1]).toContain('min-width: var(--control-height-lg)')
})

const source: SourceOut = { id: 'test-only', name: 'Planung', provider: 'google', timezone: 'UTC', is_active: true, capabilities: ['read'], coverage_start: '2026-11-01T00:00:00Z', coverage_end: '2026-12-01T00:00:00Z', last_success_at: '2026-11-13T10:00:00Z', stale: false, incomplete: false }
test('provider provenance and read-only status are textual', () => {
  render(<><SourceStatus source={source} /><SourceStatus source={{ ...source, id: 'test-only-ics', name: 'Verein', provider: 'ics' }} /></>)
  expect(screen.getByText('Planung')).toBeTruthy()
  expect(screen.getByText('Verein')).toBeTruthy()
  expect(screen.getByText(de.calendar.google)).toBeTruthy()
  expect(screen.getByText(de.calendar.ics)).toBeTruthy()
})
test('paused sources do not claim completeness or freshness', () => {
  render(<SourceStatus source={{ ...source, is_active: false }} from="2026-12-01" to="2026-12-08" />)
  expect(screen.getByText(de.calendar.paused)).toBeTruthy()
  expect(screen.queryByText(de.calendar.uncovered)).toBeNull()
  expect(screen.queryByText(de.calendar.empty)).toBeNull()
})
test('missing coverage and incomplete state remain distinct', () => {
  render(<SourceStatus source={{ ...source, incomplete: true, coverage_end: null }} from="2026-11-01" to="2026-11-08" />)
  expect(screen.getByText(de.calendar.incomplete)).toBeTruthy()
  expect(screen.getByText(de.calendar.uncovered)).toBeTruthy()
})

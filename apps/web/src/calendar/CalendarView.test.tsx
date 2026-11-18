// i18n-exempt: route paths and technical identifiers.
import { afterEach, expect, mock, spyOn, test } from 'bun:test'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createMemoryHistory, createRootRoute, createRoute, createRouter, RouterProvider } from '@tanstack/react-router'
import * as sdk from '../api/generated/sdk.gen'
import { CalendarView } from './CalendarView'
import { MonthView } from './MonthView'
import { de } from '../i18n/de'
import { calendarTime } from './state'

afterEach(() => { cleanup(); mock.restore() })
const source = { id: 'test-only', name: 'Planung', provider: 'google', timezone: 'UTC', is_active: true, capabilities: ['read'], coverage_start: '2026-01-01T00:00:00Z', coverage_end: '2027-01-01T00:00:00Z', last_success_at: '2026-11-18T00:00:00Z', stale: false, incomplete: false }
const event = (id: string) => ({ id, event_id: id, source_id: source.id, title: `Termin ${id}`, start_at: '2026-11-18T09:00:00Z', end_at: '2026-11-18T10:00:00Z', start_date: null, end_date: null, timezone: 'UTC' })
function setup() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } })
  const root = createRootRoute({ component: () => <QueryClientProvider client={client}><CalendarView /></QueryClientProvider> })
  const page = createRoute({ getParentRoute: () => root, path: '/calendar' })
  const router = createRouter({ routeTree: root.addChildren([page]), history: createMemoryHistory({ initialEntries: ['/calendar?view=week&date=2026-11-18'] }) })
  render(<RouterProvider router={router} />)
  return router
}
test('toolbar changes view and period in the URL', async () => {
  spyOn(sdk, 'calendarSourcesList').mockResolvedValue({ data: [source] } as never)
  spyOn(sdk, 'calendarOccurrencesList').mockResolvedValue({ data: { items: [event('a')], next_cursor: null } } as never)
  spyOn(sdk, 'calendarSourceSync').mockResolvedValue({ data: { queued: false }, response: { ok: true } } as never)
  const router = setup()
  expect(await screen.findByRole('link', { name: new RegExp(`Termin a.*${calendarTime(event('a').start_at!)}.*${calendarTime(event('a').end_at!)}`) })).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: de.calendar.month }))
  await waitFor(() => expect(router.state.location.searchStr).toContain('view=month'))
  fireEvent.click(screen.getByRole('button', { name: de.calendar.next }))
  await waitFor(() => expect(router.state.location.searchStr).toContain('date=2026-12-18'))
})
test('month overflow opens the selected day', async () => {
  const openDay = mock(() => {})
  const root = createRootRoute({ component: () => <MonthView date="2026-11-18" rows={Array.from({ length: 5 }, (_, i) => event(String(i)))} sources={[source]} onDay={openDay} onSlot={() => {}} onOpen={() => {}} /> })
  const router = createRouter({ routeTree: root, history: createMemoryHistory({ initialEntries: ['/'] }) })
  render(<RouterProvider router={router} />)
  fireEvent.click(await screen.findByRole('button', { name: /2 weitere/ }))
  expect(openDay).toHaveBeenCalledWith('2026-11-18')
})
test('incomplete coverage never claims an empty range', async () => {
  spyOn(sdk, 'calendarSourcesList').mockResolvedValue({ data: [{ ...source, incomplete: true }] } as never)
  spyOn(sdk, 'calendarOccurrencesList').mockResolvedValue({ data: { items: [], next_cursor: null } } as never)
  spyOn(sdk, 'calendarSourceSync').mockResolvedValue({ data: { queued: false }, response: { ok: true } } as never)
  setup()
  expect(await screen.findByText(de.calendar.unknown)).toBeTruthy()
  expect(screen.queryByText(de.calendar.empty)).toBeNull()
})
test('month draws all-day events as a single span across the week', async () => {
  const row = { ...event('urlaub'), start_at: null, end_at: null, start_date: '2026-11-20', end_date: '2026-11-23' }
  const root = createRootRoute({ component: () => <MonthView date="2026-11-18" rows={[row]} sources={[source]} onDay={() => {}} onSlot={() => {}} onOpen={() => {}} /> })
  const router = createRouter({ routeTree: root, history: createMemoryHistory({ initialEntries: ['/'] }) })
  render(<RouterProvider router={router} />)
  const span = await screen.findByRole('link', { name: /Termin urlaub/ })
  expect(screen.getAllByRole('link', { name: /Termin urlaub/ })).toHaveLength(1)
  expect(span.style.gridColumn).toBe('5 / span 3')
})
test('padded results outside the visible range do not hide a covered empty state', async () => {
  spyOn(sdk, 'calendarSourcesList').mockResolvedValue({ data: [source] } as never)
  spyOn(sdk, 'calendarOccurrencesList').mockResolvedValue({ data: { items: [{ ...event('outside'), start_at: '2026-11-24T09:00:00Z', end_at: '2026-11-24T10:00:00Z' }], next_cursor: null } } as never)
  spyOn(sdk, 'calendarSourceSync').mockResolvedValue({ data: { queued: false }, response: { ok: true } } as never)
  setup()
  expect(await screen.findByText(de.calendar.empty)).toBeTruthy()
})
test('manual refresh reports failure instead of silently swallowing it', async () => {
  spyOn(sdk, 'calendarSourcesList').mockResolvedValue({ data: [source] } as never)
  spyOn(sdk, 'calendarOccurrencesList').mockResolvedValue({ data: { items: [], next_cursor: null } } as never)
  spyOn(sdk, 'calendarSourceSync').mockResolvedValue({ error: { detail: 'test-only' }, response: { ok: false } } as never)
  setup()
  await screen.findByText(de.calendar.empty)
  await waitFor(() => expect((screen.getByRole('button', { name: de.calendar.refresh }) as HTMLButtonElement).disabled).toBe(false))
  fireEvent.click(screen.getByRole('button', { name: de.calendar.refresh }))
  expect(await screen.findByText((text) => text.includes(de.calendar.refreshError))).toBeTruthy()
})
test('pagination stops after ten pages and reports the cap', async () => {
  spyOn(sdk, 'calendarSourcesList').mockResolvedValue({ data: [source] } as never)
  const pages = spyOn(sdk, 'calendarOccurrencesList').mockResolvedValue({ data: { items: [], next_cursor: 'next' } } as never)
  spyOn(sdk, 'calendarSourceSync').mockResolvedValue({ data: { queued: false }, response: { ok: true } } as never)
  setup()
  expect(await screen.findByText(de.calendar.capped)).toBeTruthy()
  expect(pages).toHaveBeenCalledTimes(10)
})

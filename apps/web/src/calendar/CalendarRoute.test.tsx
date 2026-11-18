import { afterEach, expect, mock, spyOn, test } from 'bun:test'
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createMemoryHistory, createRootRoute, createRoute, createRouter, Outlet, RouterProvider } from '@tanstack/react-router'
import { CalendarDetail } from './CalendarPage'
import { ChatSessionProvider } from '../chat/session'
import * as sdk from '../api/generated/sdk.gen'
import { Route as CalendarRoute } from '../routes/_app/calendar'
import { Route as CalendarIndexRoute } from '../routes/_app/calendar/index'
import { de } from '../i18n/de'

const originalMatchMedia = window.matchMedia
afterEach(() => { cleanup(); mock.restore(); window.matchMedia = originalMatchMedia })

for (const desktop of [true, false]) {
  test(`calendar index has no detail placeholder: ${desktop}`, async () => {
    window.matchMedia = ((query: string) => ({ matches: desktop && ['(min-width: 640px)', '(min-width: 1024px)'].includes(query), addEventListener() {}, removeEventListener() {} })) as unknown as typeof window.matchMedia
    spyOn(sdk, 'calendarSourcesList').mockResolvedValue({ data: [] } as never)
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const root = createRootRoute({ component: () => <QueryClientProvider client={client}><Outlet /></QueryClientProvider> })
    const calendar = createRoute({ getParentRoute: () => root, path: '/calendar', component: CalendarRoute.options.component })
    const index = createRoute({ getParentRoute: () => calendar, path: '/', component: CalendarIndexRoute.options.component })
    const router = createRouter({ routeTree: root.addChildren([calendar.addChildren([index])]), history: createMemoryHistory({ initialEntries: ['/calendar'] }) })
    render(<RouterProvider router={router} />)
    expect(await screen.findByText(de.calendar.noSources)).toBeTruthy()
    expect(screen.getByRole('heading', { name: de.calendar.title })).toBeTruthy()
    // Without a calendar the agenda has nothing to page through or refresh; it offers the subscription.
    expect(screen.queryByRole('button', { name: de.calendar.today })).toBeNull()
    expect(screen.queryByRole('button', { name: de.calendar.refresh })).toBeNull()
    expect(screen.queryByLabelText(de.calendar.from)).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: de.calendar.subscribe }))
    expect(screen.getByRole('dialog', { name: de.calendar.subscribe })).toBeTruthy()
    expect(screen.queryByText(de.calendar.select)).toBeNull()
  })
}

test('desktop keeps the grid next to the detail route', async () => {
  window.matchMedia = ((query: string) => ({ matches: ['(min-width: 640px)', '(min-width: 1024px)'].includes(query), addEventListener() {}, removeEventListener() {} })) as unknown as typeof window.matchMedia
  const source = { id: 's', name: 'Planung', provider: 'google', is_active: true, stale: true, incomplete: true, capabilities: ['read'], timezone: 'UTC', last_success_at: null, coverage_start: null, coverage_end: null }
  const occurrence = { id: 'test-only', source_id: 's', event_id: 'e', title: 'Termin', start_date: '2026-11-18', end_date: '2026-11-19', start_at: null, end_at: null, timezone: null }
  spyOn(sdk, 'calendarSourcesList').mockResolvedValue({ data: [source] } as never)
  spyOn(sdk, 'calendarOccurrencesList').mockResolvedValue({ data: { items: [], next_cursor: null } } as never)
  spyOn(sdk, 'calendarOccurrenceGet').mockResolvedValue({ data: occurrence } as never)
  spyOn(sdk, 'calendarSourceSync').mockResolvedValue({ data: { queued: false }, response: { ok: true } } as never)
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const root = createRootRoute({ component: () => <QueryClientProvider client={client}><ChatSessionProvider><Outlet /></ChatSessionProvider></QueryClientProvider> })
  const calendar = createRoute({ getParentRoute: () => root, path: '/calendar', component: CalendarRoute.options.component })
  const detail = createRoute({ getParentRoute: () => calendar, path: '$occurrenceId', component: () => <CalendarDetail id="test-only" /> })
  const index = createRoute({ getParentRoute: () => calendar, path: '/', component: CalendarIndexRoute.options.component })
  const router = createRouter({ routeTree: root.addChildren([calendar.addChildren([detail, index])]), history: createMemoryHistory({ initialEntries: ['/calendar/test-only?view=week&date=2026-11-18'] }) })
  render(<RouterProvider router={router} />)
  expect(await screen.findByRole('heading', { name: 'Termin' })).toBeTruthy()
  expect(screen.getByRole('button', { name: de.calendar.week }).getAttribute('aria-pressed')).toBe('true')
  expect(screen.getByRole('heading', { name: 'Termin' }).closest('.le-calendar-detail')?.parentElement?.querySelector('.le-calendar-grid-page')).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: de.calendar.close }))
  await waitFor(() => expect(router.state.location.pathname).toBe('/calendar'))
  expect(router.state.location.search).toMatchObject({ view: 'week', date: '2026-11-18' })
})

test('a failed reload after an empty list keeps the agenda error and its retry instead of the empty state', async () => {
  window.matchMedia = ((query: string) => ({ matches: false, media: query, addEventListener() {}, removeEventListener() {} })) as unknown as typeof window.matchMedia
  const list = spyOn(sdk, 'calendarSourcesList').mockResolvedValue({ data: [] } as never)
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const root = createRootRoute({ component: () => <QueryClientProvider client={client}><Outlet /></QueryClientProvider> })
  const calendar = createRoute({ getParentRoute: () => root, path: '/calendar', component: CalendarRoute.options.component })
  const index = createRoute({ getParentRoute: () => calendar, path: '/', component: CalendarIndexRoute.options.component })
  const router = createRouter({ routeTree: root.addChildren([calendar.addChildren([index])]), history: createMemoryHistory({ initialEntries: ['/calendar'] }) })
  render(<RouterProvider router={router} />)
  await screen.findByText(de.calendar.noSources)
  // After subscribing, the 'calendar' queries are invalidated; this reload fails while [] stays cached.
  list.mockRejectedValue(new Error('test-only'))
  await act(async () => { await client.refetchQueries({ queryKey: ['calendar', 'sources'] }) })
  expect(await screen.findByText(de.calendar.error)).toBeTruthy()
  expect(screen.getByRole('button', { name: de.calendar.retry })).toBeTruthy()
  expect(screen.queryByText(de.calendar.noSources)).toBeNull()
})

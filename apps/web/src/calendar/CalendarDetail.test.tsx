import { afterEach, expect, mock, spyOn, test } from 'bun:test'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createMemoryHistory, createRootRoute, createRoute, createRouter, Outlet, RouterProvider } from '@tanstack/react-router'
import { ChatSessionProvider } from '../chat/session'
import * as sdk from '../api/generated/sdk.gen'
import { CalendarDetail } from './CalendarPage'

const live = { occurrence_id: 'event', source_id: 'source', title: 'Planung', start_at: '2026-11-20T09:00:00Z', end_at: '2026-11-20T10:00:00Z', revision: 'test-only', editable: true, location: 'Besprechungsraum', description: '<b>Nur Text</b>' }
afterEach(() => { cleanup(); mock.restore() })
function mount(overrides = {}) {
  spyOn(sdk, 'calendarOccurrenceLive').mockResolvedValue({ data: { ...live, ...overrides }, response: { status: 200 } } as never)
  spyOn(sdk, 'calendarSourcesList').mockResolvedValue({ data: [{ id: 'source', name: 'Arbeitskalender', is_active: true, capabilities: ['read', 'write'] }] } as never)
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const root = createRootRoute({ component: () => <QueryClientProvider client={client}><ChatSessionProvider><Outlet /></ChatSessionProvider></QueryClientProvider> })
  const detail = createRoute({ getParentRoute: () => root, path: '/calendar/$occurrenceId', component: () => <CalendarDetail id="event" /> })
  const index = createRoute({ getParentRoute: () => root, path: '/calendar', component: () => null })
  const router = createRouter({ routeTree: root.addChildren([detail, index]), history: createMemoryHistory({ initialEntries: ['/calendar/event?view=week&date=2026-11-18'] }) })
  render(<RouterProvider router={router} />)
  return router
}
for (const [reason, text] of [['series', 'Serientermine'], ['guests', 'Gästen']]) test(`read-only ${reason}`, async () => {
  mount({ editable: false, reason, html_link: 'https://calendar.google.com/' })
  await screen.findByText('Nur lesbar')
  expect(screen.getByText(new RegExp(text!))).toBeTruthy()
  expect(screen.queryByRole('button', { name: 'Löschen' })).toBeNull()
  expect(screen.getByRole('link', { name: 'In Google Kalender öffnen' })).toBeTruthy()
})
test('delete binds live revision and retains search on done', async () => {
  const remove = spyOn(sdk, 'calendarEventDelete').mockResolvedValue({ data: { status: 'done' }, response: { status: 200 } } as never)
  const router = mount()
  fireEvent.click(await screen.findByRole('button', { name: 'Löschen' }))
  const dialog = screen.getByRole('dialog')
  expect(within(dialog).getByText(/nicht garantiert rückgängig/)).toBeTruthy()
  fireEvent.click(within(dialog).getByRole('button', { name: 'Löschen' }))
  await waitFor(() => expect(remove).toHaveBeenCalledTimes(1))
  expect(remove.mock.calls[0]?.[0]?.body).toMatchObject({ expected_revision: 'test-only' })
  await waitFor(() => expect(router.state.location.pathname).toBe('/calendar'))
  expect(router.state.location.search).toMatchObject({ view: 'week', date: '2026-11-18' })
})
test('changed revision displays current values without deletion success', async () => {
  spyOn(sdk, 'calendarEventDelete').mockResolvedValue({ error: { detail: { status: 'not_applied', error_code: 'calendar_event_changed', current: { ...live, title: 'Neue Planung' } } }, response: { status: 409 } } as never)
  const router = mount()
  fireEvent.click(await screen.findByRole('button', { name: 'Löschen' }))
  fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Löschen' }))
  expect(await screen.findByText('Neue Planung')).toBeTruthy()
  expect(router.state.location.pathname).toBe('/calendar/event')
  expect(within(screen.getByRole('dialog')).queryByRole('button', { name: 'Löschen' })).toBeNull()
})

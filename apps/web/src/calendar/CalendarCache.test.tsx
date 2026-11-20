import { afterEach, expect, mock, spyOn, test } from 'bun:test'
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createMemoryHistory, createRootRoute, createRoute, createRouter, Outlet, RouterProvider } from '@tanstack/react-router'
import * as sdk from '../api/generated/sdk.gen'
import { de } from '../i18n/de'
import { CalendarView } from './CalendarView'
import { addDays, todayLocal } from './state'

afterEach(() => { cleanup(); mock.restore() })

function setup(view: 'week' | 'list' = 'week') {
  const day = todayLocal()
  const source = { id: 'test-only', name: 'Planung', provider: 'google', is_active: true, capabilities: ['read'],
    timezone: 'UTC', last_success_at: new Date().toISOString(), coverage_start: day, coverage_end: addDays(day, 14),
    revision: 1, data_revision: 1, stale: false, incomplete: false }
  const page = (title: string) => ({ data: { items: [{ id: 'event', source_id: source.id, title, start_date: day, end_date: addDays(day, 1) }], next_cursor: null } })
  const sources = spyOn(sdk, 'calendarSourcesList').mockResolvedValue({ data: [source] } as never)
  const index = spyOn(sdk, 'calendarOccurrencesList').mockResolvedValue(page('Erster Stand') as never)
  const due = spyOn(sdk, 'calendarSourceSync').mockResolvedValue({ data: { queued: true }, response: { ok: true } } as never)
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: 60_000 } } })
  const root = createRootRoute({ component: () => <QueryClientProvider client={client}><Outlet /></QueryClientProvider> })
  const calendar = createRoute({ getParentRoute: () => root, path: '/calendar', component: CalendarView })
  const chat = createRoute({ getParentRoute: () => root, path: '/chat/$conversationId', component: () => <p>Chat</p> })
  const router = createRouter({ routeTree: root.addChildren([calendar, chat]), history: createMemoryHistory({ initialEntries: ['/chat/test-only'] }) })
  render(<RouterProvider router={router} />)
  const open = (date = day) => act(async () => { await router.navigate({ to: '/calendar', search: { view, date } }) })
  const leave = () => act(async () => { await router.navigate({ to: '/chat/$conversationId', params: { conversationId: 'test-only' } }) })
  return { client, open, leave, sources, due, index, day, source, page }
}

test('returning through chat and revisiting a week reuse the visible index within its own freshness interval', async () => {
  const clock = Date.now.bind(Date)
  let elapsed = 0
  spyOn(Date, 'now').mockImplementation(() => clock() + elapsed)
  const { open, leave, sources, due, index, day } = setup()
  await open()
  await screen.findByRole('link', { name: /Erster Stand/ })
  expect([sources.mock.calls.length, index.mock.calls.length, due.mock.calls.length]).toEqual([1, 1, 1])

  await leave()
  elapsed = 10_000
  await open()
  expect(screen.getByRole('link', { name: /Erster Stand/ })).toBeTruthy()
  expect([sources.mock.calls.length, index.mock.calls.length, due.mock.calls.length]).toEqual([1, 1, 1])

  await leave()
  elapsed = 75_000
  await open()
  expect(screen.getByRole('link', { name: /Erster Stand/ })).toBeTruthy()
  expect([sources.mock.calls.length, index.mock.calls.length, due.mock.calls.length]).toEqual([2, 1, 1])
  await open(addDays(day, 7))
  expect(screen.queryByRole('link', { name: /Erster Stand/ })).toBeNull()
  await open()
  expect(screen.getByRole('link', { name: /Erster Stand/ })).toBeTruthy()
  expect(index).toHaveBeenCalledTimes(2)

  await leave()
  elapsed = 321_000
  index.mockRejectedValueOnce(new Error('test-only'))
  await open()
  await screen.findByText(de.calendar.cachedError)
  expect(screen.getByRole('link', { name: /Erster Stand/ })).toBeTruthy()
  expect([sources.mock.calls.length, index.mock.calls.length, due.mock.calls.length]).toEqual([3, 3, 2])
})

for (const view of ['week', 'list'] as const) {
  test(`${view} updates its rows once the worker advances the index, retains them on transient failure and retries`, async () => {
    const { open, sources, due, index, client, source, page } = setup(view)
    await open()
    await screen.findByRole('link', { name: /Erster Stand/ })
    // Enqueueing a sync has no bearing on the contents of a successful index read.
    expect(due).toHaveBeenCalledTimes(1)
    expect(index).toHaveBeenCalledTimes(1)
    const refresh = Promise.withResolvers<never>()
    index.mockReturnValueOnce(refresh.promise)
    sources.mockResolvedValue({ data: [{ ...source, data_revision: 2 }] } as never)
    await act(() => client.refetchQueries({ queryKey: ['calendar', 'sources'] }))
    await screen.findByText(de.calendar.updating)
    expect(screen.getByRole('link', { name: /Erster Stand/ })).toBeTruthy()
    await act(async () => { refresh.reject(new Error('test-only')) })
    await screen.findByText(de.calendar.cachedError)
    expect(screen.getByRole('link', { name: /Erster Stand/ })).toBeTruthy()
    expect(screen.queryByText(de.calendar.empty)).toBeNull()
    index.mockResolvedValue(page('Neuer Stand') as never)
    fireEvent.click(screen.getByRole('button', { name: de.calendar.retry }))
    await screen.findByRole('link', { name: /Neuer Stand/ })
    expect(index).toHaveBeenCalledTimes(3)
    expect(screen.queryByRole('link', { name: /Erster Stand/ })).toBeNull()

    // A confirmed calendar write invalidates the group even inside the five-minute interval.
    index.mockResolvedValue({ data: { items: [], next_cursor: null } } as never)
    await act(() => client.invalidateQueries({ queryKey: ['calendar'] }))
    await waitFor(() => expect(screen.queryByRole('link', { name: /Neuer Stand/ })).toBeNull())
    expect(index).toHaveBeenCalledTimes(4)
    expect(due).toHaveBeenCalledTimes(1)
  })

  test(`${view} hides old rows after a definitive access refusal`, async () => {
    const { open, client, index } = setup(view)
    await open()
    await screen.findByRole('link', { name: /Erster Stand/ })
    index.mockResolvedValue({ response: { status: 404 }, error: { detail: 'source_not_found' } } as never)
    await act(() => client.invalidateQueries({ queryKey: ['calendar'] }))
    await screen.findByText(de.calendar.error)
    expect(screen.queryByRole('link', { name: /Erster Stand/ })).toBeNull()
    expect(screen.queryByText(de.calendar.empty)).toBeNull()
    index.mockRejectedValue(new Error('test-only network error'))
    await act(() => client.invalidateQueries({ queryKey: ['calendar'] }))
    expect(screen.queryByRole('link', { name: /Erster Stand/ })).toBeNull()
  })
}

test('an index read that finishes after a new snapshot cannot replace its rows', async () => {
  const { open, client, sources, index, source, page } = setup()
  const old = Promise.withResolvers<never>()
  index.mockReturnValueOnce(old.promise)
  await open()
  await waitFor(() => expect(index).toHaveBeenCalledTimes(1))
  sources.mockResolvedValue({ data: [{ ...source, data_revision: 2 }] } as never)
  index.mockResolvedValue(page('Neuer Stand') as never)
  await act(() => client.refetchQueries({ queryKey: ['calendar', 'sources'] }))
  await screen.findByRole('link', { name: /Neuer Stand/ })
  await act(async () => { old.resolve(page('Veralteter Stand') as never) })
  expect(screen.queryByRole('link', { name: /Veralteter Stand/ })).toBeNull()
  expect(screen.getByRole('link', { name: /Neuer Stand/ })).toBeTruthy()
})

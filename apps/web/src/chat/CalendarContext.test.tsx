import { afterEach, expect, mock, spyOn, test } from 'bun:test'
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createMemoryHistory, createRootRoute, createRoute, createRouter, Outlet, RouterProvider } from '@tanstack/react-router'
import * as sdk from '../api/generated/sdk.gen'
import type { SourceOut } from '../api/generated/types.gen'
import { AskAboutCalendar, CalendarReference } from './CalendarContext'
import { ChatSessionProvider, useChatSession } from './session'
import { de } from '../i18n/de'

afterEach(() => { cleanup(); mock.restore() })
const source: SourceOut = { id: 'test-only-a', name: 'Verein', provider: 'ics', timezone: 'UTC', is_active: true, capabilities: ['read'], coverage_start: null, coverage_end: null, last_success_at: null, stale: true, incomplete: true }
function setup(sources = [source], sourceId = source.id, loadSources?: () => Promise<never>) {
  const list = spyOn(sdk, 'calendarSourcesList').mockResolvedValue({ data: sources } as never)
  if (loadSources) list.mockImplementation(loadSources)
  const detail = spyOn(sdk, 'calendarOccurrenceGet').mockResolvedValue({ data: { id: 'test-only-occurrence', source_id: source.id, event_id: 'test-only', title: 'Planung', start_date: '2026-11-13', end_date: '2026-11-14', start_at: null, end_at: null, timezone: null } } as never)
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const root = createRootRoute({ component: () => <QueryClientProvider client={client}><CalendarReference occurrenceId="test-only-occurrence" sourceId={sourceId} /></QueryClientProvider> })
  const page = createRoute({ getParentRoute: () => root, path: '/' })
  const router = createRouter({ routeTree: root.addChildren([page]), history: createMemoryHistory({ initialEntries: ['/'] }) })
  render(<RouterProvider router={router} />)
  return { client, detail, list }
}
test('asking from an instance opens a fresh chat with an explicit source and structured identity', async () => {
  const client = new QueryClient()
  function Probe() { return <p>{JSON.stringify(useChatSession().calendarScopes.new)}</p> }
  const root = createRootRoute({ component: () => <QueryClientProvider client={client}><ChatSessionProvider><Outlet /></ChatSessionProvider></QueryClientProvider> })
  const detail = createRoute({ getParentRoute: () => root, path: '/calendar/$occurrenceId', component: () => <AskAboutCalendar occurrenceId="test-only-occurrence" sourceId="test-only-source" /> })
  const start = createRoute({ getParentRoute: () => root, path: '/', component: Probe })
  const router = createRouter({ routeTree: root.addChildren([detail, start]), history: createMemoryHistory({ initialEntries: ['/calendar/test-only-occurrence'] }) })
  render(<RouterProvider router={router} />)
  fireEvent.click(await screen.findByRole('button', { name: de.calendar.ask }))
  await waitFor(() => expect(router.state.location.pathname).toBe('/'))
  expect(router.state.location.search).toEqual({ calendarAbout: 'test-only-occurrence' })
  expect(screen.getByText('["test-only-source"]')).toBeTruthy()
})

test('calendar evidence waits for sources before requesting the instance', async () => {
  let resolve!: (value: never) => void
  const pending = new Promise<never>(done => { resolve = done })
  const { detail } = setup([source], source.id, () => pending)
  expect(await screen.findByText(de.calendar.referenceLoading)).toBeTruthy()
  expect(screen.queryByText(de.calendar.missing)).toBeNull()
  expect(detail).not.toHaveBeenCalled()
  await act(async () => { resolve({ data: [source] } as never) })
  expect(await screen.findByRole('link', { name: 'Planung' })).toBeTruthy()
})

test('a failed sources request offers retry without reading the instance', async () => {
  const { detail, list } = setup([source], source.id, async () => { throw new Error('test-only') })
  expect(await screen.findByText(de.calendar.error)).toBeTruthy()
  expect(screen.queryByText(de.calendar.missing)).toBeNull()
  expect(detail).not.toHaveBeenCalled()
  list.mockResolvedValue({ data: [source] } as never)
  fireEvent.click(screen.getByRole('button', { name: de.calendar.retry }))
  expect(await screen.findByRole('link', { name: 'Planung' })).toBeTruthy()
  expect(list).toHaveBeenCalledTimes(2)
})

test('a failed instance request offers retry', async () => {
  const { detail } = setup()
  detail.mockRejectedValueOnce(new Error('test-only'))
  expect(await screen.findByText(de.calendar.error)).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: de.calendar.retry }))
  expect(await screen.findByRole('link', { name: 'Planung' })).toBeTruthy()
})

test('an instance the index no longer has reads as unavailable without retry', async () => {
  const { detail } = setup()
  detail.mockRejectedValueOnce({ detail: 'occurrence_not_found' })
  expect(await screen.findByText(de.calendar.missing)).toBeTruthy()
  expect(screen.queryByRole('button', { name: de.calendar.retry })).toBeNull()
  expect(detail).toHaveBeenCalledTimes(1)
})

test('pausing the source after a failed instance request shows it as unavailable, not a dead retry', async () => {
  const { client, detail } = setup()
  detail.mockRejectedValueOnce(new Error('test-only'))
  expect(await screen.findByText(de.calendar.error)).toBeTruthy()
  act(() => client.setQueryData(['calendar', 'sources'], [{ ...source, is_active: false }]))
  expect(await screen.findByText(de.calendar.missing)).toBeTruthy()
  expect(screen.queryByRole('button', { name: de.calendar.retry })).toBeNull()
})

test('calendar evidence links the exact instance with source and incomplete status', async () => {
  setup()
  expect((await screen.findByRole('link', { name: 'Planung' })).getAttribute('href')).toBe('/calendar/test-only-occurrence')
  expect(screen.getByText('Verein')).toBeTruthy()
  expect(screen.getByText(de.calendar.ics)).toBeTruthy()
  expect(screen.getByText(de.calendar.incomplete)).toBeTruthy()
})
for (const sources of [[], [{ ...source, is_active: false }]]) {
  test('removed or paused evidence cannot read the old instance', async () => {
    const { detail } = setup(sources)
    await screen.findByText(de.calendar.missing)
    expect(detail).not.toHaveBeenCalled()
    expect(screen.queryByText('Planung')).toBeNull()
  })
}
test('a source mismatch cannot render a cached title', async () => {
  setup([{ ...source, id: 'test-only-b' }], 'test-only-b')
  await screen.findByText(de.calendar.missing)
  expect(screen.queryByText('Planung')).toBeNull()
})
test('revoking the source removes previously rendered evidence', async () => {
  const { client } = setup()
  await screen.findByRole('link', { name: 'Planung' })
  act(() => client.setQueryData(['calendar', 'sources'], [{ ...source, is_active: false }]))
  await waitFor(() => expect(screen.queryByText('Planung')).toBeNull())
  expect(screen.getByText(de.calendar.missing)).toBeTruthy()
})

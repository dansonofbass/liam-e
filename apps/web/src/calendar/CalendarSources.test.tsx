import { afterEach, expect, mock, spyOn, test } from 'bun:test'
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createMemoryHistory, createRootRoute, createRoute, createRouter, RouterProvider } from '@tanstack/react-router'
import * as sdk from '../api/generated/sdk.gen'
import type { SourceOut } from '../api/generated/types.gen'
import { CalendarSources } from './CalendarSources'
import { de } from '../i18n/de'

afterEach(() => { cleanup(); mock.restore() })
const source = { id: 'test-only', name: 'Verein', provider: 'ics', timezone: 'UTC', is_active: true, revision: 2, capabilities: ['read'], coverage_start: null, coverage_end: null, last_success_at: null, stale: true, incomplete: true }
function setup(sources: SourceOut[] = [source]) {
  const list = spyOn(sdk, 'calendarSourcesList').mockResolvedValue({ data: sources } as never)
  const query = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } })
  const invalidated = spyOn(query, 'invalidateQueries')
  const root = createRootRoute({ component: () => <QueryClientProvider client={query}><CalendarSources /></QueryClientProvider> })
  const page = createRoute({ getParentRoute: () => root, path: '/accounts' })
  const router = createRouter({ routeTree: root.addChildren([page]), history: createMemoryHistory({ initialEntries: ['/accounts'] }) })
  render(<RouterProvider router={router} />)
  return { invalidated, query, list }
}

test('replacement binds a fresh proof to the source revision and invalidates calendar queries', async () => {
  const { invalidated } = setup()
  spyOn(sdk, 'calendarFeedValidate').mockResolvedValue({ data: { validation_id: 'test-only-proof', name: 'Verein', coverage_start: '2026-01-01T00:00:00Z', coverage_end: '2026-02-01T00:00:00Z', occurrence_count: 0, format_issues: [], expires_at: '2026-01-01T00:10:00Z' } } as never)
  const subscribe = spyOn(sdk, 'calendarFeedSubscribe').mockResolvedValue({ data: source } as never)
  spyOn(sdk, 'calendarFeedValidationDiscard').mockResolvedValue({} as never)
  fireEvent.click(await screen.findByRole('button', { name: de.calendar.replaceAddress }))
  const dialog = screen.getByRole('dialog', { name: de.calendar.replaceAddress })
  expect((within(dialog).getByLabelText(de.calendar.feedAddress) as HTMLInputElement).value).toBe('')
  fireEvent.change(within(dialog).getByLabelText(de.calendar.feedAddress), { target: { value: 'https://calendar.example/test-only-new' } })
  fireEvent.click(within(dialog).getByRole('button', { name: de.calendar.feedCheck }))
  await within(dialog).findByText(de.calendar.feedCount(0))
  fireEvent.click(within(dialog).getByRole('button', { name: de.calendar.replaceAddress }))
  await waitFor(() => expect(invalidated).toHaveBeenCalledWith({ queryKey: ['calendar'] }))
  expect(subscribe.mock.calls[0]?.[0]?.body).toMatchObject({ source_id: source.id, expected_revision: 2 })
  expect(screen.queryByRole('dialog')).toBeNull()
})

test('refresh, pause and confirmed removal use the existing source actions', async () => {
  setup()
  const refresh = spyOn(sdk, 'calendarSourceSync').mockResolvedValue({ data: { queued: false }, response: { ok: true } } as never)
  const pause = spyOn(sdk, 'calendarSourceUpdate').mockResolvedValue({ data: { ...source, is_active: false }, response: { ok: true } } as never)
  const remove = spyOn(sdk, 'calendarSourceDelete').mockResolvedValue({ response: { ok: true } } as never)
  fireEvent.click(await screen.findByRole('button', { name: de.calendar.refresh }))
  expect(await screen.findByText(de.calendar.feedNotQueued)).toBeTruthy()
  expect(refresh).toHaveBeenCalledTimes(1)
  fireEvent.click(screen.getByRole('button', { name: de.calendar.pause }))
  await waitFor(() => expect(pause).toHaveBeenCalledWith({ path: { source_id: source.id }, body: { is_active: false } }))
  await waitFor(() => expect((screen.getByRole('button', { name: de.calendar.remove }) as HTMLButtonElement).disabled).toBe(false))
  fireEvent.click(screen.getByRole('button', { name: de.calendar.remove }))
  const dialog = screen.getByRole('dialog', { name: de.calendar.removeTitle })
  expect(within(dialog).getByText(de.calendar.removeNote)).toBeTruthy()
  expect(remove).not.toHaveBeenCalled()
  fireEvent.click(within(dialog).getByRole('button', { name: de.calendar.remove }))
  await waitFor(() => expect(remove).toHaveBeenCalledTimes(1))
})

test('without a source the section says how to subscribe and offers it', async () => {
  setup([])
  expect(await screen.findByText(de.calendar.noSources)).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: de.calendar.subscribe }))
  expect(screen.getByRole('dialog', { name: de.calendar.subscribe })).toBeTruthy()
})

test('a failed reload after an empty list shows the error, not the claim that no calendar exists', async () => {
  const { query, list } = setup([])
  await screen.findByText(de.calendar.noSources)
  list.mockRejectedValue(new Error('test-only'))
  await act(async () => { await query.refetchQueries({ queryKey: ['calendar', 'sources'] }) })
  expect(await screen.findByText(de.calendar.error)).toBeTruthy()
  expect(screen.queryByText(de.calendar.noSources)).toBeNull()
})

test.each([
  ['reconnect_required', de.calendar.googleReconnectError],
  ['calendar_unavailable', de.calendar.googleUnavailableError],
  ['provider_unavailable', de.calendar.googleProviderError],
])('Google source error %s names the next step without offering an address replacement', async (last_error, message) => {
  setup([{ ...source, provider: 'google', last_error }])
  expect(await screen.findByText(message!)).toBeTruthy()
  expect(screen.getByText(de.calendar.google)).toBeTruthy()
  expect(screen.queryByRole('button', { name: de.calendar.replaceAddress })).toBeNull()
  expect(screen.getByRole('button', { name: de.calendar.refresh })).toBeTruthy()
})

test.each(['pause', 'remove'] as const)('confirmed %s still restricts the source cache when the next read fails', async action => {
  const { query, list } = setup()
  const button = await screen.findByRole('button', { name: de.calendar[action] })
  list.mockRejectedValue(new Error('test-only'))
  spyOn(sdk, 'calendarSourceUpdate').mockResolvedValue({ data: { ...source, is_active: false, revision: 3 }, response: { ok: true } } as never)
  spyOn(sdk, 'calendarSourceDelete').mockResolvedValue({ response: { ok: true } } as never)
  fireEvent.click(button)
  if (action === 'remove') fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: de.calendar.remove }))
  await screen.findByText(de.calendar.error)
  const cached = query.getQueryData<SourceOut[]>(['calendar', 'sources'])
  expect(cached?.filter(s => s.is_active)).toEqual([])
})

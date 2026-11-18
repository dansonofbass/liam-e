import { afterEach, expect, mock, spyOn, test } from 'bun:test'
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createMemoryHistory, createRootRoute, createRoute, createRouter, RouterProvider } from '@tanstack/react-router'
import type { SourceOut } from '../api/generated/types.gen'
import * as sdk from '../api/generated/sdk.gen'
import { client as apiClient } from '../api/generated/client.gen'
import { CalendarAgenda, SourceStatus } from './CalendarPage'
import { addDays, todayLocal } from './state'
import { de } from '../i18n/de'

afterEach(() => { cleanup(); mock.restore() })

test('the date range has its own two-column row instead of squeezing beside the buttons', async () => {
  const css = await Bun.file(new URL('./calendar.css', import.meta.url)).text()
  const rule = css.match(/^\.le-calendar-range \{ ([^{}]+) \}$/mu)
  expect(rule?.[1]).toContain('grid-template-columns: repeat(2, minmax(0, 1fr))')
  expect(css).not.toMatch(/\.le-calendar-controls \.le-field/u)
})

// DESIGN.md §7.2: the 44 px touch target applies with a coarse pointer; with a mouse the links keep their text height.
const coarseBlock = (css: string) => css.match(/@media \(pointer: coarse\) \{([\s\S]*?)\n\}/u)?.[1] ?? ''
for (const [name, selector, pattern] of [
  ['the agenda link in calendar management outside the calendar page', '.le-calendar-back', /^\.le-calendar-back \{ ([^{}]+) \}$/mu],
  ['the agenda back link even without the desktop container', '.le-calendar-detail > .le-link', /^\.le-calendar-detail > \.le-link \{ ([^{}]+) \}$/mu],
] as const) {
  test(`${name} has a token-sized touch target on coarse pointers`, async () => {
    const css = await Bun.file(new URL('./calendar.css', import.meta.url)).text()
    const rule = css.match(pattern)
    for (const part of ['display: inline-flex', 'align-items: center']) expect(rule?.[1]).toContain(part)
    expect(rule?.[1]).not.toContain('--control-height-lg')
    const coarse = coarseBlock(css)
    for (const property of ['min-height', 'min-width']) expect(coarse).toMatch(new RegExp(`${selector.replace(/[.*+?^${}()|[\]\\]/gu, '\\$&')}[^{]*\\{ ${property}: var\\(--control-height-lg\\); \\}`, 'u'))
  })
}

const source: SourceOut = { id: 'test-only', name: 'Planung', provider: 'google', timezone: 'UTC', is_active: true, capabilities: ['read'], coverage_start: '2026-11-01T00:00:00Z', coverage_end: '2026-12-01T00:00:00Z', last_success_at: '2026-11-13T10:00:00Z', stale: false, incomplete: false }
test('pausing a source hides its cached agenda rows without waiting for a refetch', async () => {
  const sources = [source, { ...source, id: 'other', name: 'Verein' }].map(item => ({ ...item, last_success_at: new Date().toISOString() }))
  spyOn(sdk, 'calendarSourcesList').mockResolvedValue({ data: sources } as never)
  const occurrences = spyOn(sdk, 'calendarOccurrencesList').mockResolvedValue({ data: { items: sources.map(item => ({ id: `occurrence-${item.id}`, source_id: item.id, title: `Termin ${item.name}`, start_date: todayLocal(), end_date: addDays(todayLocal(), 1) })), next_cursor: null } } as never)
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } })
  const root = createRootRoute({ component: () => <QueryClientProvider client={client}><CalendarAgenda /></QueryClientProvider> })
  const page = createRoute({ getParentRoute: () => root, path: '/calendar' })
  const router = createRouter({ routeTree: root.addChildren([page]), history: createMemoryHistory({ initialEntries: ['/calendar'] }) })
  render(<RouterProvider router={router} />)
  expect(await screen.findByRole('link', { name: /Termin Planung/ })).toBeTruthy()
  expect(screen.getByRole('link', { name: /Termin Verein/ })).toBeTruthy()
  act(() => { client.setQueryData(['calendar', 'sources'], sources.map(item => item.id === source.id ? { ...item, is_active: false } : item)) })
  await waitFor(() => expect(screen.queryByRole('link', { name: /Termin Planung/ })).toBeNull())
  expect(screen.getByRole('link', { name: /Termin Verein/ })).toBeTruthy()
  expect(screen.getByText(de.calendar.paused)).toBeTruthy()
  expect(occurrences).toHaveBeenCalledTimes(1)
})

function coveredSource(): SourceOut {
  return { ...source, last_success_at: new Date().toISOString(), coverage_start: `${addDays(todayLocal(), -2)}T00:00:00Z`, coverage_end: `${addDays(todayLocal(), 9)}T00:00:00Z` }
}

function renderAgenda(sources = [coveredSource()]) {
  const list = spyOn(sdk, 'calendarSourcesList').mockResolvedValue({ data: sources } as never)
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } })
  const root = createRootRoute({ component: () => <QueryClientProvider client={client}><CalendarAgenda /></QueryClientProvider> })
  const page = createRoute({ getParentRoute: () => root, path: '/calendar' })
  const router = createRouter({ routeTree: root.addChildren([page]), history: createMemoryHistory({ initialEntries: ['/calendar'] }) })
  render(<RouterProvider router={router} />)
  return { client, list }
}

test('an empty first page with a cursor does not claim there are no events', async () => {
  const occurrences = spyOn(sdk, 'calendarOccurrencesList').mockResolvedValue({ data: { items: [], next_cursor: 'test-only-next' } } as never)
  renderAgenda()
  expect(await screen.findByText(de.calendar.unknown)).toBeTruthy()
  expect(screen.queryByText(de.calendar.empty)).toBeNull()
  expect(screen.getByRole('button', { name: de.calendar.more })).toBeTruthy()
  expect(occurrences).toHaveBeenCalledTimes(1)
})

test('an agenda query error offers retry instead of claiming there are no events', async () => {
  const occurrences = spyOn(sdk, 'calendarOccurrencesList').mockRejectedValue(new Error('test-only'))
  renderAgenda()
  expect(await screen.findByText(de.calendar.error)).toBeTruthy()
  expect(screen.queryByText(de.calendar.empty)).toBeNull()
  occurrences.mockResolvedValue({ data: { items: [], next_cursor: null } } as never)
  fireEvent.click(screen.getByRole('button', { name: de.calendar.retry }))
  expect(await screen.findByText(de.calendar.empty)).toBeTruthy()
  expect(occurrences).toHaveBeenCalledTimes(2)
})

test('a fully covered empty window without another page shows no events', async () => {
  spyOn(sdk, 'calendarOccurrencesList').mockResolvedValue({ data: { items: [], next_cursor: null } } as never)
  renderAgenda()
  expect(await screen.findByText(de.calendar.empty)).toBeTruthy()
  expect(screen.queryByText(de.calendar.unknown)).toBeNull()
  expect(screen.queryByRole('button', { name: de.calendar.more })).toBeNull()
})

test('mount requests one due-only sync per active Google source, including fresh sources, but never paused ones', async () => {
  const fresh = coveredSource()
  const old = { ...fresh, last_success_at: new Date(Date.now() - 48 * 60 * 60 * 1000).toISOString() }
  const sources = [old, { ...old, id: 'other-old' }, { ...old, id: 'paused', is_active: false }, { ...fresh, id: 'fresh' }]
  spyOn(sdk, 'calendarOccurrencesList').mockResolvedValue({ data: { items: [], next_cursor: null } } as never)
  const config = apiClient.getConfig()
  const requests: Request[] = []
  apiClient.setConfig({ baseUrl: 'https://calendar.example', fetch: (async (request: Request) => {
    requests.push(request)
    return new Response(JSON.stringify({ queued: true }), { headers: { 'Content-Type': 'application/json' } })
  }) as typeof fetch })
  try {
    const { client, list } = renderAgenda(sources)
    await waitFor(() => expect(list).toHaveBeenCalledTimes(2))
    expect(screen.queryByText(de.calendar.queued)).toBeNull()
    await act(async () => { await client.refetchQueries({ queryKey: ['calendar', 'sources'] }) })
    expect(list).toHaveBeenCalledTimes(3)
    expect(requests.map(request => [request.method, new URL(request.url).pathname])).toEqual([
      ['POST', `/api/v1/calendar/sources/${old.id}/sync`],
      ['POST', '/api/v1/calendar/sources/other-old/sync'],
      ['POST', '/api/v1/calendar/sources/fresh/sync'],
    ])
    expect(requests.every(request => new URL(request.url).searchParams.get('due_only') === 'true')).toBe(true)
  } finally { apiClient.setConfig({ ...config, fetch: config.fetch }) }
})

test.each(['not-due', 'queued', 'error'])('automatic catch-up stays silent (%s); only manual refresh shows feedback', async outcome => {
  spyOn(sdk, 'calendarOccurrencesList').mockResolvedValue({ data: { items: [], next_cursor: null } } as never)
  const sync = spyOn(sdk, 'calendarSourceSync').mockResolvedValue(outcome === 'error'
    ? { error: { detail: 'test-only' }, response: { ok: false } } as never
    : { data: { queued: outcome === 'queued' }, response: { ok: true } } as never)
  const { list } = renderAgenda([{ ...coveredSource(), provider: 'ics' }])
  await waitFor(() => expect(list).toHaveBeenCalledTimes(2))
  expect(sync).toHaveBeenCalledWith({ path: { source_id: source.id }, query: { due_only: true } })
  for (const message of [de.calendar.feedNotQueued, de.calendar.queued, de.calendar.refreshError]) {
    expect(screen.queryByText(message)).toBeNull()
  }
  fireEvent.click(screen.getByRole('button', { name: de.calendar.refresh }))
  expect(await screen.findByText(outcome === 'error' ? de.calendar.refreshError : outcome === 'queued' ? de.calendar.queued : de.calendar.feedNotQueued)).toBeTruthy()
  expect(sync).toHaveBeenLastCalledWith({ path: { source_id: source.id }, query: { due_only: false } })
})

test('provider provenance and read-only status are textual', () => {
  render(<><SourceStatus source={source} /><SourceStatus source={{ ...source, id: 'test-only-ics', name: 'Verein', provider: 'ics' }} /></>)
  expect(screen.getByText('Planung')).toBeTruthy()
  expect(screen.getByText('Verein')).toBeTruthy()
  expect(screen.getByText(de.calendar.google)).toBeTruthy()
  expect(screen.getByText(de.calendar.ics)).toBeTruthy()
})
test('a writable Google source does not claim to be read-only', () => {
  render(<SourceStatus source={{ ...source, capabilities: ['read', 'write'] }} />)
  expect(screen.getByText(de.calendar.googleWritable)).toBeTruthy()
  expect(screen.queryByText(/Nur lesen/)).toBeNull()
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

// i18n-exempt: synthetic API data and paths.
import { afterEach, expect, test } from 'bun:test'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createMemoryHistory, createRootRoute, createRoute, createRouter, Outlet, RouterProvider } from '@tanstack/react-router'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { client as api } from '../api/generated/client.gen'
import { TaskDetail } from './TaskDetail'

const originalFetch = globalThis.fetch, originalConfig = api.getConfig()
afterEach(() => { cleanup(); globalThis.fetch = originalFetch; api.setConfig(originalConfig) })

function setup(conflict = false) {
  api.setConfig({ baseUrl: 'https://api.example.test' })
  const calls: { method: string; path: string; body?: unknown }[] = []
  let series = { id: 'series', title: 'Aufgabe', description: '', source_message_id: null, source_account_id: null, version: 7, archived: false, complete: true, schedule: { id: 'rev', version: 1, start_local: '2027-01-01', timezone: 'UTC', rrule: null } }
  let occurrence = { id: 'occ', series_id: 'series', revision_id: 'rev', occurrence_key: '2027-01-01', due_local: '2027-01-01', due_at: null, status: 'open', version: 4 }
  let deleted = false
  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const req = input instanceof Request ? input : new Request(input, init), url = new URL(req.url)
    const body = req.method === 'GET' ? undefined : await req.clone().json()
    calls.push({ method: req.method, path: url.pathname, body })
    if (url.pathname.endsWith('/reconcile')) return Response.json({ revision_id: 'rev', cursor: 'cursor', target: '2027-01-01T00:00:00Z', complete: true })
    if (req.method === 'POST' && url.pathname.endsWith('/skip')) {
      if (conflict) { occurrence = { ...occurrence, version: 5, status: 'completed' }; return Response.json({ detail: { code: 'task_version_conflict' } }, { status: 409 }) }
      occurrence = { ...occurrence, version: 5, status: 'skipped' }; return Response.json(occurrence)
    }
    if (req.method === 'POST' && url.pathname.endsWith('/reopen')) { occurrence = { ...occurrence, version: 6, status: 'open' }; return Response.json(occurrence) }
    if (req.method === 'POST' && url.pathname.endsWith('/archive')) { series = { ...series, archived: true, version: 8 }; return Response.json(series) }
    if (req.method === 'DELETE') { deleted = true; return new Response(null, { status: 204 }) }
    if (deleted) return Response.json({ detail: { code: 'task_not_found' } }, { status: 404 })
    return Response.json({ window: { due_from: '2027-01-01', due_to: '2027-12-31' }, series, occurrences: { items: [occurrence], next_cursor: null } })
  }) as typeof fetch
  const query = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const root = createRootRoute({ component: () => <QueryClientProvider client={query}><Outlet /></QueryClientProvider> })
  const tasks = createRoute({ getParentRoute: () => root, path: '/tasks', component: () => <Outlet /> })
  const index = createRoute({ getParentRoute: () => tasks, path: '/', component: () => <p>Aufgabenliste</p> })
  const detail = createRoute({ getParentRoute: () => tasks, path: '$taskId', component: () => <TaskDetail id="series" /> })
  const router = createRouter({ routeTree: root.addChildren([tasks.addChildren([index, detail])]), history: createMemoryHistory({ initialEntries: ['/tasks/series'] }) })
  render(<RouterProvider router={router} />)
  return { calls, router }
}

test('skip and reopen use the current occurrence version and refresh the display', async () => {
  const { calls } = setup()
  fireEvent.click(await screen.findByRole('button', { name: 'Überspringen' }))
  await screen.findByText(/Übersprungen/)
  expect(calls.find(call => call.path.endsWith('/occurrences/occ/skip'))).toMatchObject({ method: 'POST', body: { version: 4 } })
  fireEvent.click(screen.getByRole('button', { name: 'Wieder öffnen' }))
  await screen.findByRole('button', { name: 'Überspringen' })
  expect(calls.find(call => call.path.endsWith('/occurrences/occ/reopen'))).toMatchObject({ method: 'POST', body: { version: 5 } })
  expect(screen.queryByText(/Übersprungen/)).toBeNull()
})

test('archive sends the series version and displays the archived status', async () => {
  const { calls } = setup()
  fireEvent.click(await screen.findByRole('button', { name: 'Archivieren' }))
  await screen.findByText('Archiviert')
  expect(calls.find(call => call.path.endsWith('/tasks/series/archive'))).toMatchObject({ method: 'POST', body: { expected_version: 7 } })
  expect(screen.queryByRole('button', { name: 'Archivieren' })).toBeNull()
})

test('confirmed deletion sends the version and history confirmation, then navigates', async () => {
  const { calls, router } = setup()
  fireEvent.click(await screen.findByRole('button', { name: 'Endgültig löschen' }))
  expect(calls.some(call => call.method === 'DELETE')).toBe(false)
  fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Endgültig löschen' }))
  await screen.findByText('Aufgabenliste')
  expect(router.state.location.pathname).toBe('/tasks')
  expect(calls.find(call => call.method === 'DELETE')).toMatchObject({ path: '/api/v1/tasks/series', body: { expected_version: 7, confirm_history_loss: true } })
})

test('skip conflict keeps the detail open and reloads the current occurrence on request', async () => {
  const { calls, router } = setup(true)
  fireEvent.click(await screen.findByRole('button', { name: 'Überspringen' }))
  await screen.findByText('Die Aufgabe wurde inzwischen geändert. Prüfe den aktuellen Stand.')
  expect(router.state.location.pathname).toBe('/tasks/series')
  expect(calls.find(call => call.path.endsWith('/occurrences/occ/skip'))?.body).toEqual({ version: 4 })
  const reads = calls.filter(call => call.method === 'GET').length
  fireEvent.click(screen.getByRole('button', { name: 'Aktuellen Stand laden' }))
  await screen.findByText(/Erledigt/)
  await waitFor(() => expect(calls.filter(call => call.method === 'GET').length).toBeGreaterThan(reads))
  expect(screen.queryByText('Die Aufgabe wurde inzwischen geändert. Prüfe den aktuellen Stand.')).toBeNull()
})

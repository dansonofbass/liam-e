// i18n-exempt: synthetic API data and paths.
import { afterEach, expect, setSystemTime, test } from 'bun:test'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { client as api } from '../api/generated/client.gen'
import { TasksPage } from './TasksPage'
import { TaskDetail } from './TaskDetail'

const oldFetch = globalThis.fetch, oldConfig = api.getConfig()
const today = new Date().toISOString().slice(0, 10)
const schedule = { id: 'rev', version: 1, start_local: today, timezone: 'UTC', rrule: null, end_key: null, reconcile_target: null, reconcile_cursor: null }
const active = { id: 'active', title: 'Offene Aufgabe', description: '', source_account_id: null, source_message_id: null, version: 1, archived: false, schedule, complete: true }
const archived = { ...active, id: 'archived', title: 'Archiviert und fällig', archived: true }
const occurrence = { id: 'occ', series_id: 'archived', revision_id: 'rev', occurrence_key: today, due_local: today, due_at: null, status: 'open', version: 1 }
const windowData = { due_from: today, due_to: today }
let requests: { path: string; search: string; method: string; body?: unknown }[] = []
function setup(detail = false, activeDetail = false, incomplete = false) {
  api.setConfig({ baseUrl: 'https://api.example.test' })
  requests = []
  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const req = input instanceof Request ? input : new Request(input, init), url = new URL(req.url)
    requests.push({ path: url.pathname, search: url.search, method: req.method, body: ['POST', 'PATCH', 'DELETE'].includes(req.method) ? await req.clone().json() : undefined })
    if (url.pathname.endsWith('/reconcile')) return Response.json({ revision_id: 'rev', cursor: 'cursor', target: '2027-01-01T00:00:00Z', complete: true })
    if (url.pathname.endsWith('/complete') || req.method === 'PATCH' || req.method === 'DELETE') return Response.json({ detail: { code: 'task_version_conflict' } }, { status: 409 })
    if (url.pathname.endsWith('/accounts')) return Response.json([])
    if (url.pathname.endsWith('/occurrences')) {
      const status = url.searchParams.get('status')
      if (status === 'completed') return Response.json({ items: [{ ...occurrence, id: 'completed', series_id: 'active', status: 'completed', due_local: `${today}T12:00:00` }], next_cursor: null })
      if (status === 'skipped') return Response.json({ items: [{ ...occurrence, id: 'skipped', status: 'skipped', due_local: `${today}T09:00:00` }], next_cursor: null })
      return Response.json({ items: [occurrence], next_cursor: null })
    }
    if (url.pathname.endsWith('/tasks/archived')) return Response.json({ window: windowData, series: { ...(activeDetail ? { ...active, id: 'archived' } : archived), complete: !incomplete }, occurrences: { items: [occurrence], next_cursor: null } })
    return Response.json({ window: windowData, items: [{ ...active, complete: !incomplete }, archived], next_cursor: null })
  }) as typeof fetch
  const query = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  return render(<QueryClientProvider client={query}>{detail ? <TaskDetail id="archived" /> : <TasksPage />}</QueryClientProvider>)
}
afterEach(() => { cleanup(); globalThis.fetch = oldFetch; api.setConfig(oldConfig); history.replaceState({}, '', '/') })

test('open list includes due instances of archived series and sends independent source filter', async () => {
  setup()
  expect(await screen.findByRole('link', { name: 'Archiviert und fällig' })).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: 'Quelle' }))
  fireEvent.click(screen.getByRole('menuitemradio', { name: 'Ohne Mailbezug' }))
  await waitFor(() => expect(requests.some(request => request.path.endsWith('/tasks') && request.search.includes('source=unlinked'))).toBe(true))
  expect(globalThis.window.location.search).toContain('source=unlinked')
})

test('completed view merges skipped and completed occurrences in due order', async () => {
  setup()
  fireEvent.click(screen.getByRole('button', { name: 'Erledigt' }))
  const skipped = (await screen.findByRole('link', { name: 'Archiviert und fällig' })).closest('li')!
  const completed = (await screen.findByRole('link', { name: 'Offene Aufgabe' })).closest('li')!
  expect(skipped.textContent).toContain('Übersprungen')
  expect(completed.textContent).not.toContain('Übersprungen')
  expect(skipped.compareDocumentPosition(completed) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  expect(requests.some(request => request.path.endsWith('/occurrences') && request.search.includes('status=completed'))).toBe(true)
  expect(requests.some(request => request.path.endsWith('/occurrences') && request.search.includes('status=skipped'))).toBe(true)
})

test('period and incomplete notices keep date-only days in a western time zone', async () => {
  const oldZone = process.env.TZ
  process.env.TZ = 'America/Los_Angeles'
  setSystemTime(new Date('2028-01-30T20:00:00Z'))
  try {
    for (const detail of [false, true]) {
      setup(detail, false, true)
      const period = await screen.findByText(/^Zeitraum:/)
      const notice = await screen.findByText(/^Fälligkeiten werden ergänzt/)
      for (const element of [period, notice]) {
        expect(element.textContent).toContain('1.3.2027')
        expect(element.textContent).not.toMatch(/\d{4}-\d{2}-\d{2}/)
      }
      cleanup()
    }
  } finally {
    setSystemTime()
    if (oldZone === undefined) delete process.env.TZ
    else process.env.TZ = oldZone
  }
})

test('the delete confirmation traps focus and names irreversible history loss', async () => {
  setup(true)
  const trigger = await screen.findByRole('button', { name: 'Endgültig löschen' })
  trigger.focus()
  fireEvent.click(trigger)
  const dialog = screen.getByRole('dialog')
  expect(dialog.textContent).toContain('Die Aufgabe und ihr Verlauf werden endgültig gelöscht.')
  expect(dialog.contains(document.activeElement)).toBe(true)
  fireEvent.keyDown(document, { key: 'Escape' })
  expect(screen.queryByRole('dialog')).toBeNull()
  expect(document.activeElement).toBe(trigger)
  expect(within(document.body).getByRole('button', { name: 'Endgültig löschen' })).toBeTruthy()
})

test('editing targets the selected occurrence and sends both versions and scope', async () => {
  setup(true, true)
  fireEvent.click(await screen.findByRole('button', { name: 'Fälligkeit bearbeiten' }))
  fireEvent.click(screen.getByRole('button', { name: 'Änderung gilt für' }))
  fireEvent.click(screen.getByRole('menuitemradio', { name: 'Diese und folgende' }))
  fireEvent.click(screen.getByRole('button', { name: 'Änderung speichern' }))
  await screen.findByText('Die Aufgabe wurde inzwischen geändert. Prüfe den aktuellen Stand.')
  expect(requests.find(request => request.method === 'PATCH')?.body).toMatchObject({ expected_version: 1, expected_occurrence_version: 1, occurrence_id: 'occ', scope: 'this_and_following', start: today, timezone: 'UTC' })
})

test('a version conflict blocks further actions until the current state is explicitly loaded', async () => {
  setup(true)
  fireEvent.click(await screen.findByRole('button', { name: 'Erledigen' }))
  await screen.findByText('Die Aufgabe wurde inzwischen geändert. Prüfe den aktuellen Stand.')
  expect((screen.getByRole('button', { name: 'Überspringen' }) as HTMLButtonElement).disabled).toBe(true)
  expect(requests.find(request => request.path.endsWith('/complete'))?.body).toEqual({ version: 1 })
  fireEvent.click(screen.getByRole('button', { name: 'Aktuellen Stand laden' }))
  await waitFor(() => expect((screen.getByRole('button', { name: 'Überspringen' }) as HTMLButtonElement).disabled).toBe(false))
})

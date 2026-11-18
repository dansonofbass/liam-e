// i18n-exempt: synthetic API fixtures, routes and test labels.
import { afterEach, expect, test } from 'bun:test'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createMemoryHistory, createRootRoute, createRoute, createRouter, Outlet, RouterProvider } from '@tanstack/react-router'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { client as api } from '../api/generated/client.gen'
import { Preferences, PreferenceEditor } from './Preferences'
import { PreferenceContext } from '../chat/PreferenceContext'
import type { ContextOut } from '../api/generated/types.gen'

const original = globalThis.fetch, config = api.getConfig()
const row = { id: 'p', key: 'answer_length', scope: '*', value: 'test-only', status: 'active', version: 1, revision_id: 'r1', source: 'manual', confirmed_at: '2026-01-01T00:00:00Z' }
let requests: { method: string; path: string; body: any }[]
function setup(path: string, respond?: (request: Request) => Promise<Response | undefined>) {
  requests = []
  let current = { ...row }, personalization = { use_preferences: false, suggest_preferences: false, version: 1 }
  api.setConfig({ baseUrl: 'https://api.example.test' })
  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const req = input instanceof Request ? input : new Request(input, init), url = new URL(req.url)
    const body = ['PATCH', 'POST'].includes(req.method) ? await req.clone().json() : {}
    requests.push({ method: req.method, path: url.pathname, body })
    const custom = await respond?.(req)
    if (custom) return custom
    if (url.pathname.endsWith('/settings')) {
      if (req.method === 'PATCH') personalization = { ...personalization, ...body.personalization, version: 2 }
      return Response.json({ personalization })
    }
    if (url.pathname.endsWith('/summary')) return Response.json({ accounts: [] })
    if (req.method === 'DELETE') return new Response(null, { status: 204 })
    if (['POST', 'PATCH'].includes(req.method)) { current = { ...current, ...body, version: current.version + 1 }; return Response.json(current) }
    if (url.pathname.includes('/contexts/')) return Response.json({ enabled: true, resolver_version: '1', revisions: [{ revision_id: 'r1', value: 'test-only old', key: 'answer_length', removed: false }] })
    return Response.json([current])
  }) as typeof fetch
  const query = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const root = createRootRoute({ component: () => <QueryClientProvider client={query}><Outlet /></QueryClientProvider> })
  const list = createRoute({ getParentRoute: () => root, path: '/settings/preferences', component: Preferences })
  const fresh = createRoute({ getParentRoute: () => root, path: '/settings/preferences/new', component: PreferenceEditor })
  const edit = createRoute({ getParentRoute: () => root, path: '/settings/preferences/p', component: () => <PreferenceEditor id="p" /> })
  const historical = createRoute({ getParentRoute: () => root, path: '/history', component: () => <PreferenceContext context={{ id: 'c', preferences_enabled: true, preference_revision_ids_json: '["r1"]' } as ContextOut} /> })
  const router = createRouter({ routeTree: root.addChildren([list, fresh, edit, historical]), history: createMemoryHistory({ initialEntries: [path] }) })
  render(<RouterProvider router={router} />)
}
afterEach(() => { cleanup(); globalThis.fetch = original; api.setConfig(config) })

test('list names scope, source and status, with explicit opt-in confirmation', async () => {
  setup('/settings/preferences')
  expect(await screen.findByText('test-only')).toBeTruthy()
  expect(screen.getByText(/Alle Konten · Von dir eingetragen · Aktiv/)).toBeTruthy()
  fireEvent.click(await screen.findByRole('button', { name: 'Verwendung einschalten' }))
  const dialog = screen.getByRole('dialog')
  expect(dialog.contains(document.activeElement)).toBe(true)
  expect(within(dialog).getByText('Passende Präferenzen werden für Antworten an Mistral übermittelt.')).toBeTruthy()
  expect(requests.filter(r => r.method === 'PATCH')).toHaveLength(0)
  fireEvent.click(within(dialog).getByRole('button', { name: 'Verwendung einschalten' }))
  await screen.findByText('Verwendung eingeschaltet')
  expect(requests.find(r => r.method === 'PATCH')?.body).toEqual({ personalization: { expected_version: 1, use_preferences: true } })
})

test('manual save does not opt in, guards double-clicks and preserves focus', async () => {
  setup('/settings/preferences/new')
  const value = await screen.findByLabelText('Wert')
  expect(document.activeElement).toBe(value)
  fireEvent.change(value, { target: { value: 'test-only new' } })
  const save = screen.getByRole('button', { name: 'Präferenz speichern' })
  fireEvent.click(save); fireEvent.click(save)
  await screen.findByText('Gespeichert. Verwendung ist ausgeschaltet.')
  expect(requests.filter(r => r.method === 'POST')).toHaveLength(1)
  expect(requests.some(r => r.method === 'PATCH' && r.path.endsWith('/settings'))).toBe(false)
})

test('edit and pause use versions; delete dialog explains surviving history', async () => {
  setup('/settings/preferences/p')
  fireEvent.change(await screen.findByLabelText('Wert'), { target: { value: 'test-only changed' } })
  fireEvent.click(screen.getByRole('button', { name: 'Präferenz speichern' }))
  await screen.findByText('Gespeichert. Verwendung ist ausgeschaltet.')
  expect(requests.find(r => r.method === 'PATCH')?.body).toEqual({ expected_version: 1, value: 'test-only changed', scope: '*' })
  fireEvent.click(screen.getByRole('button', { name: 'Pausieren' }))
  await screen.findByRole('button', { name: 'Aktivieren' })
  fireEvent.click(screen.getByRole('button', { name: 'Löschen' }))
  let dialog = screen.getByRole('dialog')
  expect(dialog.contains(document.activeElement)).toBe(true)
  expect(dialog.textContent).toContain('Ursprüngliche Chatnachrichten und Antworten bleiben erhalten.')
  expect(within(dialog).getByRole('link', { name: 'Neuen Chat ohne bisherigen Kontext öffnen' })).toBeTruthy()
  fireEvent.keyDown(document, { key: 'Escape' })
  expect(screen.queryByRole('dialog')).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: 'Löschen' }))
  dialog = screen.getByRole('dialog')
  fireEvent.click(within(dialog).getByRole('button', { name: 'Löschen' }))
  await screen.findByText('Präferenz entfernt')
  expect(requests.filter(r => r.method === 'DELETE')).toHaveLength(1)
})

test('conflicts preserve values until explicit reload', async () => {
  setup('/settings/preferences/p', async req => req.method === 'PATCH' ? Response.json({ detail: { code: 'preference_conflict' } }, { status: 409 }) : undefined)
  fireEvent.change(await screen.findByLabelText('Wert'), { target: { value: 'test-only unsaved' } })
  fireEvent.click(screen.getByRole('button', { name: 'Präferenz speichern' }))
  fireEvent.click(await screen.findByRole('button', { name: 'Aktuelle Fassung laden' }))
  await waitFor(() => expect((screen.getByLabelText('Wert') as HTMLTextAreaElement).value).toBe('test-only'))
})

test('empty and loading states are explicit', async () => {
  let release!: (r: Response) => void
  setup('/settings/preferences', async req => req.url.endsWith('/preferences') ? await new Promise<Response>(r => { release = r }) : undefined)
  await waitFor(() => expect(screen.getAllByText('Präferenzen werden geladen …').length).toBeGreaterThan(0))
  await waitFor(() => expect(release).toBeDefined())
  release(Response.json([]))
  await screen.findByText('Noch keine Präferenzen gespeichert. Lege fest, wie liam-e für dich schreiben soll.')
})

test('failed reads offer retry', async () => {
  setup('/settings/preferences', async req => req.url.endsWith('/preferences') ? Response.json({}, { status: 503 }) : undefined)
  await screen.findByText('Die Präferenzen konnten nicht geladen werden. Versuch es noch einmal.')
  expect(screen.getByRole('button', { name: 'Noch mal versuchen' })).toBeTruthy()
})

for (const removed of [false, true]) test(`history uses exact revisions; removed=${removed}`, async () => {
  setup('/history', async req => req.url.includes('/contexts/') ? Response.json({ enabled: true, resolver_version: '1', revisions: [{ revision_id: 'r1', removed, key: removed ? null : 'answer_length', value: removed ? null : 'test-only old' }] }) : undefined)
  fireEvent.click(await screen.findByRole('button', { name: '1 Präferenz verwendet' }))
  await screen.findByText(removed ? 'Präferenz entfernt' : 'test-only old')
  expect(screen.queryByText('test-only')).toBeNull()
})

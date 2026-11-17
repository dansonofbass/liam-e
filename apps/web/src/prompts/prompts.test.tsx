// i18n-exempt: synthetic API fixtures and route paths.
import { afterEach, expect, test } from 'bun:test'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createMemoryHistory, createRootRoute, createRoute, createRouter, Outlet, RouterProvider } from '@tanstack/react-router'
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { client as api } from '../api/generated/client.gen'
import { ChatSessionProvider } from '../chat/session'
import { Editor } from './Editor'
import { Library } from './Library'
import { Settings } from './Settings'
import { TemplateMenu } from './TemplateMenu'

const originalFetch = globalThis.fetch
const originalConfig = api.getConfig()
const template = { id: 'p', name: 'Fristen', text: 'Fasse offene Fristen zusammen.', version: 2, revision_id: 'r2', content_hash: 'hash2', updated_at: '2020-01-15T12:00:00Z' }
const detail = { ...template, revisions: [{ id: 'r2', number: 2, content: template.text, content_hash: 'hash2' }, { id: 'r1', number: 1, content: 'Nenne die Fristen.', content_hash: 'hash1' }] }
const conversation = { id: 'c', title: 'Test', model: 'm', version: 3, prompt_revision_id: 'r1', account_scope_json: JSON.stringify({ selection: 'a', account_ids: ['a'] }), created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z' }
let requests: { path: string; search: string; method: string; body: Record<string, unknown> }[]
function setup(path: string, respond?: (request: Request) => Promise<Response | undefined>) {
  requests = []
  api.setConfig({ baseUrl: 'https://api.example.test' })
  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const request = input instanceof Request ? input : new Request(input, init)
    const url = new URL(request.url)
    requests.push({ path: url.pathname, search: url.search, method: request.method, body: request.method === 'PATCH' || request.method === 'POST' ? await request.clone().json() as Record<string, unknown> : {} })
    const custom = await respond?.(request)
    if (custom) return custom
    const data = url.pathname.endsWith('/conversations') ? [conversation] : url.pathname.endsWith('/prompts/p') ? detail : [template]
    return Response.json(data)
  }) as typeof fetch
  const query = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } })
  const root = createRootRoute({ component: () => <QueryClientProvider client={query}><ChatSessionProvider><Outlet /></ChatSessionProvider></QueryClientProvider> })
  const settings = createRoute({ getParentRoute: () => root, path: '/settings', component: Settings })
  const list = createRoute({ getParentRoute: () => settings, path: '/prompts', component: Library })
  const fresh = createRoute({ getParentRoute: () => settings, path: '/prompts/new', component: () => <Editor /> })
  const edit = createRoute({ getParentRoute: () => settings, path: '/prompts/$promptId', component: () => <Editor id="p" /> })
  const chat = createRoute({ getParentRoute: () => root, path: '/chat', component: () => <TemplateMenu conversationId="c" /> })
  const router = createRouter({ routeTree: root.addChildren([settings.addChildren([list, fresh, edit]), chat]), history: createMemoryHistory({ initialEntries: [path] }) })
  render(<RouterProvider router={router} />)
  return { query, router }
}
afterEach(() => { cleanup(); globalThis.fetch = originalFetch; api.setConfig(originalConfig) })

test('the current settings section link is marked as the current page', async () => {
  setup('/settings/prompts')
  expect((await screen.findByRole('link', { name: 'Vorlagen' })).getAttribute('aria-current')).toBe('page')
})

test('library displays a date only when it is known', async () => {
  setup('/settings/prompts', async request => request.url.endsWith('/prompts')
    ? Response.json([template, { ...template, id: 'old', name: 'Alt', updated_at: null }]) : undefined)
  const dated = await screen.findByRole('link', { name: /^Fristen/ })
  expect(within(dated).getByText(/15\.1\.2020/)).toBeTruthy()
  expect(dated.querySelector('time')?.getAttribute('datetime')).toBe(template.updated_at)
  expect(screen.getByRole('link', { name: /Alt/ }).querySelector('time')).toBeNull()
})

test('creates a template only on submit using the generated client', async () => {
  const { router } = setup('/settings/prompts/new', async request => request.method === 'POST' ? Response.json(template) : undefined)
  fireEvent.change(await screen.findByLabelText('Name'), { target: { value: 'Fristen' } })
  fireEvent.change(screen.getByLabelText('Anweisungen'), { target: { value: template.text } })
  expect(requests.filter(item => item.method === 'POST')).toHaveLength(0)
  fireEvent.click(screen.getByRole('button', { name: 'Vorlage speichern' }))
  await waitFor(() => expect(router.state.location.pathname).toBe('/settings/prompts'))
  expect(requests.find(item => item.method === 'POST')?.body).toEqual({ name: 'Fristen', text: template.text })
})

test('edit conflicts preserve inputs until explicitly loading the current version', async () => {
  setup('/settings/prompts/p', async request => request.method === 'PATCH' ? Response.json({ detail: { code: 'version_conflict' } }, { status: 409 }) : undefined)
  fireEvent.change(await screen.findByLabelText('Name'), { target: { value: 'Meine Änderung' } })
  fireEvent.click(screen.getByRole('button', { name: 'Vorlage speichern' }))
  fireEvent.click(await screen.findByRole('button', { name: 'Aktuelle Fassung laden' }))
  await waitFor(() => expect((screen.getByLabelText('Name') as HTMLInputElement).value).toBe('Fristen'))
  expect(requests.find(item => item.method === 'PATCH')?.body).toMatchObject({ expected_version: 2, name: 'Meine Änderung' })
})

test('delete requires the focused dialog and sends the version', async () => {
  setup('/settings/prompts/p', async request => request.method === 'DELETE' ? new Response(null, { status: 204 }) : undefined)
  fireEvent.click(await screen.findByRole('button', { name: 'Vorlage löschen' }))
  const dialog = screen.getByRole('dialog')
  expect(dialog.textContent).toContain('Bereits übermittelte Inhalte lassen sich nicht zurückholen.')
  expect(dialog.contains(document.activeElement)).toBe(true)
  fireEvent.keyDown(document, { key: 'Escape' })
  expect(screen.queryByRole('dialog')).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: 'Vorlage löschen' }))
  fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Vorlage löschen' }))
  await waitFor(() => expect(requests.filter(item => item.method === 'DELETE')).toHaveLength(1))
  expect(requests.find(item => item.method === 'DELETE')?.search).toBe('?expected_version=2')
})

test('restores a pinned revision and adopts a newer version only after server acceptance', async () => {
  let accept!: (response: Response) => void
  let accepted = false
  const updated = { ...conversation, version: 4, prompt_revision_id: 'r2' }
  const { query } = setup('/chat', async request => {
    if (request.method === 'PATCH') { const response = await new Promise<Response>(resolve => { accept = resolve }); accepted = true; return response }
    return accepted && request.url.endsWith('/conversations') ? Response.json([updated]) : undefined
  })
  expect(await screen.findByRole('button', { name: 'Vorlage: Fristen' })).toBeTruthy()
  fireEvent.click(await screen.findByRole('button', { name: 'Version übernehmen' }))
  await waitFor(() => expect(accept).toBeDefined())
  expect(query.getQueryData(['conversations'])).toEqual([conversation])
  expect(requests.find(item => item.method === 'PATCH')?.body).toEqual({ expected_version: 3, prompt_revision_id: 'r2' })
  await act(async () => { accept(Response.json(updated)) })
  await waitFor(() => expect(query.getQueryData(['conversations'])).toEqual([updated]))
  expect(screen.queryByRole('button', { name: 'Version übernehmen' })).toBeNull()
})

test('clearing a selection persists null and external changes appear on refetch', async () => {
  let stored: typeof conversation | { prompt_revision_id: null; version: number } = conversation
  const { query } = setup('/chat', async request => {
    if (request.method === 'PATCH') { stored = { ...conversation, prompt_revision_id: null, version: 4 }; return Response.json(stored) }
    return request.url.endsWith('/conversations') ? Response.json([stored]) : undefined
  })
  fireEvent.click(await screen.findByRole('button', { name: 'Vorlage: Fristen' }))
  fireEvent.click(screen.getByRole('menuitemradio', { name: 'Standard' }))
  await screen.findByRole('button', { name: 'Vorlage: Standard' })
  expect(requests.find(item => item.method === 'PATCH')?.body.prompt_revision_id).toBeNull()
  stored = { ...conversation, version: 5 }
  await act(async () => { await query.refetchQueries({ queryKey: ['conversations'] }) })
  expect(await screen.findByRole('button', { name: 'Vorlage: Fristen' })).toBeTruthy()
})

for (const status of [404, 503]) test(`editor failure ${status} preserves unsaved input`, async () => {
  setup('/settings/prompts/p', async request => request.method === 'PATCH' ? Response.json({ detail: { code: status === 404 ? 'prompt_unavailable' : 'prompts_unavailable' } }, { status }) : undefined)
  fireEvent.change(await screen.findByLabelText('Name'), { target: { value: 'Nicht gespeichert' } })
  fireEvent.click(screen.getByRole('button', { name: 'Vorlage speichern' }))
  await screen.findByRole('alert')
  expect((screen.getByLabelText('Name') as HTMLInputElement).value).toBe('Nicht gespeichert')
})

test('selection failures keep the stored revision and offer an explicit reload', async () => {
  const { query } = setup('/chat', async request => request.method === 'PATCH' ? Response.json({ detail: { code: 'version_conflict' } }, { status: 409 }) : undefined)
  fireEvent.click(await screen.findByRole('button', { name: 'Vorlage: Fristen' }))
  expect(await screen.findByText(template.text)).toBeTruthy()
  fireEvent.click(screen.getByRole('menuitemradio', { name: 'Standard' }))
  expect(await screen.findByRole('button', { name: 'Aktuelle Fassung laden' })).toBeTruthy()
  expect(query.getQueryData(['conversations'])).toEqual([conversation])
})

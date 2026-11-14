import { afterEach, expect, mock, spyOn, test } from 'bun:test'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createMemoryHistory, createRootRoute, createRoute, createRouter, Outlet, RouterProvider, useParams } from '@tanstack/react-router'
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import * as sdk from '../api/generated/sdk.gen'
import type { InsightOut } from '../api/generated/types.gen'
import { ChatSessionProvider } from '../chat/session'
import { Route as MailRoute } from '../routes/_app/mail'
import { inboxSearchSchema } from './filters'
import { MailView } from './MailView'

const originalMatchMedia = window.matchMedia, originalFetch = globalThis.fetch
const mail = { id: 'm1', account_id: 'a', color_index: 0, sender_name: 'Anna', sender_address: 'anna@example.com', to: ['ich@example.com'], cc: [], subject: 'Termin', snippet: '', body_text: '<b>fett</b>', internal_date: null, deadline: null, has_attachments: true, attachments: [{ name: 'Abrechnung_2025.pdf', size: 217088, content_type: 'application/pdf' }], is_flagged: false, is_read: true, needs_reply: false, can_unsubscribe: true, thread_id: null }
function setup({ mobile = false, unread = false, missing = false, loading = false, failed = false, path = '/mail/m1', stream = false, insight }: { mobile?: boolean; unread?: boolean; missing?: boolean; loading?: boolean; failed?: boolean; path?: string; stream?: boolean; insight?: () => Promise<{ data: InsightOut }> } = {}) {
  window.matchMedia = ((q: string) => ({ matches: !mobile && (q.includes('1024px') || q.includes('640px')), addEventListener() {}, removeEventListener() {} })) as unknown as typeof window.matchMedia
  let request: Record<string, unknown> | undefined
  globalThis.fetch = ((_url: unknown, init: RequestInit) => {
    request = JSON.parse(String(init.body)) as Record<string, unknown>
    return Promise.resolve(new Response(new ReadableStream({ start(controller) { if (stream) controller.enqueue(new TextEncoder().encode('event: start\ndata: {"event":"start","conversation_id":"c1","user_message_id":"u1"}\n\n')) } })))
  }) as typeof fetch
  const rows = [{ ...mail, is_read: !unread }, { ...mail, id: 'm2', subject: 'Zweite', is_read: !unread }]
  const getInsight = spyOn(sdk, 'mailMessageInsight').mockImplementation((insight ?? (async () => ({ data: { points: [], deadline: null, followups: [], needs_reply: false, model: '', created_at: '' } }))) as never)
  spyOn(sdk, 'mailSummary').mockImplementation((async () => ({ data: { accounts: [{ id: 'a', display_name: 'Privat', color_index: 0, state: 'ok' }], unread_total: unread ? 1 : 0, last_sync_at: null } })) as never)
  spyOn(sdk, 'mailMessagesList').mockImplementation((async () => ({ data: { items: rows, next_cursor: null } })) as never)
  const get = spyOn(sdk, 'mailMessageGet').mockImplementation((async (options: { path: { message_id: string } }) => { if (missing) return { error: { detail: 'Mail nicht gefunden.' }, response: new Response(null, { status: 404 }) }; if (failed) return { error: { detail: 'down' }, response: new Response(null, { status: 500 }) }; if (loading) return await new Promise(() => {}); return { data: rows.find(row => row.id === options.path.message_id) ?? mail } }) as never)
  const action = spyOn(sdk, 'mailMessageAction').mockImplementation((async (options: { path: { message_id: string } }) => ({ data: { action_id: 'act', message: rows.find(row => row.id === options.path.message_id) }, response: { status: 200 } })) as never)
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, retryDelay: 0 } } })
  const root = createRootRoute({ component: () => <QueryClientProvider client={client}><ChatSessionProvider><Outlet /></ChatSessionProvider></QueryClientProvider> })
  const inbox = createRoute({ getParentRoute: () => root, path: '/mail', validateSearch: inboxSearchSchema, component: MailRoute.options.component })
  const index = createRoute({ getParentRoute: () => inbox, path: '/', component: () => <div>Inbox index</div> })
  const detail = createRoute({ getParentRoute: () => inbox, path: '$messageId', component: () => { const { messageId } = useParams({ strict: false }) as { messageId: string }; return <MailView id={messageId} /> } })
  const home = createRoute({ getParentRoute: () => root, path: '/', validateSearch: (s: Record<string, unknown>) => s, component: () => <div>Home</div> })
  const chat = createRoute({ getParentRoute: () => root, path: '/chat/$conversationId', component: () => <div>Chat</div> })
  const router = createRouter({ routeTree: root.addChildren([home, inbox.addChildren([index, detail]), chat]), history: createMemoryHistory({ initialEntries: [path] }) })
  const view = render(<RouterProvider router={router} />)
  return { client, router, view, action, get, getInsight, request: () => request }
}
afterEach(() => { cleanup(); mock.restore(); window.matchMedia = originalMatchMedia; globalThis.fetch = originalFetch })

test('opening unread mail marks it read once across rerender and refetch, updating list', async () => {
  const { action, client, view, router } = setup({ unread: true })
  await waitFor(() => expect(action.mock.calls.length).toBe(1))
  await waitFor(() => expect(client.getQueriesData<{ pages: { items: { id: string; is_read: boolean }[] }[] }>({ queryKey: ['messages'] }).some(([, d]) => d?.pages.some(page => page.items.some(row => row.id === 'm1' && row.is_read)))).toBe(true))
  expect(action.mock.calls[0]?.[0]?.body).toEqual({ kind: 'mark_read' })
  view.rerender(<RouterProvider router={router} />)
  await act(async () => { await client.refetchQueries({ queryKey: ['message', 'm1'] }) })
  expect(action.mock.calls.length).toBe(1)
})

test('read mail is not automatically marked and manual unread is not reversed', async () => {
  const { action } = setup(); await screen.findByRole('heading', { name: 'Termin' })
  expect(action).not.toHaveBeenCalled()
  fireEvent.click(within(document.querySelector('.le-mail-view') as HTMLElement).getByRole('button', { name: 'Als ungelesen markieren' }))
  await waitFor(() => expect(action.mock.calls.length).toBe(1))
  await new Promise(resolve => setTimeout(resolve, 20))
  expect(action.mock.calls.length).toBe(1)
})

test('manual unread after auto read is not marked read again', async () => {
  const { action, client } = setup({ unread: true })
  await waitFor(() => expect(action.mock.calls.length).toBe(1))
  await waitFor(() => expect(client.isFetching({ queryKey: ['message', 'm1'] })).toBe(0))
  await act(async () => { client.setQueryData(['message', 'm1'], { ...mail, is_read: true }) })
  const view = document.querySelector('.le-mail-view') as HTMLElement
  fireEvent.click(await within(view).findByRole('button', { name: 'Als ungelesen markieren' }))
  await waitFor(() => expect(action.mock.calls.length).toBe(2))
  await act(async () => { await client.refetchQueries({ queryKey: ['message', 'm1'] }) })
  expect(action.mock.calls.map(([options]) => options?.body?.kind)).toEqual(['mark_read', 'mark_unread'])
})

test('manual unread waits for pending automatic read and remains unread in both caches', async () => {
  const { action, get, client } = setup({ unread: true })
  let serverRead = false
  let finishRead!: (value: unknown) => void
  get.mockImplementation((async () => ({ data: { ...mail, is_read: serverRead } })) as never)
  action.mockImplementation(((options: { body: { kind: string } }) => {
    if (options.body.kind === 'mark_read') return new Promise(resolve => { finishRead = resolve })
    serverRead = false
    return Promise.resolve({ data: { action_id: 'unread', message: { ...mail, is_read: false } }, response: { status: 200 } })
  }) as never)
  await waitFor(() => expect(action.mock.calls.length).toBe(1))
  const view = document.querySelector('.le-mail-view') as HTMLElement
  fireEvent.click(await within(view).findByRole('button', { name: 'Als ungelesen markieren' }))
  await act(async () => { await Promise.resolve() })
  expect(action.mock.calls.length).toBe(1)
  await act(async () => {
    serverRead = true
    finishRead({ data: { action_id: 'read', message: { ...mail, is_read: true } }, response: { status: 200 } })
  })
  await waitFor(() => expect(action.mock.calls.map(([options]) => options?.body?.kind)).toEqual(['mark_read', 'mark_unread']))
  await waitFor(() => expect(client.getQueryData<{ is_read: boolean }>(['message', 'm1'])?.is_read).toBe(false))
  expect(client.getQueriesData<{ pages: { items: { id: string; is_read: boolean }[] }[] }>({ queryKey: ['messages'] }).some(([, data]) => data?.pages.some(page => page.items.some(row => row.id === 'm1' && !row.is_read)))).toBe(true)
})

test('mobile bars contain the requested actions; desktop has no back button', async () => {
  setup({ mobile: true }); await screen.findByRole('heading', { name: 'Termin' })
  for (const name of ['Zurück zum Posteingang', 'Archivieren', 'Als ungelesen markieren', 'In den Papierkorb', 'Weitere Aktionen', 'Im Chat fragen', 'Antwort entwerfen']) expect(screen.getByRole('button', { name })).toBeTruthy()
  cleanup(); mock.restore(); setup(); await screen.findByRole('heading', { name: 'Termin' })
  expect(screen.queryByRole('button', { name: 'Zurück zum Posteingang' })).toBeNull()
})

test('mail body is literal text and attachment is non-interactive', async () => {
  const { view } = setup(); await screen.findByRole('heading', { name: 'Termin' })
  expect(screen.getByText('<b>fett</b>')).toBeTruthy()
  expect(view.container.querySelector('b')).toBeNull()
  expect(screen.getByText('Abrechnung_2025.pdf · 212 KB')).toBeTruthy()
})

test('not found offers return to inbox', async () => {
  const { router, get } = setup({ mobile: true, missing: true, path: '/mail/unknown' })
  expect(await screen.findByText('Die Mail ist nicht mehr da.')).toBeTruthy()
  expect(get.mock.calls.length).toBe(1)
  fireEvent.click(screen.getByRole('button', { name: 'Zum Posteingang' }))
  await waitFor(() => expect(router.state.location.pathname).toBe('/mail'))
})

test('draft reply starts a turn with context and opens conversation', async () => {
  const { router, request } = setup({ stream: true }); await screen.findByRole('heading', { name: 'Termin' })
  fireEvent.click(screen.getByRole('button', { name: 'Antwort entwerfen' }))
  await waitFor(() => expect(request()).toMatchObject({ text: 'Entwirf eine Antwort auf diese Mail.', context_message_id: 'm1' }))
  expect(request()?.account_id).toBeUndefined()
  await waitFor(() => expect(router.state.location.pathname).toBe('/chat/c1'))
})

test('ask in chat opens start page with mail reference', async () => {
  const { router } = setup(); await screen.findByRole('heading', { name: 'Termin' })
  fireEvent.click(screen.getByRole('button', { name: 'Im Chat fragen' }))
  await waitFor(() => expect(router.state.location.searchStr).toContain('about=m1'))
})

for (const mobile of [false, true]) test(`${mobile ? 'mobile' : 'desktop'} archive navigates and shows undo`, async () => {
  const { router } = setup({ mobile, path: '/mail/m1?unread=true' }); await screen.findByRole('heading', { name: 'Termin' })
  const actions = mobile ? screen.getByRole('button', { name: 'Archivieren' }) : within(document.querySelector('.le-mail-view') as HTMLElement).getByRole('button', { name: 'Archivieren' })
  fireEvent.click(actions)
  await waitFor(() => expect(router.state.location.pathname).toBe(mobile ? '/mail' : '/mail/m2'))
  expect(router.state.location.searchStr).toContain('unread=true')
  expect(await screen.findByText('Rückgängig')).toBeTruthy()
})

test('silent auto read preserves an existing undo toast', async () => {
  const { router, action } = setup({ unread: true, path: '/mail' })
  await screen.findByText('Termin')
  fireEvent.keyDown(document.body, { key: 'j' }); fireEvent.keyDown(document.body, { key: 'e' })
  expect(await screen.findByText('Rückgängig')).toBeTruthy()
  await act(async () => { await router.navigate({ to: '/mail/$messageId', params: { messageId: 'm2' } }) })
  await waitFor(() => expect(action.mock.calls.some(([options]) => options?.path?.message_id === 'm2' && options?.body?.kind === 'mark_read')).toBe(true))
  expect(screen.getByText('Rückgängig')).toBeTruthy()
})


test('loading displays placeholders and mobile back button', async () => {
  const { view } = setup({ mobile: true, loading: true })
  expect(await screen.findByRole('status', { name: '' })).toBeTruthy()
  expect(screen.getByText('Mail wird geladen …')).toBeTruthy()
  expect(view.container.querySelector('.le-mail-placeholder[aria-hidden="true"]')).toBeTruthy()
  expect(screen.getByRole('button', { name: 'Zurück zum Posteingang' })).toBeTruthy()
})

test('newsletter menu starts the contextual confirmation turn', async () => {
  const { request } = setup({ mobile: true }); await screen.findByRole('heading', { name: 'Termin' })
  fireEvent.click(screen.getByRole('button', { name: 'Weitere Aktionen' }))
  fireEvent.click(screen.getByRole('menuitem', { name: 'Newsletter abbestellen' }))
  await waitFor(() => expect(request()).toMatchObject({ text: 'Bestelle diesen Newsletter ab.', context_message_id: 'm1' }))
  expect(request()?.account_id).toBeUndefined()
  expect((screen.getByRole('button', { name: 'Antwort entwerfen' }) as HTMLButtonElement).disabled).toBe(true)
})


test('other load errors can retry or return to the filtered inbox', async () => {
  const { router, get } = setup({ mobile: true, failed: true, path: '/mail/m1?unread=true' })
  expect(await screen.findByText('Die Mail konnte nicht geladen werden. Versuch es gleich noch mal.')).toBeTruthy()
  expect(get.mock.calls.length).toBe(3)
  fireEvent.click(screen.getByRole('button', { name: 'Noch mal versuchen' }))
  await waitFor(() => expect(get.mock.calls.length).toBeGreaterThan(3))
  fireEvent.click(await screen.findByRole('button', { name: 'Zum Posteingang' }))
  await waitFor(() => expect(router.state.location.pathname).toBe('/mail'))
  expect(router.state.location.searchStr).toContain('unread=true')
})


const insightData: InsightOut = { points: ['Erster Punkt', '**fett**', 'Dritter Punkt', 'Vierter Punkt'], deadline: '2026-11-20', followups: ['Was ist wichtig?', 'Termin prüfen', 'Dritter Vorschlag'], needs_reply: false, model: 'm', created_at: '' }

test('insight shows loading then up to three literal points and a deadline', async () => {
  let finish!: (value: { data: InsightOut }) => void
  const { view } = setup({ insight: () => new Promise(resolve => { finish = resolve }) })
  const section = await screen.findByRole('region', { name: 'Zusammenfassung von liam-e' })
  expect(section.getAttribute('aria-busy')).toBe('true')
  expect(within(section).getByText('Kurz gefasst wird geladen …')).toBeTruthy()
  expect(section.querySelectorAll('[aria-hidden="true"] .le-insight-placeholder-line')).toHaveLength(3)
  await act(async () => { finish({ data: insightData }) })
  expect(await within(section).findByText('Erster Punkt')).toBeTruthy()
  expect(within(section).getByText('**fett**')).toBeTruthy()
  expect(section.querySelector('strong')).toBeNull()
  expect(within(section).getByText('Frist Fr., 20.11.')).toBeTruthy()
  expect(within(section).queryByText('Vierter Punkt')).toBeNull()
  expect(within(section).queryByText('Dritter Vorschlag')).toBeNull()
  expect(view.container.querySelector('.le-mail-header')?.nextElementSibling).toBe(section)
  expect(section.nextElementSibling?.classList.contains('le-mail-text')).toBe(true)
})

test('insight error shows quiet fallback without retry', async () => {
  const { getInsight } = setup({ insight: async () => { throw { detail: { code: 'insight_unavailable' }, status: 503 } } })
  expect(await screen.findByText('Kurz gefasst ist gerade nicht verfügbar.')).toBeTruthy()
  expect(getInsight.mock.calls.length).toBe(1)
})

test('insight followup sends context and disables chips while working', async () => {
  const { request } = setup({ insight: async () => ({ data: insightData }) })
  fireEvent.click(await screen.findByRole('button', { name: 'Was ist wichtig?' }))
  await waitFor(() => expect(request()).toMatchObject({ text: 'Was ist wichtig?', context_message_id: 'm1' }))
  expect(request()?.account_id).toBeUndefined()
  expect((screen.getByRole('button', { name: 'Termin prüfen' }) as HTMLButtonElement).disabled).toBe(true)
})

test('empty insight renders no box', async () => {
  const { getInsight } = setup()
  await screen.findByRole('heading', { name: 'Termin' })
  await waitFor(() => expect(getInsight.mock.calls.length).toBe(1))
  await waitFor(() => expect(screen.queryByRole('region', { name: 'Zusammenfassung von liam-e' })).toBeNull())
})


test('insight followup opens the conversation when the turn starts', async () => {
  const { router, request } = setup({ stream: true, insight: async () => ({ data: insightData }) })
  fireEvent.click(await screen.findByRole('button', { name: 'Was ist wichtig?' }))
  await waitFor(() => expect(request()).toMatchObject({ text: 'Was ist wichtig?', context_message_id: 'm1' }))
  await waitFor(() => expect(router.state.location.pathname).toBe('/chat/c1'))
})

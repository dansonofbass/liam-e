import { afterEach, expect, spyOn, test } from 'bun:test'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createMemoryHistory, createRootRoute, createRoute, createRouter, Outlet, RouterProvider } from '@tanstack/react-router'
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import * as sdk from '../api/generated/sdk.gen'
import type { ChatMessageOut, MailSummaryOut } from '../api/generated/types.gen'
import { Route as StartRoute } from '../routes/_app/index'
import { Conversation } from './Conversation'
import { ChatSessionProvider } from './session'

const originalFetch = globalThis.fetch
const originalMatchMedia = window.matchMedia
let stream: ReadableStreamDefaultController<Uint8Array>
let signal: AbortSignal
let history: ChatMessageOut[] = []
let requestBody: Record<string, unknown>
let summary: MailSummaryOut = { accounts: [], unread_total: 0, newsletter_senders: 0, last_sync_at: null }
function setup(path = '/') {
  history = []
  summary = { accounts: [], unread_total: 0, newsletter_senders: 0, last_sync_at: null }
  window.matchMedia = (() => ({ matches: true })) as unknown as typeof window.matchMedia
  globalThis.fetch = ((_url: unknown, init: RequestInit) => { signal = init.signal!; requestBody = JSON.parse(String(init.body)) as Record<string, unknown>; return Promise.resolve(new Response(new ReadableStream({ start(c) { stream = c } }))) }) as typeof fetch
  spyOn(sdk, 'chatHistory').mockImplementation((async () => ({ data: history })) as never)
  spyOn(sdk, 'mailSummary').mockImplementation((async () => ({ data: summary })) as never)
  spyOn(sdk, 'chatModelsList').mockImplementation((async () => ({ data: [] })) as never)
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const root = createRootRoute({ component: () => <QueryClientProvider client={client}><ChatSessionProvider><Outlet /></ChatSessionProvider></QueryClientProvider> })
  const start = createRoute({ getParentRoute: () => root, path: '/', component: StartRoute.options.component })
  const chat = createRoute({ getParentRoute: () => root, path: '/chat/$conversationId', component: () => <Conversation conversationId="c" /> })
  const router = createRouter({ routeTree: root.addChildren([start, chat]), history: createMemoryHistory({ initialEntries: [path] }) })
  render(<RouterProvider router={router} />)
  return { client, router }
}
function frame(value: object) { stream.enqueue(new TextEncoder().encode(`data: ${JSON.stringify(value)}\n\n`)) }
async function send() {
  const input = await screen.findByPlaceholderText('Frag etwas zu deinen Mails …')
  fireEvent.change(input, { target: { value: 'Meine Frage' } })
  fireEvent.click(screen.getByRole('button', { name: 'Senden' }))
}
afterEach(() => { cleanup(); globalThis.fetch = originalFetch; window.matchMedia = originalMatchMedia })

test('shows status, streams text and stops the answer', async () => {
  setup('/chat/c'); await send()
  await act(async () => { frame({ event: 'start', conversation_id: 'c', user_message_id: 'u' }); frame({ event: 'status', code: 'searching', count: 4 }) })
  expect(await screen.findByText('Durchsuche 4 Konten …')).toBeTruthy()
  expect(screen.getByRole('button', { name: 'Anhalten' })).toBeTruthy()
  await act(async () => { frame({ event: 'delta', text: 'Eine Antwort' }) })
  expect(await screen.findByText('Eine Antwort')).toBeTruthy()
  expect(document.querySelector('.sr-only[aria-live="polite"]')?.textContent).toBe('')
  fireEvent.click(screen.getByRole('button', { name: 'Anhalten' }))
  expect(signal.aborted).toBe(true)
  expect(await screen.findByText('Angehalten – die Antwort ist unvollständig.')).toBeTruthy()
})

test('navigation after start preserves the stream through done', async () => {
  const { router } = setup(); await send()
  await act(async () => { frame({ event: 'start', conversation_id: 'c', user_message_id: 'u' }) })
  await waitFor(() => expect(router.state.location.pathname).toBe('/chat/c'))
  expect(signal.aborted).toBe(false)
  await act(async () => { frame({ event: 'delta', text: 'Kommt noch' }); frame({ event: 'done', conversation_id: 'c', message_id: 'm', stopped: false }) })
  expect(await screen.findByText('Kommt noch', { selector: 'p' })).toBeTruthy()
  expect(document.querySelector('.sr-only[aria-live="polite"]')?.textContent).toBe('Kommt noch')
  await waitFor(() => expect(screen.getByRole('button', { name: 'Senden' })).toBeTruthy())
  expect(signal.aborted).toBe(false)
})

test('history replaces the live turn when the answer is persisted', async () => {
  const { client } = setup('/chat/c'); await send()
  await act(async () => { frame({ event: 'start', conversation_id: 'c', user_message_id: 'u' }); frame({ event: 'delta', text: 'Gespeichert' }); frame({ event: 'done', conversation_id: 'c', message_id: 'm', stopped: false }) })
  expect(await screen.findByText('Gespeichert', { selector: 'p' })).toBeTruthy()
  const message: ChatMessageOut = { id: 'm', conversation_id: 'c', role: 'assistant', content: 'Gespeichert', created_at: '', extras: {}, proposal: null, proposal_status: '', stopped: false, tool_name: '' }
  history = [message]
  act(() => { client.setQueryData(['history', 'c'], history) })
  await waitFor(() => expect(screen.queryByText('Meine Frage')).toBeNull())
  expect(screen.getAllByText('Gespeichert', { selector: 'p' })).toHaveLength(1)
})

test('composer scopes a request to the chosen account and clears the field', async () => {
  const { client } = setup('/chat/c')
  act(() => { client.setQueryData(['summary'], { ...summary, accounts: [{ id: 'a', display_name: 'Privat' }] }) })
  fireEvent.click(await screen.findByRole('button', { name: 'Alle Konten' }))
  fireEvent.click(screen.getByRole('menuitem', { name: 'Privat' }))
  await send()
  expect(requestBody.account_id).toBe('a')
  expect(requestBody.conversation_id).toBe('c')
  expect((screen.getByPlaceholderText('Frag etwas zu deinen Mails …') as HTMLTextAreaElement).value).toBe('')
})

test('history renders safe text, model, mail account and only the latest suggestions', async () => {
  const { client } = setup('/chat/c')
  spyOn(sdk, 'mailMessageGet').mockImplementation((async () => ({ data: { id: 'mail', account_id: 'a', color_index: 0, sender_name: 'Absender', subject: '<b>Betreff</b>', internal_date: null, deadline: null } })) as never)
  const row = (id: string, content: string, extras: ChatMessageOut['extras']): ChatMessageOut => ({ id, conversation_id: 'c', role: 'assistant', content, created_at: '', extras, proposal: null, proposal_status: '', stopped: false, tool_name: '' })
  await screen.findByPlaceholderText('Frag etwas zu deinen Mails …')
  await waitFor(() => expect(screen.queryByText('Unterhaltung wird geladen …')).toBeNull())
  act(() => {
    client.setQueryData(['summary'], { ...summary, accounts: [{ id: 'a', display_name: 'Privat' }] })
    client.setQueryData(['models'], [{ id: 'model', label: 'Modellname', description: '', is_default: true }])
    client.setQueryData(['history', 'c'], [row('old', 'Alt', { suggestions: ['Alte Frage'] }), row('new', 'Neu', { model: 'model', mails: ['mail'], suggestions: ['Weiter fragen'] })])
  })
  expect(await screen.findByText('<b>Betreff</b>')).toBeTruthy()
  expect(screen.getByText('Privat')).toBeTruthy()
  expect(screen.getByText('Modellname')).toBeTruthy()
  expect(screen.queryByText('Alte Frage')).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: 'Weiter fragen' }))
  expect(requestBody.text).toBe('Weiter fragen')
  expect(requestBody.conversation_id).toBe('c')
})

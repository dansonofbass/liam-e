import { afterEach, expect, mock, spyOn, test } from 'bun:test'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createMemoryHistory, createRootRoute, createRoute, createRouter, Outlet, RouterProvider } from '@tanstack/react-router'
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import * as sdk from '../api/generated/sdk.gen'
import type { ChatMessageOut, ConversationOut, MailSummaryOut } from '../api/generated/types.gen'
import { Route as StartRoute } from '../routes/_app/index'
import { Conversation, turnOrder } from './Conversation'
import { ChatSessionProvider } from './session'

const originalFetch = globalThis.fetch
const originalMatchMedia = window.matchMedia
let stream: ReadableStreamDefaultController<Uint8Array>
let signal: AbortSignal
let history: ChatMessageOut[] = []
let requestBody: Record<string, unknown>
let summary: MailSummaryOut = { accounts: [], unread_total: 0, newsletter_senders: 0, last_sync_at: null }
// A test can hold the account summary back to see the state while it loads.
let summaryGate: Promise<void> | null = null
function setup(path = '/', historyGone = false, selection: string | null = null) {
  history = []
  summary = { accounts: [{ id: 'a', display_name: 'Privat', email_address: 'ich@example.com', provider: 'gmail', color_index: 0, state: 'ok' } as MailSummaryOut['accounts'][number]], unread_total: 0, newsletter_senders: 0, last_sync_at: null }
  window.matchMedia = (() => ({ matches: true, addEventListener() {}, removeEventListener() {} })) as unknown as typeof window.matchMedia
  globalThis.fetch = ((_url: unknown, init: RequestInit) => { signal = init.signal!; requestBody = JSON.parse(String(init.body)) as Record<string, unknown>; return Promise.resolve(new Response(new ReadableStream({ start(c) { stream = c } }))) }) as typeof fetch
  spyOn(sdk, 'calendarSourcesList').mockResolvedValue({ data: [] } as never)
  spyOn(sdk, 'promptsList').mockImplementation((async () => ({ data: [] })) as never)
  spyOn(sdk, 'chatHistory').mockImplementation((async () => { if (historyGone) throw { detail: { code: 'conversation_not_found' } }; return { data: history } }) as never)
  spyOn(sdk, 'mailSummary').mockImplementation((async () => { await summaryGate; return { data: summary } }) as never)
  spyOn(sdk, 'chatModelsList').mockImplementation((async () => ({ data: [] })) as never)
  spyOn(sdk, 'chatConversationsList').mockImplementation((async () => ({ data: [{ id: 'c', title: 'Test', model: 'm1', version: 5, prompt_revision_id: null, account_scope_json: JSON.stringify({ account_ids: selection ? [selection] : ['a'], selection }), created_at: '', updated_at: '' }] })) as never)
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, retryDelay: 0 } } })
  const root = createRootRoute({ component: () => <QueryClientProvider client={client}><ChatSessionProvider><Outlet /></ChatSessionProvider></QueryClientProvider> })
  const start = createRoute({ getParentRoute: () => root, path: '/', component: StartRoute.options.component })
  const chat = createRoute({ getParentRoute: () => root, path: '/chat/$conversationId', component: function ChatRoute() { const { conversationId } = chat.useParams(); return <Conversation conversationId={conversationId} /> } })
  const mail = createRoute({ getParentRoute: () => root, path: '/mail/$messageId', component: () => <p>Mail</p> })
  const router = createRouter({ routeTree: root.addChildren([start, chat, mail]), history: createMemoryHistory({ initialEntries: [path] }) })
  render(<RouterProvider router={router} />)
  return { client, router }
}
function frame(value: object) { stream.enqueue(new TextEncoder().encode(`data: ${JSON.stringify(value)}\n\n`)) }
async function send() {
  const input = await screen.findByPlaceholderText('Frag etwas zu deinen Mails …')
  fireEvent.change(input, { target: { value: 'Meine Frage' } })
  fireEvent.click(screen.getByRole('button', { name: 'Senden' }))
}
afterEach(() => { cleanup(); mock.restore(); summaryGate = null; globalThis.fetch = originalFetch; window.matchMedia = originalMatchMedia })

// The task chip opens its menu; the choices are radio items, the chip names the current one.
const taskChoice = async (chip: string, choice: string) => {
  const trigger = await screen.findByRole('button', { name: chip })
  await waitFor(() => expect((trigger as HTMLButtonElement).disabled).toBe(false))
  fireEvent.click(trigger)
  fireEvent.click(await screen.findByRole('menuitemradio', { name: new RegExp(`^${choice}`) }))
}

test('account chat explicitly includes personal tasks without granting other accounts', async () => {
  setup('/chat/c', false, 'a')
  const trigger = await screen.findByRole('button', { name: 'Keine Aufgaben' })
  await waitFor(() => expect((trigger as HTMLButtonElement).disabled).toBe(false))
  fireEvent.click(trigger)
  const items = await screen.findAllByRole('menuitemradio')
  expect(items.map(item => item.querySelector('.le-menu-title')?.textContent)).toEqual(['Keine Aufgaben', 'Alle Aufgaben', 'Aufgaben dieses Kontos'])
  expect(items[1]!.textContent).toContain('persönliche Aufgaben ohne Konto- und Mailbezug')
  expect(items[0]!.getAttribute('aria-checked')).toBe('true')
  fireEvent.click(items[1]!)
  expect(await screen.findByRole('button', { name: 'Alle Aufgaben' })).toBeTruthy()
  await send()
  expect(requestBody.account_id).toBe('a')
  expect(requestBody.task_source).toBe('account_and_unlinked')
  expect(requestBody.task_source_account_id).toBe('a')
})

for (const choice of ['Aufgaben dieses Kontos', 'Alle Aufgaben']) test(`changing the mail account clears the explicit task choice: ${choice}`, async () => {
  setup()
  summary.accounts.push({ ...summary.accounts[0]!, id: 'b', display_name: 'Arbeit', email_address: 'work@example.org' })
  fireEvent.click(await screen.findByRole('button', { name: 'Alle Konten' }))
  fireEvent.click(screen.getByRole('menuitem', { name: 'Privat' }))
  await taskChoice('Keine Aufgaben', choice)
  expect(await screen.findByRole('button', { name: choice })).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: 'Privat' }))
  fireEvent.click(screen.getByRole('menuitem', { name: 'Arbeit' }))
  fireEvent.click(await screen.findByRole('button', { name: 'Keine Aufgaben' }))
  expect((await screen.findByRole('menuitemradio', { name: /^Keine Aufgaben/ })).getAttribute('aria-checked')).toBe('true')
  expect(screen.getByRole('menuitemradio', { name: /^Aufgaben dieses Kontos/ }).getAttribute('aria-checked')).toBe('false')
  fireEvent.keyDown(screen.getByRole('menu'), { key: 'Escape' })
  await send()
  expect(requestBody.account_id).toBe('b')
  expect(requestBody.task_source).toBe('none')
  expect(requestBody.task_source_account_id).toBeUndefined()
})

test('shows status, streams text and stops the answer', async () => {
  setup('/chat/c'); await send()
  await act(async () => { frame({ event: 'start', conversation_id: 'c', user_message_id: 'u' }); frame({ event: 'status', code: 'searching', count: 4 }) })
  expect((await screen.findByRole('status')).textContent).toBe('Durchsuche 4 Konten …')
  expect(screen.getByRole('button', { name: 'Anhalten' })).toBeTruthy()
  await act(async () => { frame({ event: 'delta', text: 'Eine Antwort' }) })
  expect(await screen.findByText('Eine Antwort')).toBeTruthy()
  expect(document.querySelector('.le-sr[aria-live="polite"]')?.textContent).toBe('')
  fireEvent.click(screen.getByRole('button', { name: 'Anhalten' }))
  expect(signal.aborted).toBe(true)
  expect(await screen.findByText('Angehalten – die Antwort ist unvollständig.')).toBeTruthy()
  expect(screen.getByRole('button', { name: 'Noch mal fragen' }).closest('.le-chat-retry')).toBeTruthy()
})

for (const phase of ['stopped', 'error'] as const) test(`saved partial answer is shown once after ${phase}`, async () => {
  const { client } = setup('/chat/c'); await send()
  await act(async () => { frame({ event: 'start', conversation_id: 'c', user_message_id: 'u' }); frame({ event: 'delta', text: 'Teilantwort' }) })
  expect(await screen.findByText('Teilantwort')).toBeTruthy()
  const row = (id: string, role: 'user' | 'assistant', content: string): ChatMessageOut => ({ id, conversation_id: 'c', role, content, created_at: '', extras: {}, proposal: null, proposal_status: '', stopped: role === 'assistant', tool_name: '' })
  history = [row('u', 'user', 'Meine Frage'), row('a', 'assistant', 'Teilantwort')]
  if (phase === 'stopped') fireEvent.click(screen.getByRole('button', { name: 'Anhalten' }))
  else await act(async () => { frame({ event: 'error', code: 'aborted' }) })
  await waitFor(() => expect(client.getQueryData(['history', 'c'])).toEqual(history))
  await waitFor(() => expect(screen.getAllByText('Teilantwort')).toHaveLength(1))
  expect(screen.getAllByText('Meine Frage')).toHaveLength(1)
  expect(screen.getByRole('button', { name: phase === 'stopped' ? 'Noch mal fragen' : 'Noch mal versuchen' })).toBeTruthy()
})

test('coarse pointer chat controls use the large touch target token', async () => {
  const css = await Bun.file(new URL('../styles/ds-app.css', import.meta.url)).text()
  const rule = css.match(/@media \(pointer: coarse\) \{ ([^{}]+)\{ ([^{}]+) \} \}/u)
  expect(rule).toBeTruthy()
  for (const selector of ['.le-chat-suggestions .le-chip', '.le-chat-header .le-menu-anchor .le-chip', '.le-chat-end .le-btn', '.le-chat-retry .le-btn', '.le-chat-reference .le-icon-btn']) expect(rule?.[1]).toContain(selector)
  expect(rule?.[2]).toContain('min-width: var(--control-height-lg)')
  expect(rule?.[2]).toContain('min-height: var(--control-height-lg)')
})

test('navigation after start preserves the stream through done', async () => {
  const { router } = setup(); await send()
  await act(async () => { frame({ event: 'start', conversation_id: 'c', user_message_id: 'u' }) })
  await waitFor(() => expect(router.state.location.pathname).toBe('/chat/c'))
  expect(signal.aborted).toBe(false)
  await act(async () => { frame({ event: 'delta', text: 'Kommt noch' }); frame({ event: 'done', conversation_id: 'c', message_id: 'm', stopped: false }) })
  expect(await screen.findByText('Kommt noch', { selector: 'p' })).toBeTruthy()
  const announcements = [...document.querySelectorAll('.le-chat-messages [aria-live]')].filter(element => element.textContent?.includes('Kommt noch'))
  expect(announcements).toHaveLength(1)
  expect(announcements[0]?.classList.contains('le-sr')).toBe(true)
  await waitFor(() => expect(screen.getByRole('button', { name: 'Senden' })).toBeTruthy())
  expect(signal.aborted).toBe(false)
})

test('account scope and composer focus survive navigation to the conversation', async () => {
  const { router } = setup()
  fireEvent.click(await screen.findByRole('button', { name: 'Alle Konten' }))
  fireEvent.click(screen.getByRole('menuitem', { name: 'Privat' }))
  await send()
  expect(requestBody.account_id).toBe('a')
  await act(async () => { frame({ event: 'start', conversation_id: 'c', user_message_id: 'u' }) })
  await waitFor(() => expect(router.state.location.pathname).toBe('/chat/c'))
  const input = await screen.findByPlaceholderText('Frag etwas zu deinen Mails …')
  expect(document.activeElement).toBe(input)
  await act(async () => { frame({ event: 'done', conversation_id: 'c', message_id: 'm', stopped: false }) })
  await waitFor(() => expect(screen.getByRole('button', { name: 'Senden' })).toBeTruthy())
  fireEvent.change(input, { target: { value: 'Noch eine Frage' } })
  fireEvent.click(screen.getByRole('button', { name: 'Senden' }))
  expect(requestBody.text).toBe('Noch eine Frage')
  expect(requestBody.account_id).toBe('a')
  expect(requestBody.conversation_id).toBe('c')
})

test('a live follow-up keeps the selected account and calendars after navigation', async () => {
  setup()
  spyOn(sdk, 'calendarSourcesList').mockResolvedValue({ data: [{ id: 'work', name: 'Arbeit', is_active: true }] } as never)
  fireEvent.click(await screen.findByRole('button', { name: 'Arbeit' }))
  fireEvent.click(await screen.findByRole('button', { name: 'Alle Konten' }))
  fireEvent.click(screen.getByRole('menuitem', { name: 'Privat' }))
  await send()
  await act(async () => { frame({ event: 'start', conversation_id: 'c', user_message_id: 'u' }); frame({ event: 'suggestions', items: ['Weiter fragen'] }); frame({ event: 'done', conversation_id: 'c', message_id: 'm', stopped: false }) })
  fireEvent.click(await screen.findByRole('button', { name: 'Weiter fragen' }))
  expect(requestBody.text).toBe('Weiter fragen')
  expect(requestBody.calendar_source_ids).toEqual(['work'])
  expect(requestBody.account_id).toBe('a')
  expect(requestBody.conversation_id).toBe('c')
})

test('a history suggestion after reload uses the saved account', async () => {
  const { client } = setup('/chat/c', false, 'a')
  await screen.findByRole('button', { name: 'Privat' })
  act(() => { client.setQueryData(['history', 'c'], [historyRow('answer', 'assistant', { suggestions: ['Weiter fragen'] })]) })
  fireEvent.click(await screen.findByRole('button', { name: 'Weiter fragen' }))
  expect(requestBody.account_id).toBe('a')
})

test('reload restores the saved account for the composer', async () => {
  setup('/chat/c', false, 'a')
  await screen.findByRole('button', { name: 'Privat' })
  await send()
  expect(requestBody.account_id).toBe('a')
})

test('the pencil on a mail card keeps the live calendar scope after navigation', async () => {
  setup()
  spyOn(sdk, 'calendarSourcesList').mockResolvedValue({ data: [{ id: 'work', name: 'Arbeit', is_active: true }] } as never)
  fireEvent.click(await screen.findByRole('button', { name: 'Arbeit' }))
  fireEvent.click(screen.getByRole('button', { name: 'Alle Konten' }))
  fireEvent.click(screen.getByRole('menuitem', { name: 'Privat' }))
  await send()
  await act(async () => { frame({ event: 'start', conversation_id: 'c', user_message_id: 'u' }); frame({ event: 'mails', mails: [{ id: 'mail1', account_id: 'a', color_index: 0, subject: 'Frist', sender_name: 'Anna', snippet: 'Einwände bis Freitag möglich', internal_date: null, deadline: null, is_flagged: true }] }); frame({ event: 'done', conversation_id: 'c', message_id: 'm', stopped: false }) })
  expect(await screen.findByRole('img', { name: 'Dringend' })).toBeTruthy()
  expect(screen.getByText('Einwände bis Freitag möglich').classList.contains('le-mailref-snippet')).toBe(true)
  fireEvent.click(screen.getByRole('button', { name: 'Antwort entwerfen' }))
  expect(requestBody).toMatchObject({ text: 'Entwirf eine Antwort auf diese Mail.', conversation_id: 'c', context_message_id: 'mail1', calendar_source_ids: ['work'] })
  expect(requestBody.account_id).toBe('a')
})

test('an answer shows at most three follow-up suggestions', async () => {
  setup('/chat/c'); await send()
  await act(async () => { frame({ event: 'start', conversation_id: 'c', user_message_id: 'u' }); frame({ event: 'suggestions', items: ['Eins', 'Zwei', 'Drei', 'Vier'] }); frame({ event: 'done', conversation_id: 'c', message_id: 'm', stopped: false }) })
  expect(await screen.findByRole('button', { name: 'Drei' })).toBeTruthy()
  expect(screen.queryByRole('button', { name: 'Vier' })).toBeNull()
  expect(document.querySelectorAll('.le-chat-suggestions .le-chip')).toHaveLength(3)
})

test('a follow-up suggestion without a selected account searches all accounts', async () => {
  setup('/chat/c'); await send()
  await act(async () => { frame({ event: 'start', conversation_id: 'c', user_message_id: 'u' }); frame({ event: 'suggestions', items: ['Weiter fragen'] }); frame({ event: 'done', conversation_id: 'c', message_id: 'm', stopped: false }) })
  fireEvent.click(await screen.findByRole('button', { name: 'Weiter fragen' }))
  expect(requestBody.text).toBe('Weiter fragen')
  expect(requestBody.account_id).toBeNull()
})

test('history user message is not duplicated while streaming after navigation', async () => {
  const { client, router } = setup(); await send()
  history = [{ id: 'u', conversation_id: 'c', role: 'user', content: 'Meine Frage', created_at: '', extras: {}, proposal: null, proposal_status: '', stopped: false, tool_name: '' }]
  await act(async () => { frame({ event: 'start', conversation_id: 'c', user_message_id: 'u' }); frame({ event: 'delta', text: 'Antwort' }) })
  await waitFor(() => expect(router.state.location.pathname).toBe('/chat/c'))
  expect(await screen.findByText('Antwort')).toBeTruthy()
  await waitFor(() => expect(client.getQueryData(['history', 'c'])).toEqual(history))
  expect(screen.getAllByText('Meine Frage')).toHaveLength(1)
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

test('selection survives the live proposal being replaced by history', async () => {
  const proposal: ChatMessageOut = { id: 'p', conversation_id: 'c', role: 'proposal', content: '', created_at: '', extras: {}, proposal_status: 'pending', stopped: false, tool_name: '', proposal: { kind: 'unsubscribe', reason: 'Nicht mehr gelesen.', items: [{ id: 'a', kind: 'sender', title: 'Alpha', subtitle: '', method: 'post' }, { id: 'b', kind: 'sender', title: 'Beta', subtitle: '', method: 'post' }] } }
  const answer: ChatMessageOut = { id: 'm', conversation_id: 'c', role: 'assistant', content: 'Fertig', created_at: '', extras: {}, proposal: null, proposal_status: '', stopped: false, tool_name: '' }
  const confirm = spyOn(sdk, 'chatProposalConfirm').mockImplementation((async () => ({ data: { ...proposal, proposal_status: 'done' } })) as never)
  const { client } = setup('/chat/c')
  await waitFor(() => expect(client.getQueryData(['history', 'c'])).toEqual([]))
  let resolveHistory!: (value: { data: ChatMessageOut[] }) => void
  spyOn(sdk, 'chatHistory').mockImplementation((() => new Promise(resolve => { resolveHistory = resolve })) as never)
  await send()
  await act(async () => { frame({ event: 'start', conversation_id: 'c', user_message_id: 'u' }); frame({ event: 'proposal', message: proposal }); frame({ event: 'done', conversation_id: 'c', message_id: 'm', stopped: false }) })
  fireEvent.click(await screen.findByRole('checkbox', { name: /Beta/ }))
  await waitFor(() => expect(resolveHistory).toBeDefined())
  await act(async () => { resolveHistory({ data: [answer, proposal] }) })
  await waitFor(() => expect(client.getQueryData(['history', 'c'])).toEqual([answer, proposal]))
  const beta = await screen.findByRole('checkbox', { name: /Beta/ })
  expect((beta as HTMLInputElement).checked).toBe(false)
  fireEvent.click(screen.getByRole('button', { name: '1 abbestellen und archivieren' }))
  await waitFor(() => expect(confirm).toHaveBeenCalledWith({ path: { proposal_id: 'p' }, body: { selected_ids: ['a'], body: undefined }, throwOnError: true }))
  // The confirmed card replaces its button with the result; without waiting for that the update lands after the test.
  await waitFor(() => expect(screen.queryByRole('button', { name: '1 abbestellen und archivieren' })).toBeNull())
})

test('composer account menu falls back to the address', async () => {
  const { client } = setup('/chat/c')
  await waitFor(() => expect(client.getQueryData(['summary'])).toBeTruthy())
  act(() => { client.setQueryData(['summary'], { ...summary, accounts: [{ id: 'a', display_name: '', email_address: 'ich@example.com', provider: 'gmail' }] }) })
  fireEvent.click(await screen.findByRole('button', { name: 'Alle Konten' }))
  fireEvent.click(await screen.findByRole('menuitem', { name: 'ich@example.com' }))
  expect(screen.getByRole('button', { name: 'ich@example.com' })).toBeTruthy()
})

test('composer scopes a request and clears the field only after acceptance', async () => {
  const { client } = setup('/chat/c')
  act(() => { client.setQueryData(['summary'], { ...summary, accounts: [{ id: 'a', display_name: 'Privat' }] }) })
  fireEvent.click(await screen.findByRole('button', { name: 'Alle Konten' }))
  fireEvent.click(screen.getByRole('menuitem', { name: 'Privat' }))
  await send()
  expect(requestBody.account_id).toBe('a')
  expect(requestBody.conversation_id).toBe('c')
  expect((screen.getByPlaceholderText('Frag etwas zu deinen Mails …') as HTMLTextAreaElement).value).toBe('Meine Frage')
  await act(async () => { frame({ event: 'start', conversation_id: 'c', user_message_id: 'u' }) })
  expect((screen.getByPlaceholderText('Frag etwas zu deinen Mails …') as HTMLTextAreaElement).value).toBe('')
})

test('does not follow new text after scrolling up; button resumes following', async () => {
  setup('/chat/c'); await send()
  await act(async () => { frame({ event: 'start', conversation_id: 'c', user_message_id: 'u' }) })
  const container = document.querySelector('.le-chat-messages') as HTMLElement
  Object.defineProperty(container, 'scrollHeight', { configurable: true, value: 1000 })
  Object.defineProperty(container, 'clientHeight', { configurable: true, value: 200 })
  Object.defineProperty(container, 'scrollTop', { configurable: true, writable: true, value: 100 })
  fireEvent.scroll(container)
  await act(async () => { frame({ event: 'delta', text: 'Neuer Text' }) })
  expect(container.scrollTop).toBe(100)
  fireEvent.click(screen.getByRole('button', { name: 'Zum Ende' }))
  expect(container.scrollTop).toBe(1000)
  expect(screen.queryByRole('button', { name: 'Zum Ende' })).toBeNull()
})

test('missing conversation in history offers a new conversation', async () => {
  const { router } = setup('/chat/c', true)
  const notice = (await screen.findByText('Diese Unterhaltung gibt es nicht mehr. Starte eine neue Unterhaltung.')).closest('[role="alert"]') as HTMLElement
  expect(within(notice).queryByRole('button', { name: 'Noch mal versuchen' })).toBeNull()
  fireEvent.click(within(notice).getByRole('button', { name: 'Neue Unterhaltung' }))
  await waitFor(() => expect(router.state.location.pathname).toBe('/'))
})

test('missing conversation in a stream offers a new conversation', async () => {
  const { router } = setup('/chat/c')
  globalThis.fetch = (() => Promise.resolve(new Response(JSON.stringify({ detail: { code: 'conversation_not_found' } }), { status: 404 }))) as unknown as typeof fetch
  await send()
  const notice = (await screen.findByText('Diese Unterhaltung gibt es nicht mehr. Starte eine neue Unterhaltung.')).closest('[role="alert"]') as HTMLElement
  expect(within(notice).queryByRole('button', { name: 'Noch mal versuchen' })).toBeNull()
  fireEvent.click(within(notice).getByRole('button', { name: 'Neue Unterhaltung' }))
  await waitFor(() => expect(router.state.location.pathname).toBe('/'))
})

for (const path of ['/', '/chat/c']) test(`invalid context names both account and calendar selection on ${path}`, async () => {
  setup(path)
  globalThis.fetch = (() => Promise.resolve(Response.json({ detail: { code: 'context_invalid' } }, { status: 422 }))) as unknown as typeof fetch
  await send()
  const notice = (await screen.findByText('Ein Konto oder Kalender aus deiner Auswahl ist nicht verfügbar. Prüfe deine Auswahl und versuch es noch mal.')).closest('[role="alert"]') as HTMLElement
  expect(within(notice).getByRole('button', { name: 'Noch mal versuchen' })).toBeTruthy()
  expect(within(notice).queryByRole('button', { name: 'Neue Unterhaltung' })).toBeNull()
})

test('account change in a conversation offers a new conversation instead of a retry', async () => {
  const { router } = setup('/chat/c', false, 'a')
  fireEvent.click(await screen.findByRole('button', { name: 'Privat' }))
  fireEvent.click(screen.getByRole('menuitem', { name: 'Alle Konten' }))
  globalThis.fetch = (() => Promise.resolve(new Response(JSON.stringify({ detail: { code: 'conversation_scope_change_requires_new' } }), { status: 409 }))) as unknown as typeof fetch
  await send()
  const notice = (await screen.findByText(/Für andere Konten, Kalender oder Aufgaben/)).closest('[role="alert"]') as HTMLElement
  expect(within(notice).queryByRole('button', { name: 'Noch mal versuchen' })).toBeNull()
  fireEvent.click(within(notice).getByRole('button', { name: 'Neue Unterhaltung' }))
  await waitFor(() => expect(router.state.location.pathname).toBe('/'))
  expect((await screen.findByPlaceholderText('Frag etwas zu deinen Mails …') as HTMLTextAreaElement).value).toBe('Meine Frage')
  expect(screen.getByRole('button', { name: 'Alle Konten' })).toBeTruthy()
})

test('in a conversation the other task choices say they need a new conversation', async () => {
  setup('/chat/c')
  const trigger = await screen.findByRole('button', { name: 'Keine Aufgaben' })
  await waitFor(() => expect((trigger as HTMLButtonElement).disabled).toBe(false))
  fireEvent.click(trigger)
  const items = await screen.findAllByRole('menuitemradio')
  expect(items[0]!.textContent).not.toContain('Braucht eine neue Unterhaltung.')
  for (const item of items.slice(1)) expect(item.textContent).toContain('Braucht eine neue Unterhaltung.')
})

test('a restored task choice the list cannot offer still names itself', async () => {
  const { client } = setup('/chat/c')
  const trigger = await screen.findByRole('button', { name: 'Keine Aufgaben' })
  await waitFor(() => expect((trigger as HTMLButtonElement).disabled).toBe(false))
  const context = { id: 'ctx', account_scope_json: '{}', app_prompt_version: '1', preference_revision_id: null, prompt_hash: null, prompt_revision_id: null, revoked: false, task_scope_json: JSON.stringify({ source: 'account', account_id: 'gone' }) } as ChatMessageOut['context']
  act(() => { client.setQueryData(['history', 'c'], [{ ...historyRow('a1', 'assistant'), context }]) })
  expect(await screen.findByRole('button', { name: 'Aufgaben: Gespeichertes Konto nicht verfügbar' })).toBeTruthy()
  expect(screen.queryByRole('button', { name: 'Keine Aufgaben' })).toBeNull()
})

const restoredContext = (scope: object) => ({ id: 'ctx', account_scope_json: '{}', app_prompt_version: '1', preference_revision_id: null, prompt_hash: null, prompt_revision_id: null, revoked: false, task_scope_json: JSON.stringify(scope) }) as ChatMessageOut['context']

test('a restored task choice never repeats an offered label', async () => {
  const { client } = setup('/chat/c', false, 'a')
  const trigger = await screen.findByRole('button', { name: 'Keine Aufgaben' })
  await waitFor(() => expect((trigger as HTMLButtonElement).disabled).toBe(false))
  act(() => { client.setQueryData(['history', 'c'], [{ ...historyRow('a1', 'assistant'), context: restoredContext({ source: 'all' }) }]) })
  fireEvent.click(await screen.findByRole('button', { name: 'Gespeichert: Alle Aufgaben' }))
  const names = (await screen.findAllByRole('menuitemradio')).map(item => item.querySelector('.le-menu-title')?.textContent)
  expect(names).toEqual(['Keine Aufgaben', 'Alle Aufgaben', 'Aufgaben dieses Kontos', 'Gespeichert: Alle Aufgaben'])
})

test('a restored account-and-personal choice without a mail account is marked as saved', async () => {
  const { client } = setup('/chat/c')
  const trigger = await screen.findByRole('button', { name: 'Keine Aufgaben' })
  await waitFor(() => expect((trigger as HTMLButtonElement).disabled).toBe(false))
  act(() => { client.setQueryData(['history', 'c'], [{ ...historyRow('a1', 'assistant'), context: restoredContext({ source: 'account_and_unlinked', account_id: 'a' }) }]) })
  fireEvent.click(await screen.findByRole('button', { name: 'Gespeichert: Alle Aufgaben' }))
  const names = (await screen.findAllByRole('menuitemradio')).map(item => item.querySelector('.le-menu-title')?.textContent)
  expect(new Set(names).size).toBe(names.length)
})

test('a restored account the menu does not offer shows its listed name', async () => {
  const { client } = setup('/chat/c', false, 'a')
  summary.accounts.push({ ...summary.accounts[0]!, id: 'b', display_name: 'Arbeit', email_address: 'work@example.org' })
  const trigger = await screen.findByRole('button', { name: 'Keine Aufgaben' })
  await waitFor(() => expect((trigger as HTMLButtonElement).disabled).toBe(false))
  act(() => { client.setQueryData(['history', 'c'], [{ ...historyRow('a1', 'assistant'), context: restoredContext({ source: 'account', account_id: 'b' }) }]) })
  expect(await screen.findByRole('button', { name: 'Aufgaben: Arbeit' })).toBeTruthy()
})

test('a restored account choice waits for the account list before calling the account unavailable', async () => {
  let release = () => {}
  summaryGate = new Promise<void>(resolve => { release = resolve })
  const { client } = setup('/chat/c')
  const trigger = await screen.findByRole('button', { name: 'Keine Aufgaben' })
  await waitFor(() => expect((trigger as HTMLButtonElement).disabled).toBe(false))
  act(() => { client.setQueryData(['history', 'c'], [{ ...historyRow('a1', 'assistant'), context: restoredContext({ source: 'account', account_id: 'gone' }) }]) })
  expect(await screen.findByRole('button', { name: 'Aufgaben: …' })).toBeTruthy()
  expect(screen.queryByRole('button', { name: /nicht verfügbar/ })).toBeNull()
  await act(async () => { release() })
  expect(await screen.findByRole('button', { name: 'Aufgaben: Gespeichertes Konto nicht verfügbar' })).toBeTruthy()
})

test('task selection conflict restarts visibly without the old conversation', async () => {
  const { router } = setup('/chat/c')
  await taskChoice('Keine Aufgaben', 'Alle Aufgaben')
  globalThis.fetch = ((_url: unknown, init: RequestInit) => {
    requestBody = JSON.parse(String(init.body))
    return Promise.resolve(Response.json({ detail: { code: 'conversation_scope_change_requires_new' } }, { status: 409 }))
  }) as typeof fetch
  await send()
  const notice = (await screen.findByText(/Für andere Konten, Kalender oder Aufgaben/)).closest('[role="alert"]') as HTMLElement
  expect(requestBody.task_source).toBe('all')
  fireEvent.click(within(notice).getByRole('button', { name: 'Neue Unterhaltung' }))
  await waitFor(() => expect(router.state.location.pathname).toBe('/'))
  expect(await screen.findByRole('button', { name: 'Alle Aufgaben' })).toBeTruthy()
  await send()
  await waitFor(() => expect(requestBody.conversation_id).toBeUndefined())
  expect(requestBody.task_source).toBe('all')
  expect(requestBody.text).toBe('Meine Frage')
  expect(requestBody.history).toBeUndefined()
})

test('calendar selection is separate from mail and survives a scope-conflict restart', async () => {
  const { client, router } = setup('/chat/c', false, 'a')
  await screen.findByRole('button', { name: 'Privat' })
  const sources = [{ id: 'work', name: 'Arbeitskalender', provider: 'google', is_active: true }]
  spyOn(sdk, 'calendarSourcesList').mockResolvedValue({ data: sources } as never)
  act(() => client.setQueryData(['calendar', 'sources'], sources))
  fireEvent.click(await screen.findByRole('button', { name: 'Arbeitskalender' }))
  globalThis.fetch = ((_url: unknown, init: RequestInit) => {
    requestBody = JSON.parse(String(init.body))
    return Promise.resolve(Response.json({ detail: { code: 'conversation_scope_change_requires_new' } }, { status: 409 }))
  }) as typeof fetch
  await send()
  const notice = (await screen.findByText(/Für andere Konten, Kalender oder Aufgaben/)).closest('[role="alert"]') as HTMLElement
  expect(requestBody.calendar_source_ids).toEqual(['work'])
  expect(requestBody.account_id).toBe('a')
  fireEvent.click(within(notice).getByRole('button', { name: 'Neue Unterhaltung' }))
  await waitFor(() => expect(router.state.location.pathname).toBe('/'))
  expect((await screen.findByRole('button', { name: 'Arbeitskalender' })).getAttribute('aria-pressed')).toBe('true')
  expect(screen.getByRole('button', { name: 'Privat' })).toBeTruthy()
})

test('revoked context during an answer offers a fresh conversation', async () => {
  setup('/chat/c')
  const frames = ['event: start\ndata: {"event":"start","conversation_id":"c","user_message_id":"u"}\n\n', 'event: error\ndata: {"event":"error","code":"context_revoked"}\n\n']
  globalThis.fetch = (() => Promise.resolve(new Response(frames.join(''), { status: 200, headers: { 'Content-Type': 'text/event-stream' } }))) as unknown as typeof fetch
  await send()
  const notice = (await screen.findByText(/Die Vorlage, Präferenzen oder die Auswahl von Konten, Kalendern oder Aufgaben sind nicht mehr gültig/)).closest('[role="alert"]') as HTMLElement
  expect(within(notice).getByRole('button', { name: 'Neue Unterhaltung' })).toBeTruthy()
})

test('a conversation renders both header menus without a duplicate key', async () => {
  const error = spyOn(console, 'error').mockImplementation(() => {})
  setup('/chat/c')
  await screen.findByPlaceholderText('Frag etwas zu deinen Mails …')
  const duplicate = error.mock.calls.filter(call => call.some(part => typeof part === 'string' && part.includes('same key')))
  expect(duplicate).toEqual([])
})

test('model selection errors do not follow a conversation switch', async () => {
  spyOn(sdk, 'chatConversationUpdate').mockImplementation((async () => { throw { detail: { code: 'model_unknown' } } }) as never)
  const { client, router } = setup('/chat/c')
  await screen.findByPlaceholderText('Frag etwas zu deinen Mails …')
  act(() => { client.setQueryData(['models'], [{ id: 'm1', label: 'Modell Eins', is_default: true }, { id: 'm2', label: 'Modell Zwei', is_default: false }]) })
  fireEvent.click(await screen.findByRole('button', { name: /Modell Eins/ }))
  fireEvent.click(screen.getByRole('menuitem', { name: /Modell Zwei/ }))
  expect(await screen.findByText('Dieses Modell gibt es nicht mehr. Wähle ein anderes.')).toBeTruthy()
  await act(async () => { await router.navigate({ to: '/chat/$conversationId', params: { conversationId: 'b' } }) })
  expect(screen.queryByText('Dieses Modell gibt es nicht mehr. Wähle ein anderes.')).toBeNull()
})

test('template selection errors do not follow a conversation switch', async () => {
  spyOn(sdk, 'chatConversationUpdate').mockImplementation((async () => { throw { detail: { code: 'version_conflict' } } }) as never)
  const { client, router } = setup('/chat/c')
  await waitFor(() => expect(client.getQueryData(['conversations'])).toBeTruthy())
  await waitFor(() => expect((screen.getByRole('button', { name: 'Vorlage: Standard' }) as HTMLButtonElement).disabled).toBe(false))
  const saved = client.getQueryData<Record<string, unknown>[]>(['conversations'])![0]!
  act(() => { client.setQueryData(['conversations'], [saved, { ...saved, id: 'b' }]) })
  fireEvent.click(screen.getByRole('button', { name: 'Vorlage: Standard' }))
  fireEvent.click(screen.getByRole('menuitemradio', { name: 'Standard' }))
  await screen.findByRole('button', { name: 'Aktuelle Fassung laden' })
  await act(async () => { await router.navigate({ to: '/chat/$conversationId', params: { conversationId: 'b' } }) })
  expect(screen.queryByRole('button', { name: 'Aktuelle Fassung laden' })).toBeNull()
})

test('restart after template removal preserves account and unsent text', async () => {
  const { client, router } = setup('/chat/c', false, 'a')
  await screen.findByRole('button', { name: 'Privat' })
  const saved = client.getQueryData<Record<string, unknown>[]>(['conversations'])![0]!
  act(() => { client.setQueryData(['conversations'], [{ ...saved, prompt_revision_id: 'removed' }]) })
  const input = screen.getByPlaceholderText('Frag etwas zu deinen Mails …')
  fireEvent.change(input, { target: { value: 'Noch offen' } })
  fireEvent.click(await screen.findByRole('button', { name: 'Neue Unterhaltung ohne bisherigen Kontext' }))
  await waitFor(() => expect(router.state.location.pathname).toBe('/'))
  expect(await screen.findByRole('button', { name: 'Privat' })).toBeTruthy()
  expect((screen.getByPlaceholderText('Frag etwas zu deinen Mails …') as HTMLTextAreaElement).value).toBe('Noch offen')
})

test('restart from a revoked answer preserves account and unsent text', async () => {
  const { client, router } = setup('/chat/c', false, 'a')
  await screen.findByRole('button', { name: 'Privat' })
  await waitFor(() => expect(client.getQueryData(['history', 'c'])).toEqual([]))
  act(() => { client.setQueryData(['history', 'c'], [{ ...historyRow('revoked', 'assistant'), context: { id: 'ctx', account_scope_json: '{}', app_prompt_version: '1', preference_revision_id: null, prompt_hash: null, prompt_revision_id: null, revoked: true } }]) })
  fireEvent.change(screen.getByPlaceholderText('Frag etwas zu deinen Mails …'), { target: { value: 'Noch offen' } })
  fireEvent.click(await screen.findByRole('button', { name: 'Neue Unterhaltung ohne bisherigen Kontext' }))
  await waitFor(() => expect(router.state.location.pathname).toBe('/'))
  expect(await screen.findByRole('button', { name: 'Privat' })).toBeTruthy()
  expect((screen.getByPlaceholderText('Frag etwas zu deinen Mails …') as HTMLTextAreaElement).value).toBe('Noch offen')
})

test('unknown model refusal renders its explanation', async () => {
  spyOn(sdk, 'chatConversationUpdate').mockImplementation((async () => { throw { detail: { code: 'model_unknown' } } }) as never)
  const { client } = setup('/chat/c')
  await screen.findByPlaceholderText('Frag etwas zu deinen Mails …')
  act(() => { client.setQueryData(['models'], [{ id: 'm1', label: 'Modell Eins', is_default: true }, { id: 'm2', label: 'Modell Zwei', is_default: false }]) })
  fireEvent.click(await screen.findByRole('button', { name: /Modell Eins/ }))
  fireEvent.click(screen.getByRole('menuitem', { name: /Modell Zwei/ }))
  expect(await screen.findByText('Dieses Modell gibt es nicht mehr. Wähle ein anderes.')).toBeTruthy()
  expect(screen.getByRole('button', { name: 'Modell Eins' })).toBeTruthy()
})

const modelChoices = [
  { id: 'm1', label: 'Modell Eins', description: 'Schnell', is_default: true },
  { id: 'm2', label: 'Modell Zwei', description: 'Genau', is_default: false },
]

test('the saved model survives switching conversations and a fresh page with an older answer', async () => {
  let saved: ConversationOut = { id: 'c', title: 'Test', model: 'm1', version: 5, prompt_revision_id: null, account_scope_json: null, created_at: '', updated_at: '' }
  function openPage() {
    const { router } = setup('/chat/c')
    history = [historyRow('old', 'assistant', { model: 'm1' })]
    spyOn(sdk, 'chatHistory').mockImplementation(async options => ({ data: options.query.conversation_id === 'c' ? history : [] }) as never)
    spyOn(sdk, 'chatModelsList').mockResolvedValue({ data: modelChoices } as never)
    spyOn(sdk, 'chatConversationsList').mockImplementation(async () => ({ data: [saved, { ...saved, id: 'other', model: 'retired-model' }] }) as never)
    return router
  }
  openPage()
  const update = spyOn(sdk, 'chatConversationUpdate').mockImplementation(async () => {
    saved = { ...saved, model: 'm2', version: 6 }
    return { data: saved } as never
  })
  fireEvent.click(await screen.findByRole('button', { name: /Modell Eins/ }))
  fireEvent.click(screen.getByRole('menuitem', { name: /Modell Zwei · Genau/ }))
  await waitFor(() => expect(update).toHaveBeenCalledWith({ path: { conversation_id: 'c' }, body: { model: 'm2', expected_version: 5 }, throwOnError: true }))
  expect(await screen.findByRole('button', { name: 'Modell Zwei' })).toBeTruthy()
  cleanup()
  const router = openPage()
  expect(await screen.findByRole('button', { name: 'Modell Zwei' })).toBeTruthy()
  await screen.findByText('Antwort old')
  expect(document.querySelector('.le-msg-ai small')?.textContent).toBe('Modell Eins')
  await act(async () => { await router.navigate({ to: '/chat/$conversationId', params: { conversationId: 'other' } }) })
  expect(await screen.findByRole('button', { name: 'retired-model' })).toBeTruthy()
  await act(async () => { await router.navigate({ to: '/chat/$conversationId', params: { conversationId: 'c' } }) })
  expect(await screen.findByRole('button', { name: 'Modell Zwei' })).toBeTruthy()
})

test('a live answer keeps the model announced by the server when the saved choice changes', async () => {
  const { client } = setup('/chat/c')
  spyOn(sdk, 'chatModelsList').mockResolvedValue({ data: modelChoices } as never)
  await send()
  await act(async () => {
    frame({ event: 'start', conversation_id: 'c', user_message_id: 'u', model: 'm2' })
    frame({ event: 'delta', text: 'Laufende Antwort' })
  })
  await screen.findByText('Laufende Antwort')
  expect(document.querySelector('.le-msg-ai small')?.textContent).toBe('Modell Zwei')
  act(() => { client.setQueryData<ConversationOut[]>(['conversations'], rows => rows?.map(row => ({ ...row, model: 'next-model', version: row.version + 1 }))) })
  const chip = await screen.findByRole('button', { name: 'next-model' })
  expect((chip as HTMLButtonElement).disabled).toBe(true)
  expect(document.querySelector('.le-msg-ai small')?.textContent).toBe('Modell Zwei')
})

test('a stream without model metadata shows the answer without guessing a model', async () => {
  setup('/chat/c')
  spyOn(sdk, 'chatModelsList').mockResolvedValue({ data: modelChoices } as never)
  await send()
  await act(async () => {
    frame({ event: 'start', conversation_id: 'c', user_message_id: 'u' })
    frame({ event: 'delta', text: 'Text aus einem älteren Stream' })
  })
  await screen.findByText('Text aus einem älteren Stream')
  expect(document.querySelector('.le-msg-ai small')?.textContent).toBeUndefined()
})

test('a model conflict reloads the conversation and only an explicit retry uses its new version', async () => {
  const { client } = setup('/chat/c')
  let reads = 0
  const refreshed = { id: 'c', title: 'Test', model: 'm3', version: 6, prompt_revision_id: null, account_scope_json: null, created_at: '', updated_at: '' }
  let saved = { ...refreshed, model: 'm1', version: 5 }
  spyOn(sdk, 'chatConversationsList').mockImplementation(async () => { reads++; return { data: [saved] } as never })
  const update = spyOn(sdk, 'chatConversationUpdate').mockImplementationOnce(async () => { saved = refreshed; throw { detail: { code: 'version_conflict' }, status: 409 } })
    .mockImplementation(async () => { saved = { ...refreshed, model: 'm2', version: 7 }; return { data: saved } as never })
  await screen.findByPlaceholderText('Frag etwas zu deinen Mails …')
  act(() => { client.setQueryData(['models'], [{ id: 'm1', label: 'Modell Eins', is_default: true }, { id: 'm2', label: 'Modell Zwei' }, { id: 'm3', label: 'Modell Drei' }]) })
  fireEvent.click(await screen.findByRole('button', { name: /Modell Eins/ }))
  fireEvent.click(screen.getByRole('menuitem', { name: /Modell Zwei/ }))
  expect(await screen.findByText('Die Unterhaltung wurde inzwischen geändert. Der aktuelle Stand ist geladen. Prüfe das Modell und wähle bei Bedarf erneut.')).toBeTruthy()
  expect(client.getQueryData(['conversations'])).toEqual([refreshed])
  expect(update).toHaveBeenCalledTimes(1)
  expect(reads).toBeGreaterThanOrEqual(2)
  expect(update).toHaveBeenCalledWith({ path: { conversation_id: 'c' }, body: { model: 'm2', expected_version: 5 }, throwOnError: true })
  fireEvent.click(await screen.findByRole('button', { name: /Modell Drei/ }))
  fireEvent.click(screen.getByRole('menuitem', { name: /Modell Zwei/ }))
  await waitFor(() => expect(update).toHaveBeenLastCalledWith({ path: { conversation_id: 'c' }, body: { model: 'm2', expected_version: 6 }, throwOnError: true }))
  expect(await screen.findByRole('button', { name: /Modell Zwei/ })).toBeTruthy()
})

test('a missing history mail reference is requested only once', async () => {
  const get = spyOn(sdk, 'mailMessageGet').mockImplementation((async () => ({ response: new Response(null, { status: 404 }) })) as never)
  const { client } = setup('/chat/c')
  await waitFor(() => expect(client.getQueryData(['history', 'c'])).toEqual([]))
  const row: ChatMessageOut = { id: 'm', conversation_id: 'c', role: 'assistant', content: 'Antwort', created_at: '', extras: { mails: ['missing'] }, proposal: null, proposal_status: '', stopped: false, tool_name: '' }
  act(() => { client.setQueryData(['history', 'c'], [row]) })
  await waitFor(() => expect(client.getQueryState(['message', 'missing'])?.status).toBe('error'))
  expect(client.getQueryState(['message', 'missing'])?.fetchFailureCount).toBe(1)
  expect(get).toHaveBeenCalledTimes(1)
})

test('history renders safe text, model, mail account and only the latest suggestions', async () => {
  const { client, router } = setup('/chat/c')
  spyOn(sdk, 'mailMessageGet').mockImplementation((async () => ({ data: { id: 'mail', account_id: 'a', color_index: 0, sender_name: 'Absender', subject: '<b>Betreff</b>', internal_date: null, deadline: null, is_flagged: true } })) as never)
  const row =(id: string, content: string, extras: ChatMessageOut['extras']): ChatMessageOut => ({ id, conversation_id: 'c', role: 'assistant', content, created_at: '', extras, proposal: null, proposal_status: '', stopped: false, tool_name: '' })
  await screen.findByPlaceholderText('Frag etwas zu deinen Mails …')
  await waitFor(() => expect(screen.queryByText('Unterhaltung wird geladen …')).toBeNull())
  act(() => {
    client.setQueryData(['summary'], { ...summary, accounts: [{ id: 'a', display_name: '', email_address: 'ich@example.com', provider: 'gmail' }] })
    client.setQueryData(['models'], [{ id: 'model', label: 'Modellname', description: '', is_default: true }])
    client.setQueryData(['history', 'c'], [row('old', 'Alt', { suggestions: ['Alte Frage'] }), row('new', 'Neu', { model: 'model', mails: ['mail'], suggestions: ['Weiter fragen'] })])
  })
  expect(await screen.findByText('<b>Betreff</b>')).toBeTruthy()
  expect(screen.getByText('Gmail')).toBeTruthy()
  expect(screen.getByRole('img', { name: 'Dringend' })).toBeTruthy()
  expect(screen.getByRole('button', { name: 'Antwort entwerfen' })).toBeTruthy()
  expect(document.querySelector('.le-msg-ai small')?.textContent).toBe('Modellname')
  expect(screen.getByRole('button', { name: 'm1' })).toBeTruthy()
  expect(screen.queryByText('Alte Frage')).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: 'Weiter fragen' }))
  expect(requestBody.text).toBe('Weiter fragen')
  expect(requestBody.conversation_id).toBe('c')
  fireEvent.click(screen.getByRole('button', { name: 'Mail öffnen' }))
  await waitFor(() => expect(router.state.location.pathname).toBe('/mail/mail'))
})

const historyRow = (id: string, role: string, extras: ChatMessageOut['extras'] = {}): ChatMessageOut => ({ id, conversation_id: 'c', role, content: role === 'assistant' ? `Antwort ${id}` : role === 'user' ? `Frage ${id}` : '', created_at: '', extras, proposal: role === 'proposal' ? { kind: 'archive', reason: 'Erledigt.', items: [{ id: 'm', kind: 'mail', title: 'Rechnung', subtitle: 'Anna' }] } : null, proposal_status: role === 'proposal' ? 'pending' : '', stopped: false, tool_name: '' })

test('turn order puts a proposal after the answer of its turn', () => {
  const rows = ['u1:user', 'p1:proposal', 'a1:assistant', 'u2:user', 'a2:assistant', 'u3:user', 'p3:proposal'].map(entry => { const [id, role] = entry.split(':') as [string, string]; return historyRow(id, role) })
  expect(turnOrder(rows).map(row => row.id)).toEqual(['u1', 'a1', 'p1', 'u2', 'a2', 'u3', 'p3'])
  expect(turnOrder([])).toEqual([])
})

test('history shows answer, card and follow-ups in the same order as live', async () => {
  const { client } = setup('/chat/c')
  await screen.findByPlaceholderText('Frag etwas zu deinen Mails …')
  await waitFor(() => expect(screen.queryByText('Unterhaltung wird geladen …')).toBeNull())
  act(() => { client.setQueryData(['history', 'c'], [historyRow('u', 'user'), historyRow('p', 'proposal'), historyRow('a', 'assistant', { suggestions: ['Weiter fragen'] })]) })
  const answer = await screen.findByText('Antwort a')
  const card = screen.getByText('1 Mail archivieren?')
  const chip = screen.getByRole('button', { name: 'Weiter fragen' })
  expect(answer.compareDocumentPosition(card) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  expect(card.compareDocumentPosition(chip) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  expect(screen.getAllByRole('button', { name: 'Weiter fragen' })).toHaveLength(1)
})

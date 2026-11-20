import { afterEach, expect, mock, spyOn, test } from 'bun:test'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createMemoryHistory, createRootRoute, createRoute, createRouter, Outlet, RouterProvider } from '@tanstack/react-router'
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { useState } from 'react'
import * as sdk from '../api/generated/sdk.gen'
import { de } from '../i18n/de'
import { MobileHeader } from '../shell/MobileHeader'
import { ChatSessionProvider, useChatSession, useRestartConversation } from './session'

const originalFetch = globalThis.fetch, originalMatchMedia = window.matchMedia
let controller: ReadableStreamDefaultController<Uint8Array>, signal: AbortSignal
function clientWithGrants() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } })
  client.setQueryData(['summary', 'chat'], { accounts: [{ id: 'a' }], mail_scope_version: 3 })
  return client
}
function setup() {
  window.matchMedia = (() => ({ matches: true })) as unknown as typeof window.matchMedia
  globalThis.fetch = ((_url: unknown, init: RequestInit) => { signal = init.signal!; return Promise.resolve(new Response(new ReadableStream({ start(c) { controller = c } }))) }) as typeof fetch
  function Consumer() {
    const { state, send, stop } = useChatSession()
    return <><button onClick={() => void send({ text: 'Hi' })}>send</button><button onClick={stop}>stop</button><div data-testid="phase">{state.phase}</div><div data-testid="text">{state.text}</div><div data-testid="mails">{state.mails.length}</div>{state.phase === 'stopped' && de.chat.stopped}{state.errorCode && de.errors[state.errorCode]}</>
  }
  render(<QueryClientProvider client={clientWithGrants()}><ChatSessionProvider><Consumer /></ChatSessionProvider></QueryClientProvider>)
  fireEvent.click(screen.getByText('send'))
}
function frame(value: object) { controller.enqueue(new TextEncoder().encode(`data: ${JSON.stringify(value)}\n\n`)) }
afterEach(() => { cleanup(); mock.restore(); globalThis.fetch = originalFetch; window.matchMedia = originalMatchMedia })
test('buffers cards until done and text', async () => {
  setup(); await act(async () => { frame({ event: 'start', conversation_id: 'c' }); frame({ event: 'delta', text: 'Hallo' }); frame({ event: 'mails', mails: [{}] }) })
  expect(screen.getByTestId('text').textContent).toBe('Hallo'); expect(screen.getByTestId('mails').textContent).toBe('0')
  await act(async () => { frame({ event: 'done', conversation_id: 'c', message_id: 'm', stopped: false }) })
  await waitFor(() => expect(screen.getByTestId('phase').textContent).toBe('done'))
  expect(screen.getByTestId('mails').textContent).toBe('1')
})
test('stop aborts and displays notice', async () => { setup(); await act(async () => { frame({ event: 'delta', text: 'Hallo' }) }); fireEvent.click(screen.getByText('stop')); expect(signal.aborted).toBe(true); expect(screen.getByText(de.chat.stopped)).toBeTruthy(); expect(screen.getByTestId('phase').textContent).toBe('stopped') })
test('network break reports aborted', async () => { setup(); await act(async () => { frame({ event: 'delta', text: 'Hallo' }) }); await act(async () => { controller.error(new TypeError('network')) }); await waitFor(() => expect(screen.getByText(de.errors.aborted)).toBeTruthy()); expect(screen.getByTestId('phase').textContent).toBe('error') })

test('preference failure never silently retries; explicit continuation sets only this request flag', async () => {
  const bodies: Record<string, unknown>[] = []
  globalThis.fetch = (async (_url: unknown, init: RequestInit) => {
    bodies.push(JSON.parse(init.body as string))
    return Response.json({ detail: { code: 'preferences_unavailable' } }, { status: 503 })
  }) as typeof fetch
  function Consumer() {
    const { state, send, retryWithoutPreferences } = useChatSession()
    return <><button onClick={() => void send({ text: 'test-only', account_id: 'a' })}>send</button>{state.errorCode === 'preferences_unavailable' && <button onClick={() => void retryWithoutPreferences()}>{de.preferences.continueWithout}</button>}</>
  }
  render(<QueryClientProvider client={clientWithGrants()}><ChatSessionProvider><Consumer /></ChatSessionProvider></QueryClientProvider>)
  fireEvent.click(screen.getByText('send'))
  const continueButton = await screen.findByRole('button', { name: de.preferences.continueWithout })
  expect(bodies).toHaveLength(1)
  expect(bodies[0]?.without_preferences).toBeUndefined()
  fireEvent.click(continueButton)
  await waitFor(() => expect(bodies).toHaveLength(2))
  expect(bodies[1]).toMatchObject({ text: 'test-only', account_id: 'a', without_preferences: true })
})

// Restarting is the only place that hands a conversation's unsent text to the start page.
function restartHarness(id?: string, seed = true) {
  const sources = spyOn(sdk, 'calendarSourcesList').mockResolvedValue({ data: [] } as never)
  const client = clientWithGrants()
  if (seed) client.setQueryData(['conversations'], [{ id: 'c', title: 'Test', account_scope_json: JSON.stringify({ account_ids: ['b'], selection: 'b' }) }])
  function Start() {
    const { composerTexts, setComposerText, calendarScopes } = useChatSession()
    return <><div data-testid="start" data-calendars={JSON.stringify(calendarScopes.new)} data-draft={composerTexts.new ?? ''} /><button onClick={() => { setComposerText('new', 'Bleibt') }}>draft</button></>
  }
  // The harness keeps the open conversation and the composer in its own state so a test can change them mid-flight.
  const control = { setChatId: (_id?: string) => {}, setText: (_text: string) => {} }
  function Chat() {
    const session = useChatSession()
    const [current, setCurrent] = useState(id)
    control.setChatId = setCurrent
    control.setText = text => session.setComposerText(current ?? 'new', text)
    const restart = useRestartConversation(current)
    return <><button onClick={() => void session.send({ text: 'Test', conversation_id: current, calendar_source_ids: ['work'] })}>send-calendar</button><span>{session.state.errorCode}</span><button onClick={restart}>restart</button><button onClick={() => session.setComposerText(current ?? 'new', 'Noch offen')}>type</button>{current && <MobileHeader title="Chat" conversationId={current} onMenu={() => {}} />}</>
  }
  function Away() { return <div data-testid="away" /> }
  const root = createRootRoute({ component: () => <QueryClientProvider client={client}><ChatSessionProvider><Outlet /></ChatSessionProvider></QueryClientProvider> })
  const index = createRoute({ getParentRoute: () => root, path: '/', component: Start })
  const chat = createRoute({ getParentRoute: () => root, path: '/chat/$conversationId', component: Chat })
  const accounts = createRoute({ getParentRoute: () => root, path: '/accounts', component: Away })
  const router = createRouter({ routeTree: root.addChildren([index, chat, accounts]), history: createMemoryHistory({ initialEntries: ['/'] }) })
  render(<RouterProvider router={router} />)
  // Wrappers so the test keeps calling into the latest render of the chat.
  return { router, client, sources, setChatId: (value?: string) => control.setChatId(value), setText: (text: string) => control.setText(text) }
}

async function restart(router: ReturnType<typeof restartHarness>['router']) {
  fireEvent.click(await screen.findByText('draft'))
  await act(async () => { await router.navigate({ to: '/chat/$conversationId', params: { conversationId: 'c' } }) })
  fireEvent.click(await screen.findByText('restart'))
  await waitFor(() => expect(router.state.location.pathname).toBe('/'))
}

test('restart after 409 preserves calendar selection when an uncached sources request fails', async () => {
  const { router, client, sources } = restartHarness('c')
  await openChat(router)
  globalThis.fetch = (async () => new Response(JSON.stringify({ detail: { code: 'conversation_scope_change_requires_new' } }), { status: 409 })) as unknown as typeof fetch
  sources.mockRejectedValue(new Error('test-only'))
  expect(client.getQueryData(['calendar', 'sources'])).toBeUndefined()
  fireEvent.click(screen.getByText('send-calendar'))
  await screen.findByText('conversation_scope_change_requires_new')
  fireEvent.click(screen.getByText('restart'))
  await waitFor(() => expect(router.state.location.pathname).toBe('/'))
  expect(screen.getByTestId('start').dataset.calendars).toBe('["work"]')
  expect(sources).toHaveBeenCalledTimes(1)
})

test('restart without unsent text keeps the start draft', async () => {
  const { router } = restartHarness('c')
  await restart(router)
  expect(screen.getByTestId('start').dataset.draft).toBe('Bleibt')
})

test('restart without a conversation only navigates', async () => {
  const { router } = restartHarness()
  await restart(router)
  expect(screen.getByTestId('start').dataset.draft).toBe('Bleibt')
})

function deferCalendars(sources: ReturnType<typeof restartHarness>['sources']) {
  let release!: (value: { data: never[] }) => void
  sources.mockImplementation((() => new Promise(resolve => { release = resolve })) as never)
  return () => release({ data: [] })
}
async function openChat(router: ReturnType<typeof restartHarness>['router']) {
  fireEvent.click(await screen.findByText('draft'))
  await act(async () => { await router.navigate({ to: '/chat/$conversationId', params: { conversationId: 'c' } }) })
}

test('a fresh start never waits for the old account selection', async () => {
  const list = spyOn(sdk, 'chatConversationsList')
  const { router } = restartHarness('c', false)
  await restart(router)
  expect(list).not.toHaveBeenCalled()
})

// A waiting restart belongs to the conversation that was open: leaving it or switching it drops the attempt.
test('a waiting restart changes nothing when the chat is left', async () => {
  const { router, sources } = restartHarness('c', false)
  const release = deferCalendars(sources)
  await openChat(router)
  fireEvent.click(await screen.findByRole('button', { name: 'type' }))
  fireEvent.click(screen.getByRole('button', { name: 'Neue Unterhaltung' }))
  await act(async () => { await router.navigate({ to: '/accounts' }) })
  await act(async () => { release() })
  expect(router.state.location.pathname).toBe('/accounts')
  await act(async () => { await router.navigate({ to: '/' }) })
  const start = await screen.findByTestId('start')
  expect(start.dataset.draft).toBe('Bleibt')
})

test('a waiting restart changes nothing when its conversation changes', async () => {
  const { router, sources, setChatId } = restartHarness('c', false)
  const release = deferCalendars(sources)
  await openChat(router)
  fireEvent.click(await screen.findByRole('button', { name: 'type' }))
  fireEvent.click(screen.getByRole('button', { name: 'Neue Unterhaltung' }))
  await act(async () => { setChatId('d') })
  await act(async () => { release() })
  expect(router.state.location.pathname).toBe('/chat/c')
  await act(async () => { await router.navigate({ to: '/' }) })
  const start = await screen.findByTestId('start')
  expect(start.dataset.draft).toBe('Bleibt')
})

test('a restart waiting for the calendar list changes nothing when its conversation changes, and a later restart works', async () => {
  const { router, sources, setChatId } = restartHarness('c')
  let release!: (value: { data: unknown[] }) => void
  sources.mockImplementation((() => new Promise(resolve => { release = resolve })) as never)
  await openChat(router)
  fireEvent.click(await screen.findByText('restart'))
  await act(async () => { setChatId('d') })
  await act(async () => { release({ data: [] }) })
  expect(router.state.location.pathname).toBe('/chat/c')
  await act(async () => { setChatId('c') })
  fireEvent.click(screen.getByText('restart'))
  await waitFor(() => expect(router.state.location.pathname).toBe('/'))
})

// The composer can change while the calendar list loads.
test('a waiting restart copies the latest draft', async () => {
  const { router, sources, setText } = restartHarness('c', false)
  const release = deferCalendars(sources)
  await openChat(router)
  fireEvent.click(await screen.findByRole('button', { name: 'type' }))
  fireEvent.click(screen.getByRole('button', { name: 'Neue Unterhaltung' }))
  await act(async () => { setText('Second') })
  await act(async () => { release() })
  await waitFor(() => expect(router.state.location.pathname).toBe('/'))
  const start = await screen.findByTestId('start')
  expect(start.dataset.draft).toBe('Second')
})

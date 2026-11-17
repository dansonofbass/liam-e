import { afterEach, expect, spyOn, test } from 'bun:test'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createMemoryHistory, createRootRoute, createRoute, createRouter, Outlet, RouterProvider } from '@tanstack/react-router'
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import * as sdk from '../api/generated/sdk.gen'
import { de } from '../i18n/de'
import { MobileHeader } from '../shell/MobileHeader'
import { ChatSessionProvider, useChatSession, useRestartConversation } from './session'

const originalFetch = globalThis.fetch, originalMatchMedia = window.matchMedia
let controller: ReadableStreamDefaultController<Uint8Array>, signal: AbortSignal
function setup() {
  window.matchMedia = (() => ({ matches: true })) as unknown as typeof window.matchMedia
  globalThis.fetch = ((_url: unknown, init: RequestInit) => { signal = init.signal!; return Promise.resolve(new Response(new ReadableStream({ start(c) { controller = c } }))) }) as typeof fetch
  function Consumer() {
    const { state, send, stop } = useChatSession()
    return <><button onClick={() => void send({ text: 'Hi' })}>send</button><button onClick={stop}>stop</button><div data-testid="phase">{state.phase}</div><div data-testid="text">{state.text}</div><div data-testid="mails">{state.mails.length}</div>{state.phase === 'stopped' && de.chat.stopped}{state.errorCode && de.errors[state.errorCode]}</>
  }
  render(<QueryClientProvider client={new QueryClient()}><ChatSessionProvider><Consumer /></ChatSessionProvider></QueryClientProvider>)
  fireEvent.click(screen.getByText('send'))
}
function frame(value: object) { controller.enqueue(new TextEncoder().encode(`data: ${JSON.stringify(value)}\n\n`)) }
afterEach(() => { cleanup(); globalThis.fetch = originalFetch; window.matchMedia = originalMatchMedia })
test('buffers cards until done and text', async () => {
  setup(); await act(async () => { frame({ event: 'start', conversation_id: 'c' }); frame({ event: 'delta', text: 'Hallo' }); frame({ event: 'mails', mails: [{}] }) })
  expect(screen.getByTestId('text').textContent).toBe('Hallo'); expect(screen.getByTestId('mails').textContent).toBe('0')
  await act(async () => { frame({ event: 'done', conversation_id: 'c', message_id: 'm', stopped: false }) })
  await waitFor(() => expect(screen.getByTestId('phase').textContent).toBe('done'))
  expect(screen.getByTestId('mails').textContent).toBe('1')
})
test('stop aborts and displays notice', async () => { setup(); await act(async () => { frame({ event: 'delta', text: 'Hallo' }) }); fireEvent.click(screen.getByText('stop')); expect(signal.aborted).toBe(true); expect(screen.getByText(de.chat.stopped)).toBeTruthy(); expect(screen.getByTestId('phase').textContent).toBe('stopped') })
test('network break reports aborted', async () => { setup(); await act(async () => { frame({ event: 'delta', text: 'Hallo' }) }); await act(async () => { controller.error(new TypeError('network')) }); await waitFor(() => expect(screen.getByText(de.errors.aborted)).toBeTruthy()); expect(screen.getByTestId('phase').textContent).toBe('error') })

// Restarting is the only place that hands a conversation's unsent text to the start page.
function restartHarness(id?: string, seed = true) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } })
  if (seed) client.setQueryData(['conversations'], [{ id: 'c', title: 'Test', account_scope_json: JSON.stringify({ account_ids: ['b'], selection: 'b' }) }])
  function Start() {
    const { scope, composerTexts, setScope, setComposerText } = useChatSession()
    return <><div data-testid="start" data-scope={scope ?? 'all'} data-draft={composerTexts.new ?? ''} /><button onClick={() => { setScope('a'); setComposerText('new', 'Bleibt') }}>draft</button></>
  }
  function Chat() {
    const { setComposerText } = useChatSession()
    const restart = useRestartConversation(id)
    return <><button onClick={restart}>restart</button><button onClick={() => setComposerText(id ?? 'new', 'Noch offen')}>type</button>{id && <MobileHeader title="Chat" conversationId={id} onMenu={() => {}} />}</>
  }
  const root = createRootRoute({ component: () => <QueryClientProvider client={client}><ChatSessionProvider><Outlet /></ChatSessionProvider></QueryClientProvider> })
  const index = createRoute({ getParentRoute: () => root, path: '/', component: Start })
  const chat = createRoute({ getParentRoute: () => root, path: '/chat/$conversationId', component: Chat })
  const router = createRouter({ routeTree: root.addChildren([index, chat]), history: createMemoryHistory({ initialEntries: ['/'] }) })
  render(<RouterProvider router={router} />)
  return router
}

async function restart(router: ReturnType<typeof restartHarness>) {
  fireEvent.click(await screen.findByText('draft'))
  await act(async () => { await router.navigate({ to: '/chat/$conversationId', params: { conversationId: 'c' } }) })
  fireEvent.click(await screen.findByText('restart'))
  await waitFor(() => expect(router.state.location.pathname).toBe('/'))
}

test('restart without unsent text keeps the start draft and takes the account', async () => {
  const router = restartHarness('c')
  await restart(router)
  expect((await screen.findByTestId('start')).dataset.scope).toBe('b')
  expect(screen.getByTestId('start').dataset.draft).toBe('Bleibt')
})

test('restart without a conversation only navigates', async () => {
  const router = restartHarness()
  await restart(router)
  expect((await screen.findByTestId('start')).dataset.scope).toBe('a')
  expect(screen.getByTestId('start').dataset.draft).toBe('Bleibt')
})

// The conversation list may still be in flight when the plus is pressed: the restart waits for it
// instead of claiming "all accounts", and keeps the start page's selection when it cannot load.
test('restart waits for a loading conversation list before taking its account', async () => {
  let release!: (value: { data: unknown[] }) => void
  spyOn(sdk, 'chatConversationsList').mockImplementation((() => new Promise(resolve => { release = resolve })) as never)
  const router = restartHarness('c', false)
  await act(async () => { await router.navigate({ to: '/chat/$conversationId', params: { conversationId: 'c' } }) })
  fireEvent.click(await screen.findByRole('button', { name: 'type' }))
  fireEvent.click(screen.getByRole('button', { name: 'Neue Unterhaltung' }))
  expect(router.state.location.pathname).toBe('/chat/c')
  await act(async () => { release({ data: [{ id: 'c', title: 'Test', account_scope_json: JSON.stringify({ account_ids: ['b'], selection: 'b' }) }] }) })
  await waitFor(() => expect(router.state.location.pathname).toBe('/'))
  const start = await screen.findByTestId('start')
  expect(start.dataset.scope).toBe('b')
  expect(start.dataset.draft).toBe('Noch offen')
})

test('restart keeps the start selection when the conversation list fails', async () => {
  spyOn(sdk, 'chatConversationsList').mockImplementation((async () => { throw new Error('offline') }) as never)
  const router = restartHarness('c', false)
  fireEvent.click(await screen.findByText('draft'))
  await act(async () => { await router.navigate({ to: '/chat/$conversationId', params: { conversationId: 'c' } }) })
  fireEvent.click(await screen.findByRole('button', { name: 'type' }))
  fireEvent.click(screen.getByRole('button', { name: 'Neue Unterhaltung' }))
  await waitFor(() => expect(router.state.location.pathname).toBe('/'))
  const start = await screen.findByTestId('start')
  expect(start.dataset.scope).toBe('a')
  expect(start.dataset.draft).toBe('Noch offen')
})

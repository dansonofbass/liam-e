import { afterEach, expect, test } from 'bun:test'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { de } from '../i18n/de'
import { ChatSessionProvider, useChatSession } from './session'

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

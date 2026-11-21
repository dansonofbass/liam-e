import { afterEach, expect, test } from 'bun:test'
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { LiveVoice } from './LiveVoice'

const original = { fetch: globalThis.fetch, AudioContext: globalThis.AudioContext, WebSocket: globalThis.WebSocket, secure: globalThis.isSecureContext, media: navigator.mediaDevices }
afterEach(() => { cleanup(); Object.assign(globalThis, { fetch: original.fetch, AudioContext: original.AudioContext, WebSocket: original.WebSocket, isSecureContext: original.secure }); Object.defineProperty(navigator, 'mediaDevices', { value: original.media, configurable: true }) })

test('two synthetic turns play audio, interruption and ending release resources', async () => {
  let ws: FakeSocket, stopped = 0, played = 0, closed = 0
  const requests: string[] = []
  class FakeSocket {
    static OPEN = 1
    readyState = 1; bufferedAmount = 0; binaryType = ''
    onopen?: () => void; onerror?: () => void; onclose?: () => void; onmessage?: (e: { data: string }) => void
    constructor() { ws = this; queueMicrotask(() => this.onopen?.()) }
    send() {} close() { closed++; this.onclose?.() }
    emit(value: object) { this.onmessage?.({ data: JSON.stringify(value) }) }
  }
  class FakeContext {
    sampleRate = 24000; currentTime = 0; destination = {}
    async resume() {} async close() { closed++ }
    createMediaStreamSource() { return { connect() {} } }
    createScriptProcessor() { return { connect() {}, disconnect() {}, onaudioprocess: null } }
    createBuffer(_channels: number, length: number) { return { duration: 0, getChannelData: () => new Float32Array(length) } }
    createBufferSource() { return { connect() {}, start() { played++ }, stop() {}, onended: null, buffer: null } }
  }
  Object.assign(globalThis, { AudioContext: FakeContext, WebSocket: FakeSocket, isSecureContext: true })
  Object.defineProperty(navigator, 'mediaDevices', { configurable: true, value: { getUserMedia: async () => ({ getTracks: () => [{ stop: () => { stopped++ } }] }) } })
  globalThis.fetch = (async (url: string | URL | Request) => String(url).endsWith('/status') ? Response.json({ available: true }) : new Response(new Uint8Array([0, 1, 0, 1]))) as typeof fetch
  render(<LiveVoice conversationId="c1" contextKey="c1" disabled={false} registerStop={() => {}} stopChat={() => {}} send={async text => { requests.push(text); return { conversationId: 'c1', messageId: `m${requests.length}` } }} />)
  fireEvent.click(await screen.findByLabelText('Sprachmodus starten'))
  await waitFor(() => expect(screen.getByText('Zuhören')).toBeTruthy())
  const turn = async (text: string) => { await act(async () => { ws.emit({ type: 'turn.start' }); ws.emit({ type: 'transcription.text.delta', text }); ws.emit({ type: 'turn.end' }); await new Promise(resolve => setTimeout(resolve, 510)) }) }
  await turn('Merk dir: Die Testente ist gelb.')
  await waitFor(() => expect(played).toBe(1))
  await turn('Welche Farbe hat die Testente?')
  await waitFor(() => expect(played).toBe(2))
  expect(requests).toEqual(['Merk dir: Die Testente ist gelb.', 'Welche Farbe hat die Testente?'])
  fireEvent.click(screen.getByLabelText('Sprachmodus beenden'))
  expect(stopped).toBe(1); expect(closed).toBeGreaterThanOrEqual(2)
})

test('denied microphone permission leaves no running session', async () => {
  class FakeContext { async resume() {} async close() {} }
  Object.assign(globalThis, { AudioContext: FakeContext, isSecureContext: true })
  Object.defineProperty(navigator, 'mediaDevices', { configurable: true, value: { getUserMedia: async () => { throw new Error('denied') } } })
  globalThis.fetch = (async () => Response.json({ available: true })) as unknown as typeof fetch
  render(<LiveVoice conversationId="c" contextKey="c" disabled={false} registerStop={() => {}} stopChat={() => {}} send={async () => undefined} />)
  fireEvent.click(await screen.findByLabelText('Sprachmodus starten'))
  expect(await screen.findByText('Sprachmodus nicht verfügbar')).toBeTruthy()
})

test('navigation while microphone permission is pending stops the late track', async () => {
  let resolvePermission!: (stream: unknown) => void, stopped = 0
  class FakeContext { async resume() {} async close() {} }
  Object.assign(globalThis, { AudioContext: FakeContext, isSecureContext: true })
  Object.defineProperty(navigator, 'mediaDevices', { configurable: true, value: { getUserMedia: () => new Promise(resolve => { resolvePermission = resolve }) } })
  globalThis.fetch = (async () => Response.json({ available: true })) as unknown as typeof fetch
  const view = render(<LiveVoice conversationId="c" contextKey="c" disabled={false} registerStop={() => {}} stopChat={() => {}} send={async () => undefined} />)
  fireEvent.click(await screen.findByLabelText('Sprachmodus starten'))
  await waitFor(() => expect(resolvePermission).toBeDefined())
  view.unmount()
  await act(async () => { resolvePermission({ getTracks: () => [{ stop: () => { stopped++ } }] }) })
  expect(stopped).toBe(1)
})

test('the mode can be ended while permission is pending', async () => {
  let resolvePermission!: (stream: unknown) => void, stopped = 0
  class FakeContext { async resume() {} async close() {} }
  Object.assign(globalThis, { AudioContext: FakeContext, isSecureContext: true })
  Object.defineProperty(navigator, 'mediaDevices', { configurable: true, value: { getUserMedia: () => new Promise(resolve => { resolvePermission = resolve }) } })
  globalThis.fetch = (async () => Response.json({ available: true })) as unknown as typeof fetch
  render(<LiveVoice conversationId="c" contextKey="c" disabled={false} registerStop={() => {}} stopChat={() => {}} send={async () => undefined} />)
  fireEvent.click(await screen.findByLabelText('Sprachmodus starten'))
  await waitFor(() => expect(resolvePermission).toBeDefined())
  fireEvent.click(screen.getByLabelText('Sprachmodus beenden'))
  await act(async () => { resolvePermission({ getTracks: () => [{ stop: () => { stopped++ } }] }) })
  expect(stopped).toBe(1)
  expect(screen.getByLabelText('Sprachmodus starten')).toBeTruthy()
})

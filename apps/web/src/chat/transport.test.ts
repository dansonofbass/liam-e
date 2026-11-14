import { afterEach, describe, expect, test } from 'bun:test'
import type { ChatStreamRequest } from '../api/generated/types.gen'
import { ChatStreamError, streamChatTurn } from './transport'

const BODY: ChatStreamRequest = { text: 'Hallo' }

const originalFetch = globalThis.fetch

/** A 404 whose body read fails with `error`, as a body still arriving when the caller aborts does. */
const refusingResponse = (error: Error): Response => {
  const response = new Response(null, { status: 404 })
  Object.defineProperty(response, 'json', { value: () => Promise.reject(error) })
  return response
}

/** Stand-in for `fetch`, which in Bun also carries `preconnect`. */
const respondWith = (response: Response): void => {
  globalThis.fetch = Object.assign(() => Promise.resolve(response), {
    preconnect: () => {
      /* no-op: the stand-in answers without a connection to warm */
    },
  })
}

/** The error `streamChatTurn` rejects with, or a failure if it yields instead. */
const rejectionOf = async (signal: AbortSignal): Promise<unknown> => {
  try {
    await Array.fromAsync(streamChatTurn(BODY, signal))
  } catch (error) {
    return error
  }
  throw new Error('Expected the stream to reject')
}

afterEach(() => {
  globalThis.fetch = originalFetch
})

describe('streamChatTurn refusals', () => {
  test('an abort while the refusal body is read passes through unchanged', async () => {
    const abort = new DOMException('The operation was aborted.', 'AbortError')
    respondWith(refusingResponse(abort))

    const error = await rejectionOf(new AbortController().signal)

    expect(error instanceof ChatStreamError).toBe(false)
    expect(error instanceof Error).toBe(true)
    expect((error as Error).name).toBe('AbortError')
  })

  test('a refused turn keeps the detail code and never quotes the response text', async () => {
    const body = JSON.stringify({ detail: { code: 'conversation_not_found', message: 'x' } })
    respondWith(new Response(body, { status: 404 }))

    const error = await rejectionOf(new AbortController().signal)

    expect(error instanceof ChatStreamError).toBe(true)
    const refusal = error as ChatStreamError
    expect(refusal.code).toBe('conversation_not_found')
    expect(refusal.detailCode).toBe('conversation_not_found')
    expect(refusal.message).not.toContain('x')
  })
})

import { apiBaseUrl } from '../api/client-config'
import type { ChatEvent, ChatStreamRequest } from '../api/generated/types.gen'
import { parseSse } from './sse'

export class ChatStreamError extends Error {
  constructor(public code: 'internal' | 'aborted' | 'conversation_not_found' | 'model_unknown', public detailCode?: string) {
    super('Chat stream failed')
    this.name = 'ChatStreamError'
  }
}

/** Whether `error` is a caller's abort: a browser `DOMException` is not an `Error`. */
const isAbort = (error: unknown): boolean =>
  typeof error === 'object' && error !== null && 'name' in error && error.name === 'AbortError'

export async function* streamChatTurn(body: ChatStreamRequest, signal: AbortSignal): AsyncIterable<ChatEvent> {
  try {
    const response = await fetch(`${apiBaseUrl()}/api/v1/chat/stream`, { method: 'POST', headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' }, body: JSON.stringify(body), signal })
    if (!response.ok) {
      let detailCode: string | undefined
      try {
        const json = await response.json()
        if (typeof json?.detail?.code === 'string') detailCode = json.detail.code
      } catch (error) {
        // Reading the refusal body can end in the caller's abort: that abort is not a refusal.
        if (isAbort(error)) throw error
        /* No JSON detail. */
      }
      throw new ChatStreamError(detailCode === 'conversation_not_found' || detailCode === 'model_unknown' ? detailCode : 'internal', detailCode)
    }
    if (!response.body) throw new ChatStreamError('aborted')
    for await (const frame of parseSse(response.body)) {
      let event: ChatEvent
      try { event = JSON.parse(frame.data) as ChatEvent } catch { throw new ChatStreamError('internal') }
      yield event
      if (event.event === 'done' || event.event === 'error') return
    }
    throw new ChatStreamError('aborted')
  } catch (error) {
    if (error instanceof ChatStreamError || isAbort(error)) throw error
    throw new ChatStreamError('aborted')
  }
}

import { apiBaseUrl } from '../api/client-config'
import type { ChatEvent, ChatStreamRequest } from '../api/generated/types.gen'
import { parseSse } from './sse'

export class ChatStreamError extends Error {
  constructor(public code: 'internal' | 'aborted', public detailCode?: string) {
    super('Chat stream failed')
    this.name = 'ChatStreamError'
  }
}

export async function* streamChatTurn(body: ChatStreamRequest, signal: AbortSignal): AsyncIterable<ChatEvent> {
  try {
    const response = await fetch(`${apiBaseUrl()}/api/v1/chat/stream`, { method: 'POST', headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' }, body: JSON.stringify(body), signal })
    if (!response.ok) {
      let detailCode: string | undefined
      try { const json = await response.json(); if (typeof json?.detail?.code === 'string') detailCode = json.detail.code } catch { /* No JSON detail. */ }
      throw new ChatStreamError('internal', detailCode)
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
    if (error instanceof ChatStreamError || (error instanceof Error && error.name === 'AbortError')) throw error
    throw new ChatStreamError('aborted')
  }
}

import { apiBaseUrl } from '../api/client-config'
import type { ChatEvent, ChatStreamRequest } from '../api/generated/types.gen'
import { parseSse } from './sse'

// Refusals before the stream starts that the conversation view explains on their own.
const KNOWN_REFUSALS = ['settings_unavailable', 'chat_settings_changed', 'chat_account_not_granted', 'preferences_unavailable', 'conversation_not_found', 'model_unknown', 'model_catalog_unavailable', 'conversation_scope_change_requires_new', 'calendar_reference_unavailable', 'context_unavailable', 'context_invalid', 'version_conflict', 'skill_not_found', 'skill_revision_unavailable', 'skill_disabled', 'skill_tool_unavailable'] as const
export const SKILL_REFUSALS = new Set<string>(['skill_not_found', 'skill_revision_unavailable', 'skill_disabled', 'skill_tool_unavailable'])
export type ChatRefusal = typeof KNOWN_REFUSALS[number]
const isKnownRefusal = (code: string | undefined): code is ChatRefusal => (KNOWN_REFUSALS as readonly (string | undefined)[]).includes(code)

export class ChatStreamError extends Error {
  constructor(public code: 'internal' | 'aborted' | ChatRefusal, public detailCode?: string) {
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
      throw new ChatStreamError(isKnownRefusal(detailCode) ? detailCode : 'internal', detailCode)
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

import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from '@tanstack/react-router'
import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from 'react'
import type { ChatMessageOut, ChatStreamRequest, MailRefOut, StatusEvent } from '../api/generated/types.gen'
import { ChatStreamError, streamChatTurn, type ChatRefusal } from './transport'
import { createTypewriter } from './typewriter'
import { conversationsQuery } from '../api/queries'

type ErrorCode = 'model_unavailable' | 'aborted' | 'internal' | 'context_revoked' | ChatRefusal
type State = { phase: 'idle' | 'working' | 'streaming' | 'done' | 'stopped' | 'error'; status?: StatusEvent; text: string; mails: MailRefOut[]; proposal: ChatMessageOut | null; suggestions: string[]; errorCode?: ErrorCode; conversationId?: string; messageId?: string; userMessageId?: string; request?: ChatStreamRequest }
type Session = { composerTexts: Record<string, string>; setComposerText: (id: string, text: string) => void; scopeOverrides: Record<string, string | null>; setConversationScope: (id: string, scope: string | null) => void; state: State; scope: string | null; setScope: (scope: string | null) => void; send: (request: ChatStreamRequest) => Promise<void>; stop: () => void; retry: () => Promise<void> }
const initial = (): State => ({ phase: 'idle', text: '', mails: [], proposal: null, suggestions: [] })
const Context = createContext<Session | null>(null)

export function ChatSessionProvider({ children }: { children: ReactNode }) {
  const client = useQueryClient()
  const [state, setState] = useState<State>(initial)
  const [scope, setScope] = useState<string | null>(null)
  const [composerTexts, setComposerTexts] = useState<Record<string, string>>({})
  const setComposerText = (id: string, text: string) => setComposerTexts(previous => ({ ...previous, [id]: text }))
  const [scopeOverrides, setScopeOverrides] = useState<Record<string, string | null>>({})
  const setConversationScope = (id: string, value: string | null) => setScopeOverrides(previous => ({ ...previous, [id]: value }))
  const active = useRef<{ controller: AbortController; writer: ReturnType<typeof createTypewriter>; conversationId?: string } | null>(null)
  const last = useRef<ChatStreamRequest | null>(null)
  const conversation = useRef<string | undefined>(undefined)
  const invalidate = useCallback((id?: string) => {
    void client.invalidateQueries({ queryKey: ['conversations'] })
    if (id) void client.invalidateQueries({ queryKey: ['history', id] })
  }, [client])
  const stop = useCallback(() => {
    const turn = active.current
    if (!turn) return
    active.current = null
    turn.controller.abort(); turn.writer.flushNow(); turn.writer.cancel()
    setState(s => ({ ...s, phase: 'stopped', status: undefined, mails: [], proposal: null, suggestions: [] }))
    invalidate(turn.conversationId)
  }, [invalidate])
  useEffect(() => () => { const turn = active.current; active.current = null; turn?.controller.abort(); turn?.writer.cancel() }, [])
  const send = useCallback(async (request: ChatStreamRequest) => {
    if (active.current) return
    last.current = request
    conversation.current = request.conversation_id ?? undefined
    setState({ ...initial(), phase: 'working', request, conversationId: request.conversation_id ?? undefined })
    const controller = new AbortController()
    const writer = createTypewriter({ reducedMotion: typeof window !== 'undefined' && typeof window.matchMedia === 'function' && window.matchMedia('(prefers-reduced-motion: reduce)').matches, onText: text => setState(s => ({ ...s, text, phase: 'streaming', status: undefined })) })
    const turn = { controller, writer, conversationId: conversation.current }
    active.current = turn
    let mails: MailRefOut[] = [], proposal: ChatMessageOut | null = null, suggestions: string[] = []
    try {
      for await (const event of streamChatTurn(request, controller.signal)) {
        if (active.current !== turn) return
        switch (event.event) {
          case 'start':
            setComposerTexts(previous => ({ ...previous, [request.conversation_id ?? 'new']: '' }))
            turn.conversationId = conversation.current = event.conversation_id
            setState(s => ({ ...s, conversationId: event.conversation_id, userMessageId: event.user_message_id }))
            void client.invalidateQueries({ queryKey: ['conversations'] }); break
          case 'status': setState(s => ({ ...s, status: event })); break
          case 'delta': writer.push(event.text); break
          case 'mails': mails = event.mails; break
          case 'proposal': proposal = event.message; break
          case 'suggestions': suggestions = event.items; break
          case 'done':
            await writer.finish()
            if (active.current !== turn) return
            active.current = null
            setState(s => ({ ...s, phase: event.stopped ? 'stopped' : 'done', status: undefined, mails: event.stopped ? [] : mails, proposal: event.stopped ? null : proposal, suggestions: event.stopped ? [] : suggestions, conversationId: event.conversation_id, messageId: event.message_id }))
            invalidate(event.conversation_id); return
          case 'error':
            writer.flushNow(); writer.cancel(); active.current = null
            setState(s => ({ ...s, phase: 'error', status: undefined, errorCode: event.code }))
            invalidate(turn.conversationId); return
        }
      }
    } catch (error) {
      if (active.current !== turn) return
      writer.flushNow(); writer.cancel(); active.current = null
      setState(s => ({ ...s, phase: 'error', status: undefined, errorCode: error instanceof ChatStreamError ? error.code : 'aborted' }))
      invalidate(turn.conversationId)
    }
  }, [client, invalidate])
  const retry = useCallback(async () => { if (last.current) await send({ ...last.current, ...(conversation.current ? { conversation_id: conversation.current } : {}) }) }, [send])
  return <Context.Provider value={{ state, scope, setScope, composerTexts, setComposerText, scopeOverrides, setConversationScope, send, stop, retry }}>{children}</Context.Provider>
}
// Shared restoration for every entry point; explicit edits are isolated by conversation.
export function useConversationScope(id?: string) {
  const session = useChatSession()
  const conversations = useQuery({ ...conversationsQuery(), enabled: !!id })
  const saved = conversations.data?.find(item => item.id === id)
  let selection: string | null | undefined
  if (saved) {
    try {
      const parsed = JSON.parse(saved.account_scope_json ?? '{}') as { selection?: unknown }
      if (typeof parsed.selection === 'string' || parsed.selection === null) selection = parsed.selection
      else selection = null // Legacy conversations have no pinned selection.
    } catch { /* Keep sending unavailable for malformed persisted scope. */ }
  }
  const live = id && session.state.conversationId === id ? session.state.request : undefined
  const scope = !id ? session.scope : Object.hasOwn(session.scopeOverrides, id) ? session.scopeOverrides[id]! : live ? live.account_id ?? null : selection
  return {
    saved,
    scope: scope ?? null,
    ready: scope !== undefined,
    setScope: (value: string | null) => id ? session.setConversationScope(id, value) : session.setScope(value),
  }
}

// Every restart from a conversation carries its account selection and unsent text to the start page.
export function useRestartConversation(id?: string) {
  const session = useChatSession()
  const { scope } = useConversationScope(id)
  const navigate = useNavigate()
  return () => { session.setScope(scope); session.setComposerText('new', session.composerTexts[id ?? 'new'] ?? ''); void navigate({ to: '/' }) }
}

export function useChatSession(): Session {
  const context = useContext(Context)
  if (!context) throw new Error('useChatSession must be used within ChatSessionProvider')
  return context
}

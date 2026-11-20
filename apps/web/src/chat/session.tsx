import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from '@tanstack/react-router'
import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from 'react'
import type { ChatMessageOut, ChatStreamRequest, ConversationOut, MailRefOut, StatusEvent, CalendarRefOut, SourceOut } from '../api/generated/types.gen'
import { ChatStreamError, streamChatTurn, type ChatRefusal } from './transport'
import { useI18n } from '../i18n/I18n'
import { createTypewriter } from './typewriter'
import { calendarSourcesQuery, chatSettingsQuery, conversationsQuery, historyQuery, summaryQuery } from '../api/queries'

type ErrorCode = 'model_unavailable' | 'aborted' | 'internal' | 'context_revoked' | ChatRefusal
type State = { phase: 'idle' | 'working' | 'streaming' | 'done' | 'stopped' | 'error'; status?: StatusEvent; text: string; mails: MailRefOut[]; calendars?: CalendarRefOut[]; proposal: ChatMessageOut | null; suggestions: string[]; errorCode?: ErrorCode; conversationId?: string; messageId?: string; userMessageId?: string; model?: string; request?: ChatStreamRequest }
export type TaskScope = { source: 'none' | 'all' | 'unlinked' | 'account' | 'account_and_unlinked'; account_id?: string }
type Session = { taskScopes: Record<string, TaskScope>; setTaskScope: (id: string, scope: TaskScope) => void; calendarScopes: Record<string, string[]>; setCalendarScope: (id: string, ids: string[]) => void; composerTexts: Record<string, string>; setComposerText: (id: string, text: string | ((previous: string) => string)) => void; audioDraftLocked: boolean; setAudioDraftLocked: (locked: boolean) => void; state: State; send: (request: ChatStreamRequest) => Promise<void>; stop: () => void; retry: () => Promise<void>; retryWithoutPreferences: () => Promise<void> }
const initial = (): State => ({ phase: 'idle', text: '', mails: [], proposal: null, suggestions: [] })
const Context = createContext<Session | null>(null)

export type ComposerMail = Pick<MailRefOut, 'id' | 'account_id'>

export function composerDraftKey(conversationId?: string | null, messageId?: string | null) {
  return conversationId ?? (messageId ? 'mail:' + messageId : 'new')
}

// The account selection a conversation was saved with; undefined until its conversation is known.
function savedSelection(saved?: ConversationOut): string | null | undefined {
  if (!saved) return undefined
  try {
    const parsed = JSON.parse(saved.account_scope_json ?? '{}') as { selection?: unknown }
    if (typeof parsed.selection === 'string' || parsed.selection === null) return parsed.selection
    return null // Legacy conversations have no pinned selection.
  } catch { return undefined } // Malformed persisted scope keeps sending unavailable.
}

export function ChatSessionProvider({ children }: { children: ReactNode }) {
  const client = useQueryClient()
  const { browserLocale } = useI18n()
  const [state, setState] = useState<State>(initial)
  const [taskScopes, setTaskScopes] = useState<Record<string, TaskScope>>({})
  const setTaskScope = (id: string, scope: TaskScope) => setTaskScopes(previous => ({ ...previous, [id]: scope }))
  const [calendarScopes, setCalendarScopes] = useState<Record<string, string[]>>({})
  const setCalendarScope = (id: string, ids: string[]) => setCalendarScopes(previous => ({ ...previous, [id]: ids }))
  const [composerTexts, setComposerTexts] = useState<Record<string, string>>({})
  const setComposerText = (id: string, text: string | ((previous: string) => string)) =>
    setComposerTexts(previous => ({ ...previous, [id]: typeof text === 'function' ? text(previous[id] ?? '') : text }))
  const [audioDraftLocked, setAudioDraftLocked] = useState(false)
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
    const composerKey = composerDraftKey(request.conversation_id, request.context_message_id)
    const calendarIds = request.calendar_source_ids ?? calendarScopes[composerKey] ?? savedCalendarScope(request.conversation_id ? client.getQueryData(historyQuery(request.conversation_id).queryKey) : undefined)
    const liveTasks = request.conversation_id && conversation.current === request.conversation_id ? last.current : undefined
    const tasks = taskScopes[composerKey] ?? (liveTasks ? { source: liveTasks.task_source ?? 'none', account_id: liveTasks.task_source_account_id ?? undefined } : savedTaskScope(request.conversation_id ? client.getQueryData(historyQuery(request.conversation_id).queryKey) : undefined))
    request = { ...request, locale: browserLocale, task_source: request.task_source ?? tasks.source, task_source_account_id: request.task_source !== undefined ? request.task_source_account_id : tasks.account_id, calendar_source_ids: calendarIds, calendar_timezone: Intl.DateTimeFormat().resolvedOptions().timeZone }
    last.current = request
    conversation.current = request.conversation_id ?? undefined
    setState({ ...initial(), phase: 'working', request, conversationId: request.conversation_id ?? undefined })
    const controller = new AbortController()
    const writer = createTypewriter({ reducedMotion: typeof window !== 'undefined' && typeof window.matchMedia === 'function' && window.matchMedia('(prefers-reduced-motion: reduce)').matches, onText: text => setState(s => ({ ...s, text, phase: 'streaming', status: undefined })) })
    const turn = { controller, writer, conversationId: conversation.current }
    active.current = turn
    let calendars: CalendarRefOut[] = []
    let mails: MailRefOut[] = [], proposal: ChatMessageOut | null = null, suggestions: string[] = []
    try {
      // Direct replies and quick actions use the same grant as the composer.
      let version: number | null | undefined
      try {
        const summary = client.getQueryData(summaryQuery(true).queryKey)
        const grant = summary?.mail_scope_version == null ? await client.fetchQuery(chatSettingsQuery()) : undefined
        version = grant?.version ?? summary?.mail_scope_version
        if (request.account_id && !(grant ? grant.account_ids.includes(request.account_id) : summary?.accounts.some(account => account.id === request.account_id))) {
          throw new ChatStreamError('chat_account_not_granted')
        }
      } catch (error) {
        if (error instanceof ChatStreamError) throw error
        throw new ChatStreamError('settings_unavailable')
      }
      if (active.current !== turn) return
      if (version == null) throw new ChatStreamError('settings_unavailable')
      request = { ...request, expected_mail_scope_version: version }
      for await (const event of streamChatTurn(request, controller.signal)) {
        if (active.current !== turn) return
        switch (event.event) {
          case 'start':
            setComposerTexts(previous => {
              return previous[composerKey] === request.text ? { ...previous, [composerKey]: '' } : previous
            })
            turn.conversationId = conversation.current = event.conversation_id
            setState(s => ({ ...s, conversationId: event.conversation_id, userMessageId: event.user_message_id, model: event.model }))
            void client.invalidateQueries({ queryKey: ['conversations'] }); break
          case 'status': setState(s => ({ ...s, status: event })); break
          case 'delta': writer.push(event.text); break
          case 'mails': mails = event.mails; break
          case 'calendars': calendars = event.calendars; break
          case 'proposal': proposal = event.message; break
          case 'suggestions': suggestions = event.items; break
          case 'done':
            await writer.finish()
            if (active.current !== turn) return
            active.current = null
            setState(s => ({ ...s, phase: event.stopped ? 'stopped' : 'done', status: undefined, mails: event.stopped ? [] : mails, calendars: event.stopped ? [] : calendars, proposal: event.stopped ? null : proposal, suggestions: event.stopped ? [] : suggestions, conversationId: event.conversation_id, messageId: event.message_id }))
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
      if (error instanceof ChatStreamError && ['chat_settings_changed', 'chat_account_not_granted'].includes(error.code)) {
        void client.resetQueries({ queryKey: summaryQuery(true).queryKey, exact: true })
        void client.resetQueries({ queryKey: chatSettingsQuery().queryKey, exact: true })
      }
      setState(s => ({ ...s, phase: 'error', status: undefined, errorCode: error instanceof ChatStreamError ? error.code : 'aborted' }))
      invalidate(turn.conversationId)
    }
  }, [client, invalidate, calendarScopes, taskScopes, browserLocale])
  const retry = useCallback(async () => { if (last.current) await send({ ...last.current, ...(conversation.current ? { conversation_id: conversation.current } : {}) }) }, [send])
  const retryWithoutPreferences = useCallback(async () => { if (last.current) await send({ ...last.current, without_preferences: true, ...(conversation.current ? { conversation_id: conversation.current } : {}) }) }, [send])
  return <Context.Provider value={{ state, taskScopes, setTaskScope, calendarScopes, setCalendarScope, composerTexts, setComposerText, audioDraftLocked, setAudioDraftLocked, send, stop, retry, retryWithoutPreferences }}>{children}</Context.Provider>
}
// A mail entry point narrows the central grant. Existing conversations retain that focus.
export function useConversationScope(id?: string, mail?: ComposerMail) {
  const session = useChatSession()
  const conversations = useQuery({ ...conversationsQuery(), enabled: !!id })
  const saved = conversations.data?.find(item => item.id === id)
  const live = id && session.state.conversationId === id ? session.state.request : undefined
  const scope = id ? (live ? live.account_id ?? null : savedSelection(saved)) : mail?.account_id ?? null
  return { saved, scope: scope ?? null, ready: scope !== undefined }
}

// Start with the current central grant and carry the unsent draft.
export function useRestartConversation(id?: string) {
  const session = useChatSession()
  const client = useQueryClient()
  const navigate = useNavigate()
  // A waiting restart finishes with the live state of the conversation it was pressed in.
  const latest = useRef({ session, id })
  latest.current = { session, id }
  const attempt = useRef({ token: 0, pending: false })
  useEffect(() => () => { attempt.current.token += 1; attempt.current.pending = false }, [id])
  return () => {
    if (attempt.current.pending) return
    const { token } = attempt.current
    const transfer = async () => {
      if (attempt.current.token !== token) return
      attempt.current.pending = true
      let sources: SourceOut[] | undefined
      if (id) {
        try { sources = await client.ensureQueryData(calendarSourcesQuery()) }
        catch { /* Without a successful list, preserve the known calendar selection. */ }
      }
      if (attempt.current.token !== token) return // The conversation was left or switched: drop the attempt.
      attempt.current.pending = false
      const now = latest.current
      const text = now.id ? now.session.composerTexts[now.id] : undefined
      if (now.id) {
        const activeIds = sources && new Set(sources.filter(source => source.is_active).map(source => source.id))
        const ids = now.session.calendarScopes[now.id] ?? (now.session.state.conversationId === now.id ? now.session.state.request?.calendar_source_ids : undefined) ?? savedCalendarScope(client.getQueryData(historyQuery(now.id).queryKey))
        now.session.setCalendarScope('new', activeIds ? ids.filter(sourceId => activeIds.has(sourceId)) : ids)
        const liveTask = now.session.state.conversationId === now.id ? now.session.state.request : undefined
        const task = now.session.taskScopes[now.id] ?? (liveTask ? { source: liveTask.task_source ?? 'none', account_id: liveTask.task_source_account_id ?? undefined } : savedTaskScope(client.getQueryData(historyQuery(now.id).queryKey)))
        const allowed = client.getQueryData(summaryQuery(true).queryKey)?.accounts
        const valid = task.source !== 'account_and_unlinked' && (!task.account_id || allowed?.some(account => account.id === task.account_id))
        now.session.setTaskScope('new', valid ? task : { source: 'none' })
      }
      if (text) now.session.setComposerText('new', text)
      void navigate({ to: '/' })
    }
    void transfer()
  }
}

function savedCalendarScope(messages?: ChatMessageOut[]): string[] {
  try {
    const raw: unknown = JSON.parse(messages?.findLast(message => message.context)?.context?.calendar_scope_json ?? '[]')
    return Array.isArray(raw) && raw.every(id => typeof id === 'string') ? raw : []
  } catch { return [] }
}

export function useCalendarScope(id?: string, messageId?: string) {
  const session = useChatSession()
  const history = useQuery({ ...historyQuery(id ?? ''), enabled: !!id })
  const key = composerDraftKey(id, messageId)
  const live = id && session.state.conversationId === id ? session.state.request?.calendar_source_ids : undefined
  return {
    ids: session.calendarScopes[key] ?? live ?? savedCalendarScope(history.data),
    ready: !id || session.calendarScopes[key] !== undefined || live !== undefined || history.isSuccess,
    set: (ids: string[]) => session.setCalendarScope(key, ids),
  }
}

function savedTaskScope(messages?: ChatMessageOut[]): TaskScope {
  try {
    const raw = JSON.parse(messages?.findLast(message => message.context)?.context?.task_scope_json ?? '{"source":"none"}') as TaskScope
    if (['none', 'all', 'unlinked'].includes(raw.source)) return { source: raw.source }
    if (['account', 'account_and_unlinked'].includes(raw.source) && typeof raw.account_id === 'string') return raw
  } catch { /* Unknown provenance grants no access. */ }
  return { source: 'none' }
}

export function useTaskScope(id?: string, messageId?: string) {
  const session = useChatSession()
  const history = useQuery({ ...historyQuery(id ?? ''), enabled: !!id })
  const live = id && session.state.conversationId === id ? session.state.request : undefined
  const key = composerDraftKey(id, messageId)
  return {
    scope: session.taskScopes[key] ?? (live ? { source: live.task_source ?? 'none', account_id: live.task_source_account_id ?? undefined } : savedTaskScope(history.data)),
    ready: !id || session.taskScopes[key] !== undefined || live !== undefined || history.isSuccess,
    set: (scope: TaskScope) => session.setTaskScope(key, scope),
  }
}

export function useChatSession(): Session {
  const context = useContext(Context)
  if (!context) throw new Error('useChatSession must be used within ChatSessionProvider')
  return context
}

import { useQuery } from '@tanstack/react-query'
import { useNavigate } from '@tanstack/react-router'
import { useCallback, useRef } from 'react'
import { historyQuery, messageQuery, MessageNotFoundError, modelsQuery, summaryQuery } from '../api/queries'
import { errorCode } from '../api/unwrap'
import type { AccountSummaryOut, ChatMessageOut, MailRefOut } from '../api/generated/types.gen'
import { Button, ChatMessage, Chip, Composer, MailReference, Notice } from '../ds'
import { providerLabel } from '../ds/providerLabel'
import { useI18n } from '../i18n/I18n'
import { ModelMenu } from './ModelMenu'
import { TemplateMenu } from '../prompts/TemplateMenu'
import { ChatHeader } from './ChatHeader'
import { ProposalCard } from './ProposalCard'
import { useFollowScroll } from './useFollowScroll'
import { SafeMarkdown } from './SafeMarkdown'
import { CalendarReference, CalendarScope } from './CalendarContext'
import { composerDraftKey, useCalendarScope, useChatSession, useConversationScope, useRestartConversation, useTaskScope, type ComposerMail } from './session'
import { TaskScopeSelector } from './TaskContext'
import { PreferenceContext } from './PreferenceContext'
import { AudioRecorder, supportedAudioFormat } from './AudioRecorder'
import { useAudioCapabilities } from './audio-capabilities'
import { SpeechControls, useSpeechPlayback } from './SpeechPlayback'

type Accounts = AccountSummaryOut[]
// A retry would send the same request and be refused again.
const NEEDS_NEW_CONVERSATION = new Set(['conversation_not_found', 'conversation_scope_change_requires_new', 'context_unavailable', 'context_revoked', 'chat_account_not_granted', 'chat_settings_changed'])

export function ChatComposer({ conversationId, contextMail, contextOccurrenceId, model, promptRevisionId, onSend, autoFocus, onRecordingStart }: { conversationId?: string; contextMail?: ComposerMail; contextOccurrenceId?: string; model?: string; promptRevisionId?: string | null; onSend?: () => void; autoFocus?: boolean; onRecordingStart?: () => void }) {
  const { texts } = useI18n()
  const { state, send, stop, composerTexts, setComposerText, audioDraftLocked, setAudioDraftLocked } = useChatSession()
  const contextMessageId = contextMail?.id
  const { scope, ready } = useConversationScope(conversationId, contextMail)
  const calendar = useCalendarScope(conversationId, contextMessageId)
  const tasks = useTaskScope(conversationId, contextMessageId)
  const stt = useAudioCapabilities()?.stt
  const format = supportedAudioFormat(stt)
  const lockDraft = useCallback((locked: boolean) => {
    if (locked) onRecordingStart?.()
    setAudioDraftLocked(locked)
  }, [onRecordingStart, setAudioDraftLocked])
  const draftKey = composerDraftKey(conversationId, contextMessageId)
  const value = composerTexts[draftKey] ?? ''
  const setValue = (text: string) => setComposerText(draftKey, text)
  const appendTranscript = (text: string) => setComposerText(draftKey, previous =>
    previous ? previous + (previous.endsWith('\n\n') ? '' : previous.endsWith('\n') ? '\n' : '\n\n') + text : text)
  const voiceContext = JSON.stringify([draftKey, contextOccurrenceId, scope, model, promptRevisionId,
    calendar.ids, tasks.scope.source, tasks.scope.account_id, format])
  const busy = state.phase === 'working' || state.phase === 'streaming'
  const calendars = <CalendarScope conversationId={conversationId} messageId={contextMessageId} disabled={busy || audioDraftLocked} />
  return <>{!contextMessageId && calendars}<Composer value={value} locked={audioDraftLocked} onChange={setValue} onSubmit={() => {
    if (busy || audioDraftLocked || !ready || !calendar.ready || !tasks.ready || !value.trim()) return
    onSend?.()
    void send({ text: value, account_id: scope, conversation_id: conversationId, context_message_id: contextMessageId, context_occurrence_id: contextOccurrenceId, calendar_source_ids: calendar.ids, task_source: tasks.scope.source, task_source_account_id: tasks.scope.account_id, model, ...(!conversationId ? { prompt_revision_id: promptRevisionId } : {}) })
  }} onStop={stop} busy={busy} placeholder={contextMessageId ? texts.inbox.mailQuestionPlaceholder : texts.chat.placeholder} autoFocus={autoFocus} controls={<TaskScopeSelector conversationId={conversationId} contextMail={contextMail} disabled={busy || audioDraftLocked} />}
    audioControls={stt && format && <AudioRecorder key={voiceContext} format={format}
      limits={stt.app_limits} disabled={busy || !ready || !calendar.ready || !tasks.ready}
      onLock={lockDraft} onTranscript={appendTranscript} />} />{contextMessageId && calendars}</>
}

type Draft = { onDraft: (id: string) => void; disabled: boolean }
function Reference({ mail, accounts, draft }: { mail: MailRefOut; accounts: Accounts; draft: Draft }) {
  const navigate = useNavigate()
  return <MailReference mail={mail} accountLabel={accounts.filter(account => account.id === mail.account_id).map(providerLabel)[0]} onOpen={() => { void navigate({ to: '/mail/$messageId', params: { messageId: mail.id } }) }} onDraft={() => draft.onDraft(mail.id)} draftDisabled={draft.disabled || !accounts.some(account => account.id === mail.account_id)} />
}
function HistoryReference({ id, accounts, draft }: { id: string; accounts: Accounts; draft: Draft }) {
  const { data } = useQuery({ ...messageQuery(id), retry: (count, error) => !(error instanceof MessageNotFoundError) && count < 2 })
  return data ? <Reference mail={data} accounts={accounts} draft={draft} /> : null
}
// DESIGN.md §9.1: at most three follow-up suggestions, whatever the model sent.
function Suggestions({ items, onSend }: { items: string[]; onSend: (text: string) => void }) {
  return <div className="le-chat-suggestions">{items.slice(0, 3).map(text => <Chip key={text} onClick={() => onSend(text)}>{text}</Chip>)}</div>
}

// The agent saves a proposal while it works and its answer at the end of the turn. Live, the card
// follows the answer; the history shows it there too, so nothing jumps once the history reloads.
export function turnOrder(messages: ChatMessageOut[]): ChatMessageOut[] {
  const ordered: ChatMessageOut[] = []
  let held: ChatMessageOut[] = []
  const flush = () => { ordered.push(...held); held = [] }
  for (const message of messages) {
    if (message.role === 'proposal' || message.role === 'draft') { held.push(message); continue }
    if (message.role === 'user') flush()
    ordered.push(message)
    if (message.role === 'assistant') flush()
  }
  flush()
  return ordered
}

export function Conversation({ conversationId }: { conversationId: string }) {
  const { texts } = useI18n()
  const history = useQuery(historyQuery(conversationId))
  const { data: summary } = useQuery(summaryQuery(true))
  const { data: models = [] } = useQuery(modelsQuery())
  const { state, send, retry, retryWithoutPreferences, audioDraftLocked } = useChatSession()
  const tts = useAudioCapabilities()?.tts
  const speechEnabled = tts?.status === 'available' && tts.formats.includes('audio/mpeg') &&
    typeof Audio !== 'undefined' && typeof URL.createObjectURL === 'function'
  const speech = useSpeechPlayback(conversationId, speechEnabled, audioDraftLocked)
  const { scope, ready } = useConversationScope(conversationId)
  const calendar = useCalendarScope(conversationId)
  const restart = useRestartConversation(conversationId)
  const scrollRef = useRef<HTMLDivElement>(null)
  const { showEnd, scrollToEnd } = useFollowScroll(scrollRef, [history.data, state, conversationId])
  const accounts = summary?.accounts ?? []
  const messages = history.data ?? []
  const grantVersion = summary?.mail_scope_version
  const oldGrant = grantVersion != null && messages.some(message => message.context?.mail_scope_version !== grantVersion)
  const ordered = turnOrder(messages)
  const lastAssistant = messages.findLast(message => message.role === 'assistant')
  // Follow-ups come after the last answer and the cards of its turn.
  let suggestionsAfter = lastAssistant ? ordered.indexOf(lastAssistant) : -1
  while (suggestionsAfter >= 0 && (ordered[suggestionsAfter + 1]?.role === 'proposal' || ordered[suggestionsAfter + 1]?.role === 'draft')) suggestionsAfter += 1
  const live = state.conversationId === conversationId && !(state.messageId && messages.some(message => message.id === state.messageId))
  const userIndex = state.userMessageId ? messages.findIndex(message => message.id === state.userMessageId) : -1
  const savedPartial = (state.phase === 'stopped' || state.phase === 'error') && userIndex >= 0 && messages.slice(userIndex + 1).some(message => message.role === 'assistant')
  const busy = state.phase === 'working' || state.phase === 'streaming'
  // Follow-ups keep the account and calendars the composer shows, like a typed question.
  const submitSuggestion = (text: string) => { if (audioDraftLocked || !ready || !calendar.ready) return; void send({ text, account_id: scope, conversation_id: conversationId, calendar_source_ids: calendar.ids }) }
  // The pencil on a mail card asks for a reply draft to that mail in this conversation, like the button on the open mail.
  const draft: Draft = { onDraft: id => { if (audioDraftLocked || !ready || !calendar.ready) return; void send({ text: texts.mail.draftPrompt, account_id: scope, conversation_id: conversationId, context_message_id: id, calendar_source_ids: calendar.ids }) }, disabled: oldGrant || !ready || !calendar.ready || busy || audioDraftLocked }
  const modelLabel = (id?: string) => id ? models.find(model => model.id === id)?.label ?? id : undefined
  const renderMessage = (message: ChatMessageOut) => {
    if (message.role === 'user') return <ChatMessage role="user">{message.content}</ChatMessage>
    if (message.role === 'proposal' || message.role === 'draft') return <ProposalCard key={message.id} message={message} oldGrant={oldGrant} />
    if (message.role !== 'assistant') return null
    return <>{message.context && <PreferenceContext context={message.context} />}{message.context?.revoked && <Notice tone="info" action={{ label: texts.prompts.restart, onClick: restart }}>{message.context.preferences_enabled ? texts.errors.context_revoked : texts.prompts.removed}</Notice>}<ChatMessage role="assistant" model={modelLabel(message.extras.model)} stopped={message.stopped}><SafeMarkdown text={message.content} /></ChatMessage>
      {speechEnabled && !oldGrant && !message.stopped && !message.context?.revoked && message.content.trim() &&
        <SpeechControls messageId={message.id} player={speech} disabled={audioDraftLocked} />}
      {message.extras.mails?.map(id => <HistoryReference key={id} id={id} accounts={accounts} draft={draft} />)}{message.extras.calendars?.map(ref => <CalendarReference key={ref.occurrence_id} occurrenceId={ref.occurrence_id} sourceId={ref.source_id} />)}</>
  }
  const status = state.status?.code === 'searching' ? texts.status.searching(state.status.count ?? 0) : state.status ? texts.status[state.status.code] : null
  const historyGone = errorCode(history.error instanceof Error ? history.error.cause : history.error) === 'conversation_not_found'
  const newConversation = { label: texts.shell.newConversation, onClick: restart }
  return <div className="le-chat-view"><ChatHeader conversationId={conversationId} modelMenu={<ModelMenu disabled={audioDraftLocked} key={`${conversationId}:model`} conversationId={conversationId} />}><TemplateMenu key={`${conversationId}:template`} conversationId={conversationId} /></ChatHeader><div className="le-chat-messages le-chat-thread" ref={scrollRef}>
    {history.isPending && <p className="le-hint">{texts.chat.loadingHistory}</p>}
    {history.isError && <Notice tone="danger" action={historyGone ? newConversation : { label: texts.chat.retry, onClick: () => { void history.refetch() } }}>{historyGone ? texts.errors.conversation_not_found : texts.chat.historyError}</Notice>}
    {ordered.map((message, index) => <div className="le-chat-entry" id={`message-${message.id}`} key={message.id}>{renderMessage(message)}{index === suggestionsAfter && !live && !oldGrant && <Suggestions items={lastAssistant?.extras.suggestions ?? []} onSend={submitSuggestion} />}</div>)}
    {live && <div className="le-chat-entry">{!savedPartial && <>{!messages.some(message => message.id === state.userMessageId) && <ChatMessage role="user">{state.request?.text}</ChatMessage>}{status && <div className="le-working" role="status">{status}</div>}<div aria-hidden={busy || undefined}><ChatMessage role="assistant" model={modelLabel(state.model)} streaming={busy} stopped={state.phase === 'stopped'} live={false}><SafeMarkdown text={state.text} /></ChatMessage></div></>}
      {state.phase === 'stopped' && <div className="le-chat-retry"><Button variant="ghost" onClick={() => { void retry() }}>{texts.chat.askAgain}</Button></div>}
      {state.phase === 'error' && <Notice tone="danger" action={state.errorCode === 'preferences_unavailable' ? { label: texts.preferences.continueWithout, onClick: () => { void retryWithoutPreferences() } } : state.errorCode && NEEDS_NEW_CONVERSATION.has(state.errorCode) ? newConversation : { label: texts.chat.retry, onClick: () => { void retry() } }}>{state.errorCode === 'conversation_scope_change_requires_new' ? texts.taskChat.scopeConflict : texts.errors[state.errorCode ?? 'internal']}</Notice>}
      {state.phase === 'done' && <>{state.calendars?.map(ref => <CalendarReference key={ref.occurrence_id} occurrenceId={ref.occurrence_id} sourceId={ref.source_id} />)}{state.mails.map(mail => <Reference key={mail.id} mail={mail} accounts={accounts} draft={draft} />)}{state.proposal && <ProposalCard key={state.proposal.id} message={state.proposal} oldGrant={oldGrant} />}{!oldGrant && <Suggestions items={state.suggestions} onSend={submitSuggestion} />}</>}
    </div>}
    <div className="le-sr" aria-live="polite">{state.conversationId === conversationId && state.phase === 'done' ? state.text : ''}</div>
  </div>{showEnd && <div className="le-chat-end"><Button variant="secondary" onClick={scrollToEnd}>{texts.chat.toEnd}</Button></div>}<div className="le-chat-composer">{oldGrant ? <Notice tone="info" action={{ label: texts.prompts.restart, onClick: restart }}>{texts.chatAccounts.restart}</Notice> : <ChatComposer conversationId={conversationId} onRecordingStart={speech.stop} autoFocus={busy && state.conversationId === conversationId} />}</div></div>
}

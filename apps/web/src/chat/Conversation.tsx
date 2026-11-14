import { useQuery } from '@tanstack/react-query'
import { useNavigate } from '@tanstack/react-router'
import { useState } from 'react'
import { historyQuery, messageQuery, modelsQuery, summaryQuery } from '../api/queries'
import type { AccountSummaryOut, ChatMessageOut, MailRefOut } from '../api/generated/types.gen'
import { Button, ChatMessage, Chip, Composer, MailReference, Notice } from '../ds'
import { de } from '../i18n/de'
import { ProposalCard } from './ProposalCard'
import { SafeMarkdown } from './SafeMarkdown'
import { useChatSession } from './session'

type Accounts = AccountSummaryOut[]

export function ChatComposer({ conversationId, contextMessageId, onSend }: { conversationId?: string; contextMessageId?: string; onSend?: () => void }) {
  const { data: summary } = useQuery(summaryQuery())
  const { state, send, stop } = useChatSession()
  const [value, setValue] = useState('')
  const [scope, setScope] = useState<string | null>(null)
  const busy = state.phase === 'working' || state.phase === 'streaming'
  return <Composer value={value} onChange={setValue} onSubmit={() => {
    if (busy || !value.trim()) return
    onSend?.()
    void send({ text: value, account_id: scope, conversation_id: conversationId, context_message_id: contextMessageId })
    setValue('')
  }} onStop={stop} busy={busy} scope={scope} accounts={(summary?.accounts ?? []).map(account => ({ id: account.id, label: account.display_name }))} onScopeChange={setScope} placeholder={de.chat.placeholder} />
}

function Reference({ mail, accounts }: { mail: MailRefOut; accounts: Accounts }) {
  const navigate = useNavigate()
  return <MailReference mail={mail} accountLabel={accounts.find(account => account.id === mail.account_id)?.display_name} onOpen={() => { void navigate({ href: `/mail?message=${encodeURIComponent(mail.id)}` }) }} />
}
function HistoryReference({ id, accounts }: { id: string; accounts: Accounts }) {
  const { data } = useQuery(messageQuery(id))
  return data ? <Reference mail={data} accounts={accounts} /> : null
}
function Suggestions({ items, onSend }: { items: string[]; onSend: (text: string) => void }) {
  return <div className="le-chat-suggestions">{items.map(text => <Chip key={text} onClick={() => onSend(text)}>{text}</Chip>)}</div>
}

export function Conversation({ conversationId }: { conversationId: string }) {
  const history = useQuery(historyQuery(conversationId))
  const { data: summary } = useQuery(summaryQuery())
  const { data: models = [] } = useQuery(modelsQuery())
  const { state, send, retry } = useChatSession()
  const accounts = summary?.accounts ?? []
  const messages = history.data ?? []
  const lastAssistant = messages.findLast(message => message.role === 'assistant')
  const live = state.conversationId === conversationId && !(state.messageId && messages.some(message => message.id === state.messageId))
  const busy = state.phase === 'working' || state.phase === 'streaming'
  const submitSuggestion = (text: string) => { void send({ text, conversation_id: conversationId }) }
  const modelLabel = (id?: string) => id ? models.find(model => model.id === id)?.label ?? id : undefined
  const renderMessage = (message: ChatMessageOut) => {
    if (message.role === 'user') return <ChatMessage role="user">{message.content}</ChatMessage>
    if (message.role === 'proposal' || message.role === 'draft') return <ProposalCard key={message.id} message={message} />
    if (message.role !== 'assistant') return null
    return <><ChatMessage role="assistant" model={modelLabel(message.extras.model)} stopped={message.stopped}><SafeMarkdown text={message.content} /></ChatMessage>{message.extras.mails?.map(id => <HistoryReference key={id} id={id} accounts={accounts} />)}{message.id === lastAssistant?.id && !live && <Suggestions items={message.extras.suggestions ?? []} onSend={submitSuggestion} />}</>
  }
  const status = state.status?.code === 'searching' ? de.status.searching(state.status.count ?? 0) : state.status ? de.status[state.status.code] : null
  const liveModel = modelLabel(lastAssistant?.extras.model) ?? models.find(model => model.is_default)?.label
  return <div className="le-chat-view"><div className="le-chat-messages">
    {history.isPending && <p className="le-hint">{de.chat.loadingHistory}</p>}
    {history.isError && <Notice tone="danger" action={{ label: de.chat.retry, onClick: () => { void history.refetch() } }}>{de.chat.historyError}</Notice>}
    {messages.map(message => <div className="le-chat-entry" key={message.id}>{renderMessage(message)}</div>)}
    {live && <div className="le-chat-entry"><ChatMessage role="user">{state.request?.text}</ChatMessage><div aria-hidden={busy || undefined}><ChatMessage role="assistant" model={liveModel} streaming={busy} stopped={state.phase === 'stopped'}>{status && <p>{status}</p>}<SafeMarkdown text={state.text} /></ChatMessage></div>
      {state.phase === 'stopped' && <Button variant="ghost" onClick={() => { void retry() }}>{de.chat.askAgain}</Button>}
      {state.phase === 'error' && <Notice tone="danger" action={{ label: de.chat.retry, onClick: () => { void retry() } }}>{de.errors[state.errorCode ?? 'internal']}</Notice>}
      {state.phase === 'done' && <>{state.mails.map(mail => <Reference key={mail.id} mail={mail} accounts={accounts} />)}{state.proposal && <ProposalCard key={state.proposal.id} message={state.proposal} />}<Suggestions items={state.suggestions} onSend={submitSuggestion} /></>}
    </div>}
    <div className="sr-only" aria-live="polite">{state.conversationId === conversationId && state.phase === 'done' ? state.text : ''}</div>
  </div><div className="le-chat-composer"><ChatComposer conversationId={conversationId} /></div></div>
}

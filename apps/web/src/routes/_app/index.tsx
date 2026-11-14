import { useQuery } from '@tanstack/react-query'
import { createFileRoute, redirect, useNavigate, useSearch } from '@tanstack/react-router'
import { useEffect, useState } from 'react'
import { messageQuery, summaryQuery } from '../../api/queries'
import { ChatComposer } from '../../chat/Conversation'
import { ModelMenu } from '../../chat/ModelMenu'
import { ChatHeader } from '../../chat/ChatHeader'
import { useChatSession } from '../../chat/session'
import { Button as ActionButton, IconButton, MailReference, Notice, QuickAction } from '../../ds'
import { providerLabel } from '../../ds/providerLabel'
import { de } from '../../i18n/de'
import { formatTime } from '../../i18n/format'
export const Route = createFileRoute('/_app/')({
  staticData: { landing: true },
  validateSearch: (search: Record<string, unknown>): { about?: string } => typeof search.about === 'string' ? { about: search.about } : {},
  beforeLoad: ({ context }) => {
    const to = context.landingPath()
    if (to !== undefined && to !== '' && to !== '/') {
      // oxlint-disable-next-line typescript/only-throw-error -- TanStack Router's redirect is thrown, by design
      throw redirect({ href: to })
    }
  },
  component: Greeting,
})
function Greeting() {
  const { state, send, retry, scope } = useChatSession()
  const navigate = useNavigate()
  const search = useSearch({ strict: false })
  const about = typeof search.about === 'string' ? search.about : undefined
  const summary = useQuery(summaryQuery())
  const reference = useQuery({ ...messageQuery(about ?? ''), enabled: Boolean(about) })
  const [started, setStarted] = useState(false)
  const busy = state.phase === 'working' || state.phase === 'streaming'
  const quickSend = (text: string) => {
    if (busy) return
    setStarted(true)
    void send({ text, account_id: scope, context_message_id: about })
  }
  useEffect(() => {
    if (started && state.conversationId) {
      setStarted(false)
      void navigate({ to: '/chat/$conversationId', params: { conversationId: state.conversationId } })
    }
  }, [started, state.conversationId, navigate])
  const data = summary.data
  return <div className="le-chat-view"><ChatHeader><ModelMenu /></ChatHeader><div className="le-chat-messages le-chat-thread le-chat-start-scroll"><div className="le-chat-start"><h1 className="display le-greeting">{de.chat.greetingFirst}<br /><span>{de.chat.greetingSecond}</span></h1>
    {started && state.phase === 'error' && !state.conversationId && <Notice tone="danger" action={{ label: de.chat.retry, onClick: () => { void retry() } }}>{de.errors[state.errorCode ?? 'internal']}</Notice>}
    {summary.isPending && <p className="le-hint">{de.chat.loadingSummary}</p>}
    {summary.isError && <Notice tone="danger" action={{ label: de.chat.retry, onClick: () => { void summary.refetch() } }}>{de.chat.summaryError}</Notice>}
    {data && (data.accounts.length === 0 ? <><Notice tone="info">{de.chat.noAccounts}</Notice><ActionButton variant="primary" onClick={() => { void navigate({ href: '/accounts' }) }}>{de.accounts.connect}</ActionButton></> : <><p className="le-hint">{de.chat.stand(data.unread_total, data.accounts.length, data.last_sync_at ? formatTime(new Date(data.last_sync_at)) : undefined)}</p><div className="le-chat-quick-actions">
      <QuickAction icon="mail-open" title={de.quickActions.unread.title} sub={de.quickActions.unread.subtitle(data.unread_total)} onClick={() => quickSend(de.quickActions.unread.prompt)} />
      <QuickAction icon="flag" title={de.quickActions.priority.title} sub={de.quickActions.priority.subtitle} onClick={() => quickSend(de.quickActions.priority.prompt)} />
      <QuickAction icon="newspaper" title={de.quickActions.newsletters.title} sub={de.quickActions.newsletters.subtitle(data.newsletter_senders)} onClick={() => quickSend(de.quickActions.newsletters.prompt)} />
      <QuickAction icon="clock" title={de.quickActions.dueToday.title} sub={de.quickActions.dueToday.subtitle} onClick={() => quickSend(de.quickActions.dueToday.prompt)} />
    </div></>)}
  </div></div>{data && data.accounts.length > 0 && <div className="le-chat-composer">{about && <div className="le-chat-reference">{reference.isPending && <span className="le-hint">{de.chat.loadingReference}</span>}{reference.isError && <Notice tone="danger" action={{ label: de.chat.retry, onClick: () => { void reference.refetch() } }}>{de.chat.referenceError}</Notice>}{reference.data && <MailReference mail={reference.data} accountLabel={data.accounts.filter(account => account.id === reference.data?.account_id).map(providerLabel)[0]} onOpen={() => { void navigate({ to: '/mail/$messageId', params: { messageId: reference.data.id } }) }} />}<IconButton icon="x" label={de.chat.removeReference} onClick={() => { void navigate({ to: '/', search: { about: undefined } }) }} /></div>}<ChatComposer contextMessageId={about} onSend={() => setStarted(true)} /></div>}</div>
}

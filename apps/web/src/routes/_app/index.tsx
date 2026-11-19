import { useQuery, useQueryClient } from '@tanstack/react-query'
import { createFileRoute, redirect, useNavigate, useSearch } from '@tanstack/react-router'
import { useEffect, useState } from 'react'
import { calendarSourcesQuery, messageQuery, modelsQuery, summaryQuery } from '../../api/queries'
import { CalendarReference } from '../../chat/CalendarContext'
import { ChatComposer } from '../../chat/Conversation'
import { ModelMenu } from '../../chat/ModelMenu'
import { TemplateMenu } from '../../prompts/TemplateMenu'
import { ChatHeader } from '../../chat/ChatHeader'
import { useChatSession } from '../../chat/session'
import { Button as ActionButton, IconButton, MailReference, Notice, QuickAction } from '../../ds'
import { providerLabel } from '../../ds/providerLabel'
import { useI18n } from '../../i18n/I18n'
import { formatTime } from '../../i18n/format'
export const Route = createFileRoute('/_app/')({
  staticData: { landing: true },
  validateSearch: (search: Record<string, unknown>): { about?: string; calendarAbout?: string } => ({ about: typeof search.about === 'string' ? search.about : undefined, calendarAbout: typeof search.calendarAbout === 'string' ? search.calendarAbout : undefined }),
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
  const { texts, locale } = useI18n()
  const client = useQueryClient()
  const { state, send, retry, retryWithoutPreferences, scope } = useChatSession()
  const navigate = useNavigate()
  const search = useSearch({ strict: false })
  const calendarAbout = typeof search.calendarAbout === 'string' ? search.calendarAbout : undefined
  const about = typeof search.about === 'string' ? search.about : undefined
  const summary = useQuery(summaryQuery())
  const calendars = useQuery(calendarSourcesQuery())
  const reference = useQuery({ ...messageQuery(about ?? ''), enabled: Boolean(about) })
  const [started, setStarted] = useState(false)
  // The model chosen in the chip rides along with the first message and becomes the model of the new conversation.
  const [model, setModel] = useState<string>()
  const [revision, setRevision] = useState<string | null>(null)
  const busy = state.phase === 'working' || state.phase === 'streaming'
  const quickSend = (text: string) => {
    if (busy) return
    setStarted(true)
    void send({ text, account_id: scope, context_message_id: about, context_occurrence_id: calendarAbout, model, prompt_revision_id: revision })
  }
  const modelGone = started && state.phase === 'error' && !state.conversationId && state.errorCode === 'model_unknown'
  useEffect(() => {
    if (modelGone) {
      setModel(undefined)
      void client.invalidateQueries({ queryKey: modelsQuery().queryKey })
    }
  }, [modelGone, client])
  useEffect(() => {
    if (started && state.conversationId) {
      setStarted(false)
      void navigate({ to: '/chat/$conversationId', params: { conversationId: state.conversationId } })
    }
  }, [started, state.conversationId, navigate])
  const data = summary.data
  const turnError = started && state.phase === 'error' && !state.conversationId
  const mail = reference.data
  const account = mail && data?.accounts.find(item => item.id === mail.account_id)
  return <div className={about ? 'le-chat-view le-chat-view--mail-question' : 'le-chat-view'}>
    <ChatHeader modelMenu={<ModelMenu model={model} onChange={setModel} />}>
      <TemplateMenu revision={revision} onChange={setRevision} />
    </ChatHeader>
    {about && <h1 className="le-sr">{texts.mail.askInChat}</h1>}
    {(!about || turnError || summary.isError) && <div className="le-chat-messages le-chat-thread le-chat-start-scroll"><div className="le-chat-start">
      {!about && <h1 className="display le-greeting">{texts.chat.greetingFirst}<br /><span>{texts.chat.greetingSecond}</span></h1>}
      {turnError && <Notice tone="danger" action={state.errorCode === 'preferences_unavailable' ? { label: texts.preferences.continueWithout, onClick: () => { void retryWithoutPreferences() } } : modelGone ? undefined : { label: texts.chat.retry, onClick: () => { void retry() } }}>{texts.errors[state.errorCode ?? 'internal']}</Notice>}
      {summary.isPending && <p className="le-hint">{texts.chat.loadingSummary}</p>}
      {summary.isError && <Notice tone="danger" action={{ label: texts.chat.retry, onClick: () => { void summary.refetch() } }}>{texts.chat.summaryError}</Notice>}
      {!about && data && (data.accounts.length === 0 ? <><Notice tone="info">{texts.chat.noAccounts}</Notice><ActionButton variant="primary" onClick={() => { void navigate({ href: '/accounts' }) }}>{texts.accounts.connect}</ActionButton></> : <><p className="le-hint">{texts.chat.stand(data.unread_total, data.accounts.length, data.last_sync_at ? formatTime(new Date(data.last_sync_at), undefined, locale) : undefined)}</p><div className="le-chat-quick-actions">
        <QuickAction icon="mail-open" title={texts.quickActions.unread.title} sub={texts.quickActions.unread.subtitle(data.unread_total)} onClick={() => quickSend(texts.quickActions.unread.prompt)} />
        <QuickAction icon="flag" title={texts.quickActions.priority.title} sub={texts.quickActions.priority.subtitle} onClick={() => quickSend(texts.quickActions.priority.prompt)} />
        <QuickAction icon="newspaper" title={texts.quickActions.newsletters.title} sub={texts.quickActions.newsletters.subtitle(data.newsletter_senders)} onClick={() => quickSend(texts.quickActions.newsletters.prompt)} />
        <QuickAction icon="clock" title={texts.quickActions.dueToday.title} sub={texts.quickActions.dueToday.subtitle} onClick={() => quickSend(texts.quickActions.dueToday.prompt)} />
      </div></>)}
    </div></div>}
    {(about || !!data?.accounts.length || calendars.data?.some(source => source.is_active) || calendarAbout) && <div className="le-chat-composer">
      {calendarAbout && <div className="le-chat-reference"><CalendarReference occurrenceId={calendarAbout} /><IconButton icon="x" label={texts.calendar.removeReference} onClick={() => { void navigate({ to: '/', search: { about } }) }} /></div>}
      {about && <div className="le-chat-reference">
        {reference.isPending && <span className="le-hint">{texts.chat.loadingReference}</span>}
        {reference.isError && <Notice tone="danger" action={{ label: texts.chat.retry, onClick: () => { void reference.refetch() } }}>{texts.chat.referenceError}</Notice>}
        {mail && <MailReference compact mail={mail} accountLabel={account && providerLabel(account)} onOpen={() => { void navigate({ to: '/mail/$messageId', params: { messageId: mail.id } }) }} />}
        <IconButton icon="x" label={texts.chat.removeReference} onClick={() => { void navigate({ to: '/', search: { about: undefined } }) }} />
      </div>}
      {(!about || (reference.isSuccess && mail?.id === about)) && <ChatComposer key={about} autoFocus={Boolean(about)} contextMail={mail} contextOccurrenceId={calendarAbout} model={model} promptRevisionId={revision} onSend={() => setStarted(true)} />}
    </div>}
  </div>
}

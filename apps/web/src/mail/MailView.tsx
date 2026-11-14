import { useQuery, useQueryClient, type InfiniteData } from '@tanstack/react-query'
import { useNavigate, useRouter, useSearch } from '@tanstack/react-router'
import { useEffect, useRef, useState } from 'react'
import type { MessagePageOut } from '../api/generated/types.gen'
import { MessageNotFoundError, messageQuery, messagesInfiniteQuery, summaryQuery } from '../api/queries'
import { useChatSession } from '../chat/session'
import { Avatar, Button, IconButton, Menu, Notice, Tag, Tooltip } from '../ds'
import { de } from '../i18n/de'
import { formatBytes, formatMailTime } from '../i18n/format'
import { useBreakpoint, useCoarsePointer } from '../shell/useBreakpoint'
import { toMessageFilters, type InboxSearch } from './filters'
import { InsightBox } from './InsightBox'
import { useMailActionsContext } from './useMailActions'

export function MailView({ id }: { id: string }) {
  const client = useQueryClient(), router = useRouter(), navigate = useNavigate()
  const search = useSearch({ strict: false }) as InboxSearch
  const breakpoint = useBreakpoint(), coarse = useCoarsePointer()
  const split = breakpoint === 'desktop' || breakpoint === 'wide'
  const message = useQuery({ ...messageQuery(id), retry: (count, error) => !(error instanceof MessageNotFoundError) && count < 2 })
  const summary = useQuery(summaryQuery())
  const { run } = useMailActionsContext()
  const { state, send, retry } = useChatSession()
  const [started, setStarted] = useState(false)
  const opened = useRef(new Set<string>())
  const busy = state.phase === 'working' || state.phase === 'streaming'
  const data = message.data
  useEffect(() => {
    if (!data || opened.current.has(id)) return
    opened.current.add(id)
    if (!data.is_read) void run(id, 'mark_read', { silent: true })
  }, [id, data, run])
  useEffect(() => {
    if (started && state.conversationId) {
      setStarted(false)
      void navigate({ to: '/chat/$conversationId', params: { conversationId: state.conversationId } })
    }
  }, [started, state.conversationId, navigate])
  const back = () => { void navigate({ to: '/mail', search }) }
  const start = (text: string) => {
    if (busy) return
    setStarted(true)
    void send({ text, context_message_id: id })
  }
  const remove = (kind: 'archive' | 'trash') => {
    const list = client.getQueryData<InfiniteData<MessagePageOut>>(messagesInfiniteQuery(toMessageFilters(search)).queryKey)
    const items = list?.pages.flatMap(page => page.items) ?? []
    const index = items.findIndex(item => item.id === id)
    const next = split && index >= 0 ? items[index + 1]?.id ?? items[index - 1]?.id : undefined
    const destination = next ? `/mail/${encodeURIComponent(next)}` : '/mail'
    if (next) void navigate({ to: '/mail/$messageId', params: { messageId: next }, search })
    else back()
    void run(id, kind).then(restored => {
      if (split && restored && router.state.location.pathname === destination) void navigate({ to: '/mail/$messageId', params: { messageId: id }, search: true })
    })
  }
  const ask = () => { void navigate({ to: '/', search: { about: id } }) }
  const iconSize = !split || coarse ? 'lg' : 'md'
  const actions = data && <>
    <IconButton label={de.controls.archive} icon="archive" size={iconSize} shortcut={split ? 'E' : undefined} onClick={() => remove('archive')} />
    <IconButton label={data.is_read ? de.controls.markUnread : de.controls.markRead} icon="mail-open" size={iconSize} shortcut={split ? 'U' : undefined} onClick={() => { void run(id, data.is_read ? 'mark_unread' : 'mark_read') }} />
    <IconButton label={de.controls.trash} icon="trash-2" size={iconSize} tone="danger" shortcut={split ? 'Entf' : undefined} onClick={() => remove('trash')} />
    {data.can_unsubscribe && <Menu trigger={props => <IconButton {...props} label={de.mail.more} icon="more-horizontal" size={iconSize} disabled={busy} />} items={[{ label: de.mail.unsubscribe, icon: 'newspaper', onSelect: () => start(de.mail.unsubscribePrompt) }]} />}
  </>
  const chatButtons = <>
    <Tooltip content={de.mail.askTip}><Button variant="secondary" icon={split ? undefined : 'message-circle'} className={split ? 'le-btn--sm' : ''} disabled={busy} onClick={ask}>{de.mail.askInChat}</Button></Tooltip>
    <Tooltip content={de.mail.draftTip}><Button variant="primary" icon={split ? undefined : 'pencil'} className={split ? 'le-btn--sm' : ''} disabled={busy} onClick={() => start(de.mail.draftPrompt)}>{de.mail.draftReply}</Button></Tooltip>
  </>
  const account = summary.data?.accounts.find(item => item.id === data?.account_id)
  return <div className="le-mail-view">
    <div className="le-topbar le-mail-topbar">{!split && <IconButton label={de.mail.back} icon="arrow-left" size="lg" onClick={back} />}{!split && <span className="le-grow" />}{actions}{split && <><span className="le-grow" />{data && chatButtons}</>}</div>
    <div className="le-mail-scroll">
      {started && state.phase === 'error' && !state.conversationId && <Notice tone="danger" action={{ label: de.chat.retry, onClick: () => { void retry() } }}>{de.errors[state.errorCode ?? 'internal']}</Notice>}
      {message.isPending && <><span className="le-sr" role="status">{de.mail.loading}</span><div className="le-mail-placeholder" aria-hidden="true"><div className="le-mail-placeholder-head"><span /><div><span /><span /></div></div><span /><span /><span /><span /></div></>}
      {message.isError && <div className="le-mail-error">{message.error instanceof MessageNotFoundError ? <Notice tone="danger" action={{ label: de.mail.toInbox, onClick: back }}>{de.proposalErrors.item_gone}</Notice> : <><Notice tone="danger" action={{ label: de.chat.retry, onClick: () => { void message.refetch() } }}>{de.mail.loadError}</Notice><Button variant="secondary" className="le-mail-to-inbox" onClick={back}>{de.mail.toInbox}</Button></>}</div>}
      {data && <article className="le-mail-article"><h1 className="title">{data.subject}</h1><div className="le-mail-header"><Avatar name={data.sender_name || data.sender_address} address={data.sender_address} colorIndex={data.color_index} size="lg" /><div className="le-mail-sender"><div className="body-strong">{data.sender_name || data.sender_address}</div>{breakpoint !== 'mobile' && <div className="small le-muted le-mail-address">{data.to.length ? de.mail.addressTo(data.sender_address, data.to.join(', ')) : data.sender_address}</div>}</div>{account && <Tag tone="on-surface" dot={data.color_index}>{account.display_name}</Tag>}{data.internal_date && <time className="small le-muted le-num" dateTime={data.internal_date}>{formatMailTime(new Date(data.internal_date), new Date())}</time>}</div>
        <InsightBox id={id} onFollowup={start} />
        {data.body_text && <div className="le-mail-text body">{data.body_text}</div>}
        {data.attachments.length > 0 && <div className="le-mail-attachments">{data.attachments.map((attachment, index) => <Tag key={index} icon="paperclip">{de.mail.attachment(attachment.name, formatBytes(attachment.size))}</Tag>)}</div>}
      </article>}
    </div>
    {!split && data && <div className="le-mail-bottom">{chatButtons}</div>}
  </div>
}

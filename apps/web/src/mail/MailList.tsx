import { useInfiniteQuery, useQuery, useQueryClient } from '@tanstack/react-query'
import { useLocation, useNavigate, useParams, useRouter, useSearch } from '@tanstack/react-router'
import { useEffect, useRef, useState } from 'react'
import { mailSyncAll } from '../api/generated/sdk.gen'
import type { MessageListItemOut } from '../api/generated/types.gen'
import { messagesInfiniteQuery, summaryQuery } from '../api/queries'
import { Chip, IconButton, MailRow, Menu, Notice, TextField } from '../ds'
import { de } from '../i18n/de'
import { formatTime } from '../i18n/format'
import { useBreakpoint, useCoarsePointer } from '../shell/useBreakpoint'
import { hasActiveFilters, toMessageFilters, type InboxSearch } from './filters'
import { groupByDay } from './groups'
import { useInboxKeys } from './useInboxKeys'
import { useMailActionsContext } from './useMailActions'

export function MailList({ onOpen }: { onOpen(id: string): void }) {
  const search = useSearch({ strict: false }) as InboxSearch
  const { messageId } = useParams({ strict: false }) as { messageId?: string }
  const location = useLocation()
  const navigate = useNavigate()
  const router = useRouter()
  const client = useQueryClient()
  const breakpoint = useBreakpoint(), coarse = useCoarsePointer()
  const summary = useQuery(summaryQuery())
  const messages = useInfiniteQuery(messagesInfiniteQuery(toMessageFilters(search)))
  const { run, undo, notify, toast } = useMailActionsContext()
  const [localSelected, setLocalSelected] = useState<string | undefined>()
  const [searchOpen, setSearchOpen] = useState(Boolean(search.q))
  const [value, setValue] = useState(search.q ?? '')
  const [syncing, setSyncing] = useState(false)
  const searchRef = useRef<HTMLDivElement>(null), sentinel = useRef<HTMLDivElement>(null)
  const rowRefs = useRef(new Map<string, HTMLLIElement>())
  const selected = messageId ?? localSelected
  const items = messages.data?.pages.flatMap(page => page.items) ?? []
  const selectedIndex = items.findIndex(item => item.id === selected)
  const changeSearch = (change: Partial<InboxSearch>) => { void navigate({ to: '.', search: previous => ({ ...previous, ...change }), replace: true }) }

  useEffect(() => { setValue(search.q ?? ''); if (search.q) setSearchOpen(true) }, [search.q])
  useEffect(() => {
    const trimmed = value.trim() || undefined
    if (trimmed === search.q) return
    const id = setTimeout(() => changeSearch({ q: trimmed }), 300)
    return () => clearTimeout(id)
  }, [value, search.q])
  useEffect(() => { if (searchOpen) searchRef.current?.querySelector('input')?.focus() }, [searchOpen])
  useEffect(() => { if (selected) rowRefs.current.get(selected)?.scrollIntoView?.({ block: 'nearest' }) }, [selected])
  useEffect(() => {
    const node = sentinel.current
    if (!node || typeof IntersectionObserver === 'undefined') return
    const observer = new IntersectionObserver(entries => {
      if (entries.some(entry => entry.isIntersecting) && messages.hasNextPage && !messages.isFetchingNextPage) void messages.fetchNextPage()
    }, { rootMargin: '200px' })
    observer.observe(node)
    return () => observer.disconnect()
  }, [messages.hasNextPage, messages.isFetchingNextPage, messages.fetchNextPage])

  const remove = (mail: MessageListItemOut, kind: 'archive' | 'trash') => {
    const moved = selected === mail.id
    const next = items[selectedIndex + 1]?.id ?? items[selectedIndex - 1]?.id
    if (moved) {
      setLocalSelected(next)
      if (messageId) {
        if (next) onOpen(next)
        else void navigate({ href: `/mail${location.searchStr}` })
      }
    }
    void run(mail.id, kind).then(restored => {
      if (!restored || !moved) return
      if (!messageId) setLocalSelected(current => current === next ? mail.id : current)
      else {
        const destination = next ? `/mail/${encodeURIComponent(next)}` : '/mail'
        if (router.state.location.pathname === destination) void navigate({ href: `/mail/${encodeURIComponent(mail.id)}${router.state.location.searchStr}` })
      }
    })
  }
  const toggleRead = (mail: MessageListItemOut) => { void run(mail.id, mail.is_read ? 'mark_unread' : 'mark_read') }
  const current = items[selectedIndex]
  const select = (id: string | undefined) => {
    if (messageId && id) onOpen(id)
    else if (!messageId) setLocalSelected(id)
  }
  useInboxKeys({
    onNext: () => select(items[Math.min(selectedIndex + 1, items.length - 1)]?.id),
    onPrev: () => select(items[Math.max(selectedIndex - 1, 0)]?.id),
    onOpen: () => { if (current) onOpen(current.id) },
    onArchive: () => { if (current) remove(current, 'archive') },
    onToggleRead: () => { if (current) toggleRead(current) },
    onTrash: () => { if (current) remove(current, 'trash') },
  })
  const refresh = async () => {
    if (syncing) return
    setSyncing(true)
    try {
      const result = await mailSyncAll({ body: {} })
      if (result.error || !result.response?.ok) throw new Error('sync failed')
      void client.invalidateQueries({ queryKey: ['summary'] }); void client.invalidateQueries({ queryKey: ['messages'] })
    } catch { notify(de.inbox.refreshError) } finally { setSyncing(false) }
  }
  const buttons = <><IconButton className="le-inbox-control" icon="search" label={de.inbox.search} tip={de.inbox.searchTip} size={breakpoint === 'mobile' || coarse ? 'lg' : 'md'} onClick={() => { setSearchOpen(true); searchRef.current?.querySelector('input')?.focus() }} /><IconButton className="le-inbox-control" icon="refresh-cw" label={de.inbox.refresh} tip={de.inbox.refreshTip} size={breakpoint === 'mobile' || coarse ? 'lg' : 'md'} disabled={syncing} onClick={() => { void refresh() }} /></>
  const time = summary.data?.last_sync_at ? formatTime(new Date(summary.data.last_sync_at)) : undefined
  const accounts = summary.data?.accounts ?? []
  const accountLabel = accounts.find(account => account.id === search.account?.[0])?.display_name ?? de.controls.allAccounts
  const groups = groupByDay(items, new Date())
  return <>
    {breakpoint !== 'mobile' && <div className="le-topbar"><h1 className="le-crumb">{de.inbox.title}</h1>{time && <small className="le-muted le-num">{de.inbox.stand(time)}</small>}<span className="le-grow" />{buttons}</div>}
    <div className="le-inbox-filters"><Menu trigger={props => <Chip {...props} quiet>{accountLabel}</Chip>} items={[{ label: de.controls.allAccounts, onSelect: () => changeSearch({ account: undefined }) }, ...accounts.map(account => ({ label: account.display_name, onSelect: () => changeSearch({ account: [account.id] }) }))]} />
      {(['unread', 'important', 'attachments'] as const).map(key => <Chip key={key} pressed={Boolean(search[key])} quiet={!search[key]} onClick={() => changeSearch({ [key]: search[key] ? undefined : true })}>{de.inbox[key]}</Chip>)}
    </div>
    {breakpoint === 'mobile' && <div className="le-inbox-mobile-status"><small className="le-muted le-num">{de.inbox.unreadStand(summary.data?.unread_total ?? 0, time)}</small><span className="le-grow" />{buttons}</div>}
    {searchOpen && <div className="le-inbox-search" ref={searchRef}><TextField label={de.inbox.search} type="search" placeholder={de.inbox.searchPlaceholder} value={value} onChange={event => setValue(event.target.value)} onKeyDown={event => { if (event.key === 'Escape') { setValue(''); setSearchOpen(false); changeSearch({ q: undefined }) } }} /></div>}
    <div className="le-inbox-scroll">
      {messages.isPending && <><span className="le-sr" role="status">{de.inbox.loading}</span><div aria-hidden="true">{Array.from({ length: 6 }, (_, i) => <div key={i} className="le-mailrow le-mailrow--placeholder"><span /><span /></div>)}</div></>}
      {messages.isError && !messages.data && <Notice tone="danger" action={{ label: de.chat.retry, onClick: () => { void messages.refetch() } }}>{de.inbox.loadError}</Notice>}
      {messages.data && !items.length && <p className="le-hint">{hasActiveFilters(search) ? de.inbox.emptyFiltered : de.inbox.empty}</p>}
      {groups.map(group => <div key={group.label}><div className="le-side-label">{group.label}</div><ul className="le-maillist" aria-label={group.label}>{group.items.map(mail => <li key={mail.id} ref={node => { if (node) rowRefs.current.set(mail.id, node); else rowRefs.current.delete(mail.id) }}><MailRow mail={mail} selected={selected === mail.id} coarse={coarse} accountLabel={accounts.find(account => account.id === mail.account_id)?.display_name} onOpen={() => { setLocalSelected(mail.id); onOpen(mail.id) }} onArchive={() => remove(mail, 'archive')} onToggleRead={() => toggleRead(mail)} onTrash={() => remove(mail, 'trash')} /></li>)}</ul></div>)}
      <div ref={sentinel} />{messages.isFetchingNextPage && <p className="le-hint">{de.inbox.loadingMore}</p>}
    </div>
    {toast && <div className="le-inbox-toast"><Notice tone={toast.tone} action={toast.undoable ? { label: de.proposal.undo, onClick: () => { void undo() } } : undefined}><span>{toast.text}</span></Notice></div>}
  </>
}

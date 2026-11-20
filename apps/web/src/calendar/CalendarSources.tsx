// i18n-exempt: CSS classes, query keys and dialog roles.
import { useId, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { calendarSourcesQuery } from '../api/queries'
import { calendarSourceDelete, calendarSourceSync, calendarSourceUpdate } from '../api/generated/sdk.gen'
import type { SourceOut } from '../api/generated/types.gen'
import { Button, Notice } from '../ds'
import { useFocusTrap } from '../ds/useFocusTrap'
import { useI18n } from '../i18n/I18n'
import { SourceStatus } from './CalendarPage'
import { CalendarSetup, FeedSetup } from './FeedSetup'

function RemoveSource({ source, close, removed }: { source: SourceOut; close: () => void; removed: () => Promise<void> }) {
  const { texts } = useI18n()
  const [pending, setPending] = useState(false), [error, setError] = useState(false)
  const busy = useRef(false), title = useId()
  const dismiss = () => { if (!busy.current) close() }
  const ref = useFocusTrap(true, dismiss)
  const remove = async () => {
    if (busy.current) return
    busy.current = true; setPending(true); setError(false)
    try {
      const result = await calendarSourceDelete({ path: { source_id: source.id } })
      if (result.error || !result.response?.ok) throw new Error()
      await removed()
    } catch { setError(true) } finally { busy.current = false; setPending(false) }
  }
  return createPortal(<div className="le-scrim"><div className="le-dialog" role="dialog" aria-modal="true" aria-labelledby={title} ref={ref} tabIndex={-1}>
    <h2 className="heading" id={title}>{texts.calendar.removeTitle}</h2><p>{source.name}</p><p>{texts.calendar.removeNote}</p>
    {error && <Notice tone="danger">{texts.calendar.actionError}</Notice>}
    <div className="le-dialog-actions"><Button variant="secondary" disabled={pending} onClick={dismiss}>{texts.calendar.cancel}</Button><Button variant="danger" disabled={pending} onClick={() => { void remove() }}>{texts.calendar.remove}</Button></div>
  </div></div>, document.body)
}

/** Provider setup shares the calendar query group and agenda with all sources. */
export function CalendarSources() {
  const { texts } = useI18n()
  const sources = useQuery(calendarSourcesQuery()), client = useQueryClient()
  const [pending, setPending] = useState<string[]>([]), [messages, setMessages] = useState<Record<string, string>>({})
  const [removing, setRemoving] = useState<SourceOut>(), [replacing, setReplacing] = useState<SourceOut>()
  const heading = useRef<HTMLHeadingElement>(null)
  const invalidate = () => { void client.invalidateQueries({ queryKey: ['calendar'] }) }
  const cacheChange = async (id: string, saved?: SourceOut) => {
    const { queryKey } = calendarSourcesQuery()
    await client.cancelQueries({ queryKey, exact: true })
    client.setQueryData<SourceOut[]>(queryKey, rows => saved
      ? rows?.map(row => row.id === id ? saved : row)
      : rows?.filter(row => row.id !== id))
  }
  const action = async (source: SourceOut, refresh: boolean) => {
    setPending(current => [...current, source.id])
    try {
      const result = refresh ? await calendarSourceSync({ path: { source_id: source.id } }) : await calendarSourceUpdate({ path: { source_id: source.id }, body: { is_active: !source.is_active } })
      if (result.error || !result.response?.ok) throw new Error()
      setMessages(current => ({ ...current, [source.id]: refresh ? (result.data && 'queued' in result.data && result.data.queued ? texts.calendar.queued : ['ics', 'google'].includes(source.provider) ? texts.calendar.feedNotQueued : texts.calendar.notQueued) : '' }))
      if (result.data && 'is_active' in result.data) await cacheChange(source.id, result.data)
      invalidate()
    } catch { setMessages(current => ({ ...current, [source.id]: refresh ? texts.calendar.refreshError : texts.calendar.actionError })) }
    finally { setPending(current => current.filter(id => id !== source.id)) }
  }
  return <section id="calendar-sources" className="le-calendar-sources" aria-labelledby="calendar-sources-title">
    <h2 className="heading" id="calendar-sources-title" tabIndex={-1} ref={heading}>{texts.calendar.title}</h2>
    <div className="le-calendar-controls"><CalendarSetup /><Link to="/calendar" className="le-link le-calendar-back">{texts.calendar.back}</Link></div>
    {sources.isPending && <p role="status">{texts.calendar.loading}</p>}
    {sources.isError && <Notice tone="danger" action={{ label: texts.calendar.retry, onClick: () => { void sources.refetch() } }}>{texts.calendar.error}</Notice>}
    {sources.isSuccess && sources.data.length === 0 && <p className="small le-muted">{texts.calendar.noSources}</p>}
    {Boolean(sources.data?.length) && <div className="le-calendar-source-list">{sources.data?.map(source => <section key={source.id} className="le-calendar-source" aria-label={source.name}>
      <SourceStatus source={source} />
      <div className="le-calendar-controls">
        <Button variant="secondary" disabled={pending.includes(source.id)} onClick={() => { void action(source, false) }}>{source.is_active ? texts.calendar.pause : texts.calendar.activate}</Button>
        {source.is_active && <Button variant="ghost" icon="refresh-cw" disabled={pending.includes(source.id)} onClick={() => { void action(source, true) }}>{texts.calendar.refresh}</Button>}
        {source.provider === 'ics' && <Button variant="ghost" disabled={pending.includes(source.id)} onClick={() => setReplacing(source)}>{texts.calendar.replaceAddress}</Button>}
        <Button variant="ghost" disabled={pending.includes(source.id)} onClick={() => setRemoving(source)}>{texts.calendar.remove}</Button>
      </div>
      {messages[source.id] && <Notice tone="info">{messages[source.id]}</Notice>}
    </section>)}</div>}
    {replacing && <FeedSetup source={replacing} close={() => setReplacing(undefined)} saved={() => { setReplacing(undefined); invalidate() }} />}
    {removing && <RemoveSource source={removing} close={() => setRemoving(undefined)} removed={async () => { await cacheChange(removing.id); setRemoving(undefined); invalidate(); heading.current?.focus() }} />}
  </section>
}

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
import { de } from '../i18n/de'
import { SourceStatus } from './CalendarPage'

function RemoveSource({ source, close, removed }: { source: SourceOut; close: () => void; removed: () => void }) {
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
      removed()
    } catch { setError(true) } finally { busy.current = false; setPending(false) }
  }
  return createPortal(<div className="le-scrim"><div className="le-dialog" role="dialog" aria-modal="true" aria-labelledby={title} ref={ref} tabIndex={-1}>
    <h2 className="heading" id={title}>{de.calendar.removeTitle}</h2><p>{source.name}</p><p>{de.calendar.removeNote}</p>
    {error && <Notice tone="danger">{de.calendar.actionError}</Notice>}
    <div className="le-dialog-actions"><Button variant="secondary" disabled={pending} onClick={dismiss}>{de.calendar.cancel}</Button><Button variant="danger" disabled={pending} onClick={() => { void remove() }}>{de.calendar.remove}</Button></div>
  </div></div>, document.body)
}

/** Provider setup belongs to adapter issues. Mount reviewed forms in CalendarSetup only. */
export function CalendarSetup() {
  return <Notice tone="info">{de.calendar.unavailable}</Notice>
}
export function CalendarSources() {
  const sources = useQuery(calendarSourcesQuery()), client = useQueryClient()
  const [pending, setPending] = useState<string[]>([]), [messages, setMessages] = useState<Record<string, string>>({})
  const [removing, setRemoving] = useState<SourceOut>()
  const heading = useRef<HTMLHeadingElement>(null)
  const invalidate = () => { void client.invalidateQueries({ queryKey: ['calendar'] }) }
  const action = async (source: SourceOut, refresh: boolean) => {
    setPending(current => [...current, source.id])
    try {
      const result = refresh ? await calendarSourceSync({ path: { source_id: source.id } }) : await calendarSourceUpdate({ path: { source_id: source.id }, body: { is_active: !source.is_active } })
      if (result.error || !result.response?.ok) throw new Error()
      setMessages(current => ({ ...current, [source.id]: refresh ? (result.data && 'queued' in result.data && result.data.queued ? de.calendar.queued : de.calendar.notQueued) : '' }))
      invalidate()
    } catch { setMessages(current => ({ ...current, [source.id]: refresh ? de.calendar.refreshError : de.calendar.actionError })) }
    finally { setPending(current => current.filter(id => id !== source.id)) }
  }
  return <section id="calendar-sources" aria-labelledby="calendar-sources-title">
    <h2 className="heading" id="calendar-sources-title" tabIndex={-1} ref={heading}>{de.calendar.title}</h2>
    <Link to="/calendar" className="le-link le-calendar-back">{de.calendar.back}</Link>
    <CalendarSetup />
    {sources.isPending && <p role="status">{de.calendar.loading}</p>}
    {sources.isError && <Notice tone="danger" action={{ label: de.calendar.retry, onClick: () => { void sources.refetch() } }}>{de.calendar.error}</Notice>}
    {sources.data?.map(source => <section key={source.id} aria-label={source.name}>
      <SourceStatus source={source} />
      <div className="le-calendar-controls">
        <Button variant="secondary" disabled={pending.includes(source.id)} onClick={() => { void action(source, false) }}>{source.is_active ? de.calendar.pause : de.calendar.activate}</Button>
        {source.is_active && <Button variant="ghost" icon="refresh-cw" disabled={pending.includes(source.id)} onClick={() => { void action(source, true) }}>{de.calendar.refresh}</Button>}
        <Button variant="ghost" disabled={pending.includes(source.id)} onClick={() => setRemoving(source)}>{de.calendar.remove}</Button>
      </div>
      {messages[source.id] && <Notice tone="info">{messages[source.id]}</Notice>}
    </section>)}
    {removing && <RemoveSource source={removing} close={() => setRemoving(undefined)} removed={() => { setRemoving(undefined); invalidate(); heading.current?.focus() }} />}
  </section>
}

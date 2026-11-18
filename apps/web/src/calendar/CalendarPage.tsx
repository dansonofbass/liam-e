// i18n-exempt: route paths and CSS classes are technical identifiers.
import { useInfiniteQuery, useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { useEffect, useRef, useState } from 'react'
import { calendarAgendaQuery, calendarSourcesQuery, calendarDetailQuery } from '../api/queries'
import { calendarSourceSync } from '../api/generated/sdk.gen'
import type { SourceOut } from '../api/generated/types.gen'
import { Button, Chip, Notice, TextField } from '../ds'
import { de } from '../i18n/de'
import { addDays, browserZone, calendarDate, calendarTime, covers, inLocalWindow, occurrenceDay, oldSource, todayLocal, validWindow } from './state'
import './calendar.css'
import { AskAboutCalendar } from '../chat/CalendarContext'
import { CalendarSetup } from './FeedSetup'

export function SourceStatus({ source, from, to }: { source: SourceOut; from?: string; to?: string }) {
  return <div className="le-calendar-status">
    <strong>{source.name}</strong>
    <span>{source.provider === 'ics' ? de.calendar.ics : source.provider === 'google' ? de.calendar.google : de.calendar.readOnly}</span>
    <span>{source.last_success_at ? `${de.calendar.stored}: ${calendarDate(source.last_success_at)} ${calendarTime(source.last_success_at)}` : de.calendar.never}</span>
    {!source.is_active ? <Notice tone="info">{de.calendar.paused}</Notice> : <>
      {source.last_error && <Notice tone="danger">{source.last_error === 'address_check' ? de.calendar.feedAddressError : de.calendar.feedSyncError}</Notice>}
      {source.incomplete && <Notice tone="info">{de.calendar.incomplete}</Notice>}
      {oldSource(source) && source.last_success_at && <Notice tone="info">{de.calendar.old}</Notice>}
      {from && to && !covers(source, from, to) && <Notice tone="info">{de.calendar.uncovered}</Notice>}
    </>}
  </div>
}
export function CalendarDetail({ id }: { id: string }) {
  const detail = useQuery(calendarDetailQuery(id)), sources = useQuery(calendarSourcesQuery())
  const row = detail.data, source = sources.data?.find(s => s.id === row?.source_id)
  return <article className="le-calendar-detail">
    <Link className="le-link" to="/calendar">{de.calendar.back}</Link>
    {detail.isPending && <p role="status">{de.calendar.loading}</p>}
    {(detail.isError || sources.isError || (sources.isSuccess && row && !source?.is_active)) && <Notice tone="danger">{de.calendar.missing}</Notice>}
    {row && !detail.isError && !sources.isError && source?.is_active && <><h1 className="title">{row.title}</h1><p>{calendarDate(occurrenceDay(row))} · {row.start_date ? de.calendar.allDay : calendarTime(row.start_at!)}</p>
      {row.end_date && <p>{de.calendar.to}: {calendarDate(row.end_date)}</p>}
      {row.end_at && <p>{calendarDate(row.end_at)} · {calendarTime(row.end_at)}</p>}
      {source && <><SourceStatus source={source} /><AskAboutCalendar occurrenceId={row.id} sourceId={source.id} /></>}
    </>}
  </article>
}
export function CalendarAgenda() {
  const sources = useQuery(calendarSourcesQuery())
  const [from, setFrom] = useState(todayLocal), [to, setTo] = useState(() => addDays(todayLocal(), 7))
  const [sourceId, setSourceId] = useState<string>()
  const timeZone = browserZone()
  const [refreshing, setRefreshing] = useState(false), [notices, setNotices] = useState<Record<string, string>>({})
  const selected = sources.data?.filter(s => s.is_active && (!sourceId || s.id === sourceId)) ?? []
  const valid = validWindow(from, to)
  const page = useInfiniteQuery({ ...calendarAgendaQuery(from, to, timeZone, sourceId), enabled: valid && selected.length > 0 })
  const complete = selected.length > 0 && selected.every(s => covers(s, from, to))
  const attempted = useRef(new Set<string>())
  const refreshSources = async (targets: SourceOut[], dueOnly = false) => {
    setRefreshing(true)
    await Promise.all(targets.map(async source => {
      try {
        const result = await calendarSourceSync({ path: { source_id: source.id }, query: { due_only: dueOnly } })
        if (result.error || !result.response?.ok) throw new Error()
        if (!dueOnly) setNotices(current => ({ ...current, [source.id]: result.data?.queued ? de.calendar.queued : source.provider === 'ics' ? de.calendar.feedNotQueued : de.calendar.notQueued }))
      } catch { if (!dueOnly) setNotices(current => ({ ...current, [source.id]: de.calendar.refreshError })) }
    }))
    setRefreshing(false)
    void sources.refetch()
    if (valid && selected.length) void page.refetch()
  }
  useEffect(() => {
    const due = (sources.data ?? []).filter(s => s.is_active && (s.provider === 'ics' || oldSource(s)) && !attempted.current.has(s.id))
    for (const source of due) attempted.current.add(source.id)
    if (due.length) void refreshSources(due, true)
  }, [sources.data])
  // Adjacent padded windows can return the same spanning instance. Keep its stable identity once.
  const unique = new Map(page.data?.pages.flatMap(p => p.items).map(row => [row.id, row]))
  const activeIds = new Set(selected.map(source => source.id))
  const rows = page.isSuccess ? [...unique.values()].filter(row => activeIds.has(row.source_id) && inLocalWindow(row, from, to, timeZone)).sort((a, b) => occurrenceDay(a, timeZone).localeCompare(occurrenceDay(b, timeZone)) || (a.start_at ?? '').localeCompare(b.start_at ?? '') || a.id.localeCompare(b.id)) : []
  // Without any calendar there is nothing to page through or refresh: name the way to add one.
  // Only after a successful load: a failed reload keeps the cached list and must show its error and retry.
  if (sources.isSuccess && sources.data.length === 0) return <section className="le-calendar-agenda" aria-label={de.calendar.title}>
    <h1 className="title">{de.calendar.title}</h1>
    <Notice tone="info">{de.calendar.noSources}</Notice>
    <div className="le-calendar-controls"><CalendarSetup primary /></div>
  </section>
  return <section className="le-calendar-agenda" aria-label={de.calendar.title}>
    <h1 className="title">{de.calendar.title}</h1>
    <div className="le-calendar-controls">
      <Button variant="secondary" onClick={() => { setFrom(todayLocal()); setTo(addDays(todayLocal(), 7)) }}>{de.calendar.today}</Button>
      <Button variant="ghost" icon="refresh-cw" disabled={!selected.length || refreshing} onClick={() => { void refreshSources(selected) }}>{de.calendar.refresh}</Button>
      <Link className="le-link" to="/accounts">{de.calendar.manage}</Link>
    </div>
    <div className="le-calendar-range">
      <TextField label={de.calendar.from} type="date" value={from} onChange={e => { setFrom(e.target.value) }} />
      <TextField label={de.calendar.to} type="date" value={to} onChange={e => { setTo(e.target.value) }} />
    </div>
    {!valid && <Notice tone="info">{de.calendar.range}</Notice>}
    <div className="le-calendar-controls" aria-label={de.calendar.title}>
      <Chip pressed={!sourceId} onClick={() => { setSourceId(undefined) }}>{de.calendar.all}</Chip>
      {sources.data?.filter(s => s.is_active).map(s => <Chip key={s.id} pressed={sourceId === s.id} onClick={() => { setSourceId(s.id) }}>{s.name}</Chip>)}
    </div>
    {sources.isPending && <p role="status">{de.calendar.loading}</p>}
    {sources.isError && <Notice tone="danger" action={{ label: de.calendar.retry, onClick: () => { void sources.refetch() } }}>{de.calendar.error}</Notice>}
    {sources.data?.filter(s => !s.is_active || !sourceId || s.id === sourceId).map(s => <div key={s.id}><SourceStatus source={s} from={from} to={to} />{notices[s.id] && <Notice tone="info">{notices[s.id]}</Notice>}</div>)}
    {selected.length > 0 && valid && <>
      {page.isPending && <><p role="status">{de.calendar.loading}</p><div className="le-calendar-placeholder" aria-hidden="true" /></>}
      {page.isError && <Notice tone="danger" action={{ label: de.calendar.retry, onClick: () => { void page.refetch() } }}>{de.calendar.error}</Notice>}
      {page.isSuccess && !rows.length && <p>{complete && !page.hasNextPage ? de.calendar.empty : de.calendar.unknown}</p>}
      {rows.map((row, index) => <div key={row.id}>
        {(index === 0 || occurrenceDay(rows[index - 1]!) !== occurrenceDay(row)) && <h2 className="heading">{calendarDate(occurrenceDay(row))}</h2>}
        <Link className="le-calendar-row" to="/calendar/$occurrenceId" params={{ occurrenceId: row.id }}>
          <span>{row.start_date ? de.calendar.allDay : calendarTime(row.start_at!)}</span><strong>{row.title}</strong><span>{sources.data?.find(s => s.id === row.source_id)?.name}</span>
        </Link>
      </div>)}
      {page.hasNextPage && <Button variant="secondary" disabled={page.isFetchingNextPage} onClick={() => { void page.fetchNextPage() }}>{de.calendar.more}</Button>}
    </>}
  </section>
}

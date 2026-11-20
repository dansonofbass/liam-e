// i18n-exempt: route paths and CSS classes are technical identifiers.
import { useInfiniteQuery, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useLocation, useNavigate } from '@tanstack/react-router'
import { useEffect, useState } from 'react'
import { calendarAgendaQuery, calendarSourcesQuery } from '../api/queries'
import { calendarOccurrenceLive } from '../api/generated/sdk.gen'
import type { SourceOut } from '../api/generated/types.gen'
import { Button, Chip, IconButton, Notice, TextField } from '../ds'
import { useI18n } from '../i18n/I18n'
import { addDays, browserZone, calendarDate, calendarTime, covers, inLocalWindow, occurrenceDay, oldSource, todayLocal, validWindow } from './state'
import './calendar.css'
import { AskAboutCalendar } from '../chat/CalendarContext'
import { CalendarSetup } from './FeedSetup'
import { CalendarAccessLost, calendarSourceInterval } from './cache'
import { useCalendarRefresh } from './useCalendarRefresh'
import { parseSearch } from './url'
import { useBreakpoint } from '../shell/useBreakpoint'
import { Dot } from '../ds/Chip'
import { DeleteEventDialog } from './DeleteEventDialog'
import { EventDialog } from './EventDialog'
import { eventWhen } from './EventReading'
import { safeCalendarLink, useUnresolvedWrites } from './write-state'
import { UnresolvedNotice } from './UnresolvedNotice'
import { ApiError, apiErrorMessage } from '../api/unwrap'

export function SourceStatus({ source, from, to }: { source: SourceOut; from?: string; to?: string }) {
  const { texts, locale } = useI18n()
  const googleError = source.last_error === 'reconnect_required' ? texts.calendar.googleReconnectError
    : source.last_error === 'calendar_unavailable' ? texts.calendar.googleUnavailableError : texts.calendar.googleProviderError
  return <div className="le-calendar-status">
    <strong>{source.name}</strong>
    <span>{source.provider === 'ics' ? texts.calendar.ics : source.provider === 'google' ? (source.capabilities.includes('write') ? texts.calendar.googleWritable : texts.calendar.google) : texts.calendar.readOnly}</span>
    <span>{source.last_success_at ? `${texts.calendar.stored}: ${calendarDate(source.last_success_at, undefined, locale)} ${calendarTime(source.last_success_at, undefined, locale)}` : texts.calendar.never}</span>
    {!source.is_active ? <Notice tone="info">{texts.calendar.paused}</Notice> : <>
      {source.last_error && <Notice tone="danger">{source.provider === 'google' ? googleError : source.last_error === 'address_check' ? texts.calendar.feedAddressError : texts.calendar.feedSyncError}</Notice>}
      {source.incomplete && <Notice tone="info">{texts.calendar.incomplete}</Notice>}
      {oldSource(source) && source.last_success_at && <Notice tone="info">{texts.calendar.old}</Notice>}
      {from && to && !covers(source, from, to) && <Notice tone="info">{texts.calendar.uncovered}</Notice>}
    </>}
  </div>
}
export function CalendarDetail({ id }: { id: string }) {
  const { texts, locale } = useI18n()
  const breakpoint = useBreakpoint(), location = useLocation(), navigate = useNavigate()
  const search = parseSearch(location.search as Record<string, unknown>, breakpoint === 'mobile')
  const client = useQueryClient()
  const [deleting, setDeleting] = useState(false), [editing, setEditing] = useState(false)
  useEffect(() => { setDeleting(false); setEditing(false) }, [id])
  const detail = useQuery({ queryKey: ['calendar', 'live', id], retry: false, gcTime: 0, queryFn: async () => {
    const result = await calendarOccurrenceLive({ path: { occurrence_id: id } })
    if (!result.data || (result.response && result.response.status >= 400)) throw new ApiError(result.error)
    return result.data
  } }), sources = useQuery(calendarSourcesQuery())
  const row = detail.data, source = sources.data?.find(s => s.id === row?.source_id)
  const open = useUnresolvedWrites().filter(write => write.occurrenceId === id)
  const writable = row?.editable && source?.capabilities.includes('write') && !!row.revision
  // A conflict or an open outcome makes the shown revision stale: reread it once the dialog closes.
  const reread = () => { void client.invalidateQueries({ queryKey: ['calendar', 'live', id] }) }
  const href = safeCalendarLink(row?.html_link)
  const reason = texts.calendar.reasons[(row?.reason ?? 'calendar_not_writable') as keyof typeof texts.calendar.reasons] ?? texts.calendar.reasons.calendar_not_writable
  return <article className="le-calendar-detail">
    <div className="le-calendar-detail-header"><Link className="le-link le-calendar-back" to="/calendar" search={search}>{texts.calendar.back}</Link><IconButton className="le-calendar-close" label={texts.calendar.close} icon="x" onClick={() => { void navigate({ to: '/calendar', search }) }} /></div>
    {(detail.isPending || sources.isPending) && <><p role="status">{texts.calendar.loading}</p>{[0, 1, 2].map(n => <div key={n} className="le-calendar-placeholder" aria-hidden="true" />)}</>}
    {(detail.isError || sources.isError) && <Notice tone="danger" action={{ label: texts.calendar.retry, onClick: () => { void detail.refetch(); void sources.refetch() } }}>{detail.isError ? apiErrorMessage(detail.error, texts, texts.calendar.writeErrors.calendar_write_unknown) : texts.calendar.error}</Notice>}
    {sources.isSuccess && row && !source?.is_active && <Notice tone="danger">{texts.calendar.writeErrors.calendar_unavailable}</Notice>}
    {row && !detail.isError && !sources.isError && source?.is_active && <><h1 className="title">{row.title}</h1><p>{eventWhen(row, locale)}</p>
      <p className="le-calendar-source-name"><Dot colorIndex={sources.data!.filter(s => s.is_active).findIndex(s => s.id === source.id)} />{source.name}</p>
      {row.location && <p>{row.location}</p>}{row.description && <p className="le-event-description">{row.description}</p>}
      {!writable && <><span className="le-tag">{texts.calendar.readOnlyTag}</span><p>{reason}</p></>}
      {href && <a className="le-link" href={href} target="_blank" rel="noopener noreferrer">{texts.calendar.googleOpen}</a>}
      <UnresolvedNotice writes={open} />
      <div className="le-calendar-controls">{writable && <><Button variant="secondary" disabled={open.length > 0} onClick={() => setEditing(true)}>{texts.calendar.editEvent}</Button><Button variant="danger" disabled={open.length > 0} onClick={() => setDeleting(true)}>{texts.calendar.deleteEvent}</Button></>}{(source.chat_access === 'read_only' || source.chat_access === 'writable') && <AskAboutCalendar occurrenceId={id} />}</div>
      {editing && <EventDialog key={id} mode="edit" initial={{ ...row, occurrence_id: id }} sources={sources.data!} onClose={() => { setEditing(false); reread() }} />}
      {deleting && <DeleteEventDialog key={id} event={{ ...row, occurrence_id: id }} onClose={() => { setDeleting(false); reread() }} onDone={() => { void client.invalidateQueries({ queryKey: ['calendar'] }); void navigate({ to: '/calendar', search }) }} />}
    </>}
  </article>
}
export function CalendarAgenda() {
  const { texts, locale } = useI18n()
  const sources = useQuery({ ...calendarSourcesQuery(), refetchInterval: calendarSourceInterval })
  const [from, setFrom] = useState(todayLocal), [to, setTo] = useState(() => addDays(todayLocal(), 7))
  const [sourceId, setSourceId] = useState<string>()
  const timeZone = browserZone()
  const visibleSources = sources.error instanceof CalendarAccessLost ? undefined : sources.data
  const { refresh, refreshing, notices } = useCalendarRefresh(visibleSources)
  const selected = visibleSources?.filter(s => s.is_active && (!sourceId || s.id === sourceId)) ?? []
  const valid = validWindow(from, to)
  const page = useInfiniteQuery({ ...calendarAgendaQuery(from, to, timeZone, selected, sourceId), enabled: valid && selected.length > 0 })
  const complete = selected.length > 0 && selected.every(s => covers(s, from, to))
  // Adjacent padded windows can return the same spanning instance. Keep its stable identity once.
  const active = new Set(selected.map(source => source.id))
  const unique = new Map(page.data?.pages.flatMap(p => p.items).map(row => [row.id, row]))
  const rows = page.error instanceof CalendarAccessLost ? [] : [...unique.values()].filter(row => active.has(row.source_id) && inLocalWindow(row, from, to, timeZone)).sort((a, b) => occurrenceDay(a, timeZone).localeCompare(occurrenceDay(b, timeZone)) || (a.start_at ?? '').localeCompare(b.start_at ?? '') || a.id.localeCompare(b.id))
  // Without any calendar there is nothing to page through or refresh: name the way to add one.
  // Only after a successful load: a failed reload keeps the cached list and must show its error and retry.
  if (sources.isSuccess && sources.data.length === 0) return <section className="le-calendar-agenda" aria-label={texts.calendar.list}>
    <Notice tone="info">{texts.calendar.noSources}</Notice>
    <div className="le-calendar-controls"><CalendarSetup primary /></div>
  </section>
  // Embedded as the calendar's list view, under the page's own title.
  return <section className="le-calendar-agenda" aria-label={texts.calendar.list}>
    <div className="le-calendar-controls">
      <Button variant="secondary" onClick={() => { setFrom(todayLocal()); setTo(addDays(todayLocal(), 7)) }}>{texts.calendar.today}</Button>
      <Button variant="ghost" icon="refresh-cw" disabled={!selected.length || refreshing} onClick={() => { void refresh(selected) }}>{texts.calendar.refresh}</Button>
      <Link className="le-link" to="/accounts">{texts.calendar.manage}</Link>
    </div>
    <div className="le-calendar-range">
      <TextField label={texts.calendar.from} type="date" value={from} onChange={e => { setFrom(e.target.value) }} />
      <TextField label={texts.calendar.to} type="date" value={to} onChange={e => { setTo(e.target.value) }} />
    </div>
    {!valid && <Notice tone="info">{texts.calendar.range}</Notice>}
    <div className="le-calendar-controls" aria-label={texts.calendar.title}>
      <Chip pressed={!sourceId} onClick={() => { setSourceId(undefined) }}>{texts.calendar.all}</Chip>
      {visibleSources?.filter(s => s.is_active).map(s => <Chip key={s.id} pressed={sourceId === s.id} onClick={() => { setSourceId(s.id) }}>{s.name}</Chip>)}
    </div>
    {sources.isPending && <p role="status">{texts.calendar.loading}</p>}
    {sources.isError && <Notice tone="danger" action={{ label: texts.calendar.retry, onClick: () => { void sources.refetch() } }}>{texts.calendar.error}</Notice>}
    {visibleSources?.filter(s => !s.is_active || !sourceId || s.id === sourceId).map(s => <div key={s.id}><SourceStatus source={s} from={from} to={to} />{notices[s.id] && <Notice tone="info">{notices[s.id]}</Notice>}</div>)}
    {selected.length > 0 && valid && <>
      {page.isPending && <><p role="status">{texts.calendar.loading}</p><div className="le-calendar-placeholder" aria-hidden="true" /></>}
      {page.isRefetching && <p role="status">{texts.calendar.updating}</p>}
      {page.isError && <Notice tone="danger" action={{ label: texts.calendar.retry, onClick: () => { void page.refetch() } }}>{page.isRefetchError && !(page.error instanceof CalendarAccessLost) ? texts.calendar.cachedError : texts.calendar.error}</Notice>}
      {sources.isSuccess && page.isSuccess && !page.isRefetching && !rows.length && <p>{complete && !page.hasNextPage ? texts.calendar.empty : texts.calendar.unknown}</p>}
      {rows.map((row, index) => <div key={row.id}>
        {(index === 0 || occurrenceDay(rows[index - 1]!) !== occurrenceDay(row)) && <h2 className="heading">{calendarDate(occurrenceDay(row), undefined, locale)}</h2>}
        <Link className="le-calendar-row" to="/calendar/$occurrenceId" params={{ occurrenceId: row.id }}>
          <span>{row.start_date ? texts.calendar.allDay : calendarTime(row.start_at!, undefined, locale)}</span><strong>{row.title}</strong><span>{sources.data?.find(s => s.id === row.source_id)?.name}</span>
        </Link>
      </div>)}
      {page.hasNextPage && <Button variant="secondary" disabled={page.isFetching || page.isPlaceholderData} onClick={() => { void page.fetchNextPage() }}>{texts.calendar.more}</Button>}
    </>}
  </section>
}

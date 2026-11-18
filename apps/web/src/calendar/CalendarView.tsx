// i18n-exempt: route paths and CSS classes.
import { useQuery } from '@tanstack/react-query'
import { useLocation, useNavigate } from '@tanstack/react-router'
import { useEffect, useRef, useState } from 'react'
import { calendarSourcesQuery } from '../api/queries'
import { calendarSourceSync } from '../api/generated/sdk.gen'
import { Button, Chip, IconButton, Notice } from '../ds'
import { de } from '../i18n/de'
import { useBreakpoint } from '../shell/useBreakpoint'
import { CalendarSetup } from './FeedSetup'
import { ListView } from './ListView'
import { MonthView } from './MonthView'
import { SourceBar } from './SourceBar'
import { TimeGrid } from './TimeGrid'
import { periodTitle, shift, visibleRange } from './grid'
import { addDays, covers, localBoundary, todayLocal } from './state'
import { parseSearch, type CalendarView as View } from './url'
import { useRangeOccurrences } from './useRangeOccurrences'
import { EventDialog } from './EventDialog'
import { UnresolvedNotice } from './UnresolvedNotice'
import { useUnresolvedWrites } from './write-state'

export function CalendarView() {
  const mobile = useBreakpoint() === 'mobile'
  const location = useLocation(), navigate = useNavigate()
  const { view, date } = parseSearch(location.search as Record<string, unknown>, mobile)
  const range = visibleRange(view, date)
  const sources = useQuery(calendarSourcesQuery())
  const [excluded, setExcluded] = useState<string[]>([])
  const [slot, setSlot] = useState<{ date: string; minute?: number }>()
  const writable = (sources.data ?? []).filter(s => s.is_active && s.capabilities.includes('write'))
  const unresolved = useUnresolvedWrites(), creating = unresolved.some(write => write.kind === 'create')
  const onSlot = (value: { date: string; minute?: number }) => { if (writable.length && !creating) setSlot(value) }
  const selected = (sources.data ?? []).filter(s => s.is_active && !excluded.includes(s.id))
  const page = useRangeOccurrences(range.from, range.to, selected.map(s => s.id))
  const attempted = useRef(new Set<string>())
  const [refreshing, setRefreshing] = useState(false)
  const [notices, setNotices] = useState<Record<string, string>>({})
  const refresh = async (ids: string[], dueOnly: boolean) => {
    setRefreshing(true)
    await Promise.all(ids.map(async id => {
      try {
        const result = await calendarSourceSync({ path: { source_id: id }, query: { due_only: dueOnly } })
        if (result.error || !result.response?.ok) throw new Error()
        if (!dueOnly) setNotices(current => ({ ...current, [id]: result.data?.queued ? de.calendar.queued : de.calendar.feedNotQueued }))
      } catch { if (!dueOnly) setNotices(current => ({ ...current, [id]: de.calendar.refreshError })) }
    }))
    setRefreshing(false)
    void sources.refetch()
    if (!dueOnly) page.refetch()
  }
  useEffect(() => {
    if (view === 'list') return
    const ids = (sources.data ?? []).filter(s => s.is_active && !attempted.current.has(s.id)).map(s => s.id)
    ids.forEach(id => attempted.current.add(id))
    if (ids.length) void refresh(ids, true)
  }, [sources.data, view])
  const change = (v: View, d: string) => { void navigate({ to: '/calendar', search: { view: v, date: d } }) }
  const open = (occurrenceId: string) => { void navigate({ to: '/calendar/$occurrenceId', params: { occurrenceId }, search: { view, date } }) }
  const start = localBoundary(range.from), end = localBoundary(range.to)
  const rows = page.rows.filter(row => row.start_date && row.end_date ? row.start_date < range.to && row.end_date > range.from : row.start_at && row.end_at && Date.parse(row.start_at) < end && (Date.parse(row.end_at) > start || (row.start_at === row.end_at && Date.parse(row.start_at) >= start)))
  if (sources.isSuccess && sources.data.length === 0) return <section className="le-calendar-agenda"><h1 className="title">{de.calendar.title}</h1><Notice tone="info">{de.calendar.noSources}</Notice><CalendarSetup primary /></section>
  return <section className="le-calendar-grid-page" aria-label={de.calendar.title}>
    <h1 className="title">{de.calendar.title}</h1>
    <div className="le-calendar-toolbar">
      {/* The list keeps its own from/to range; a period here would contradict it. */}
      {view !== 'list' && <>
        <Button className="le-calendar-today le-btn--sm" variant="secondary" onClick={() => change(view, todayLocal())}>{de.calendar.today}</Button>
        <IconButton className="le-calendar-prev" size={mobile ? 'lg' : 'md'} icon="chevron-left" label={de.calendar.previous} onClick={() => change(view, shift(view, date, -1))} />
        <IconButton className="le-calendar-next" size={mobile ? 'lg' : 'md'} icon="chevron-right" label={de.calendar.next} onClick={() => change(view, shift(view, date, 1))} />
        <h2 className="heading le-calendar-period">{periodTitle(view, date)}</h2>
      </>}
      {writable.length > 0 && <Button className="le-calendar-add le-btn--sm" variant="secondary" icon="plus" disabled={creating} onClick={() => onSlot({ date, minute: 540 })}>{de.calendar.addEvent}</Button>}
      <div className="le-calendar-switch" role="group" aria-label={de.calendar.view}>{(['month', 'week', 'day', 'list'] as const).map(v => <Button variant="ghost" key={v} aria-pressed={v === view} onClick={() => change(v, date)}>{de.calendar[v]}</Button>)}</div>
      {view !== 'list' && <IconButton className="le-calendar-refresh" icon="refresh-cw" label={de.calendar.refresh} disabled={!selected.length || refreshing} onClick={() => { void refresh(selected.map(s => s.id), false) }} />}
    </div>
    <UnresolvedNotice writes={unresolved} />
    {view === 'list' ? <ListView /> : <>
    {sources.isPending && <p role="status">{de.calendar.loading}</p>}
    {sources.isError && <Notice tone="danger" action={{ label: de.calendar.retry, onClick: () => { void sources.refetch() } }}>{de.calendar.error}</Notice>}
    <SourceBar sources={sources.data ?? []} selected={selected.map(s => s.id)} onToggle={id => setExcluded(current => current.includes(id) ? current.filter(x => x !== id) : [...current, id])} from={range.from} to={range.to} />
    {selected.map(s => notices[s.id] && <Notice key={s.id} tone="info">{s.name}: {notices[s.id]}</Notice>)}
    {page.isPending && <p role="status">{de.calendar.loading}</p>}
    {page.isError && <Notice tone="danger" action={{ label: de.calendar.retry, onClick: page.refetch }}>{de.calendar.error}</Notice>}
    {page.capped && <Notice tone="info">{de.calendar.capped}</Notice>}
    {selected.length > 0 && !page.isPending && !page.isError && rows.length === 0 && <p>{page.complete && !page.capped && selected.every(s => covers(s, range.from, range.to)) ? de.calendar.empty : de.calendar.unknown}</p>}
    {mobile && view === 'day' && <div className="le-day-strip" role="group" aria-label={de.calendar.dayStrip}>{Array.from({ length: 7 }, (_, i) => {
      const day = addDays(visibleRange('week', date).from, i)
      return <Chip key={day} pressed={day === date} onClick={() => change('day', day)}><span>{new Intl.DateTimeFormat('de-DE', { weekday: 'short', timeZone: 'UTC' }).format(new Date(day)).replace(/\.?$/, '.')}</span><strong>{Number(day.slice(8))}</strong></Chip>
    })}</div>}
    {view === 'month' ? <MonthView date={date} rows={rows} sources={(sources.data ?? []).filter(s => s.is_active)} mobile={mobile} onSelectDay={d => change('month', d)} onDay={d => change('day', d)} onSlot={onSlot} onOpen={open} /> : <TimeGrid from={range.from} to={range.to} rows={rows} sources={(sources.data ?? []).filter(s => s.is_active)} onSlot={onSlot} onOpen={open} />}
    </>}
    {slot && <EventDialog mode="create" initial={slot} sources={sources.data ?? []} onClose={() => setSlot(undefined)} />}
  </section>
}

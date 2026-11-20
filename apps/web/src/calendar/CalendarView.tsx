// i18n-exempt: route paths and CSS classes.
import { useQuery } from '@tanstack/react-query'
import { useLocation, useNavigate } from '@tanstack/react-router'
import { useState } from 'react'
import { calendarSourcesQuery } from '../api/queries'
import { CalendarAccessLost, calendarSourceInterval } from './cache'
import { useCalendarRefresh } from './useCalendarRefresh'
import { Button, Chip, IconButton, Notice } from '../ds'
import { formatShortWeekday } from '../i18n/format'
import { useI18n } from '../i18n/I18n'
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
  const { texts, locale } = useI18n()
  const mobile = useBreakpoint() === 'mobile'
  const location = useLocation(), navigate = useNavigate()
  const { view, date } = parseSearch(location.search as Record<string, unknown>, mobile)
  const range = visibleRange(view, date)
  const sources = useQuery({ ...calendarSourcesQuery(), refetchInterval: view === 'list' ? false : calendarSourceInterval })
  const visibleSources = sources.error instanceof CalendarAccessLost ? undefined : sources.data
  const [excluded, setExcluded] = useState<string[]>([])
  const [slot, setSlot] = useState<{ date: string; minute?: number }>()
  const writable = (visibleSources ?? []).filter(s => s.is_active && s.capabilities.includes('write'))
  const unresolved = useUnresolvedWrites(), creating = unresolved.some(write => write.kind === 'create')
  const onSlot = (value: { date: string; minute?: number }) => { if (writable.length && !creating) setSlot(value) }
  const selected = (visibleSources ?? []).filter(s => s.is_active && !excluded.includes(s.id))
  // The location may already point at chat while the previous route is still mounted.
  const inCalendar = location.pathname === '/calendar' || location.pathname.startsWith('/calendar/')
  const gridSources = inCalendar && view !== 'list' ? visibleSources : undefined
  const page = useRangeOccurrences(range.from, range.to, gridSources ? selected : [])
  const { refresh, refreshing, notices } = useCalendarRefresh(gridSources)
  const change = (v: View, d: string) => { void navigate({ to: '/calendar', search: { view: v, date: d } }) }
  const open = (occurrenceId: string) => { void navigate({ to: '/calendar/$occurrenceId', params: { occurrenceId }, search: { view, date } }) }
  const start = localBoundary(range.from), end = localBoundary(range.to)
  const rows = page.rows.filter(row => row.start_date && row.end_date ? row.start_date < range.to && row.end_date > range.from : row.start_at && row.end_at && Date.parse(row.start_at) < end && (Date.parse(row.end_at) > start || (row.start_at === row.end_at && Date.parse(row.start_at) >= start)))
  if (sources.isSuccess && sources.data.length === 0) return <section className="le-calendar-agenda"><h1 className="title">{texts.calendar.title}</h1><Notice tone="info">{texts.calendar.noSources}</Notice><CalendarSetup primary /></section>
  return <section className="le-calendar-grid-page" aria-label={texts.calendar.title}>
    <h1 className="title">{texts.calendar.title}</h1>
    <div className="le-calendar-toolbar">
      {/* The list keeps its own from/to range; a period here would contradict it. */}
      {view !== 'list' && <>
        <Button className="le-calendar-today le-btn--sm" variant="secondary" onClick={() => change(view, todayLocal())}>{texts.calendar.today}</Button>
        <IconButton className="le-calendar-prev" size={mobile ? 'lg' : 'md'} icon="chevron-left" label={texts.calendar.previous} onClick={() => change(view, shift(view, date, -1))} />
        <IconButton className="le-calendar-next" size={mobile ? 'lg' : 'md'} icon="chevron-right" label={texts.calendar.next} onClick={() => change(view, shift(view, date, 1))} />
        <h2 className="heading le-calendar-period">{periodTitle(view, date, locale)}</h2>
      </>}
      {writable.length > 0 && <Button className="le-calendar-add le-btn--sm" variant="secondary" icon="plus" disabled={creating} onClick={() => onSlot({ date, minute: 540 })}>{texts.calendar.addEvent}</Button>}
      <div className="le-calendar-switch" role="group" aria-label={texts.calendar.view}>{(['month', 'week', 'day', 'list'] as const).map(v => <Button variant="ghost" key={v} aria-pressed={v === view} onClick={() => change(v, date)}>{texts.calendar[v]}</Button>)}</div>
      {view !== 'list' && <IconButton className="le-calendar-refresh" icon="refresh-cw" label={texts.calendar.refresh} disabled={!selected.length || refreshing} onClick={() => { void refresh(selected) }} />}
    </div>
    <UnresolvedNotice writes={unresolved} />
    {view === 'list' ? <ListView /> : <>
    {sources.isPending && <p role="status">{texts.calendar.loading}</p>}
    {sources.isError && <Notice tone="danger" action={{ label: texts.calendar.retry, onClick: () => { void sources.refetch() } }}>{texts.calendar.error}</Notice>}
    <SourceBar sources={visibleSources ?? []} selected={selected.map(s => s.id)} onToggle={id => setExcluded(current => current.includes(id) ? current.filter(x => x !== id) : [...current, id])} from={range.from} to={range.to} />
    {selected.map(s => notices[s.id] && <Notice key={s.id} tone="info">{s.name}: {notices[s.id]}</Notice>)}
    {page.isPending && <p role="status">{texts.calendar.loading}</p>}
    {page.isRefetching && <p role="status">{texts.calendar.updating}</p>}
    {page.isError && <Notice tone="danger" action={{ label: texts.calendar.retry, onClick: page.refetch }}>{page.isRefetchError ? texts.calendar.cachedError : texts.calendar.error}</Notice>}
    {page.capped && <Notice tone="info">{texts.calendar.capped}</Notice>}
    {selected.length > 0 && !sources.isError && !page.isPending && !page.isRefetching && !page.isError && rows.length === 0 && <p>{page.complete && !page.capped && selected.every(s => covers(s, range.from, range.to)) ? texts.calendar.empty : texts.calendar.unknown}</p>}
    {mobile && view === 'day' && <div className="le-day-strip" role="group" aria-label={texts.calendar.dayStrip}>{Array.from({ length: 7 }, (_, i) => {
      const day = addDays(visibleRange('week', date).from, i)
      return <Chip key={day} pressed={day === date} onClick={() => change('day', day)}><span>{formatShortWeekday(new Date(day), 'UTC', locale)}</span><strong>{Number(day.slice(8))}</strong></Chip>
    })}</div>}
    {view === 'month' ? <MonthView date={date} rows={rows} sources={(visibleSources ?? []).filter(s => s.is_active)} mobile={mobile} onSelectDay={d => change('month', d)} onDay={d => change('day', d)} onSlot={onSlot} onOpen={open} /> : <TimeGrid from={range.from} to={range.to} rows={rows} sources={(visibleSources ?? []).filter(s => s.is_active)} onSlot={onSlot} onOpen={open} />}
    </>}
    {slot && <EventDialog mode="create" initial={slot} sources={visibleSources ?? []} onClose={() => setSlot(undefined)} />}
  </section>
}

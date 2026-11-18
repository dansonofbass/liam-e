// i18n-exempt: route paths and CSS classes.
import { useQuery } from '@tanstack/react-query'
import { Link, useLocation, useNavigate } from '@tanstack/react-router'
import { useEffect, useRef, useState } from 'react'
import { calendarSourcesQuery } from '../api/queries'
import { calendarSourceSync } from '../api/generated/sdk.gen'
import { Button, Chip, Notice } from '../ds'
import { de } from '../i18n/de'
import { useBreakpoint } from '../shell/useBreakpoint'
import { CalendarSetup } from './FeedSetup'
import { ListView } from './ListView'
import { MonthView } from './MonthView'
import { SourceBar } from './SourceBar'
import { TimeGrid } from './TimeGrid'
import { periodTitle, shift, visibleRange } from './grid'
import { addDays, calendarDate, covers, localBoundary, todayLocal } from './state'
import { parseSearch, type CalendarView as View } from './url'
import { useRangeOccurrences } from './useRangeOccurrences'

export function CalendarView() {
  const mobile = useBreakpoint() === 'mobile'
  const location = useLocation(), navigate = useNavigate()
  const { view, date } = parseSearch(location.search as Record<string, unknown>, mobile)
  const range = visibleRange(view, date)
  const sources = useQuery(calendarSourcesQuery())
  const [excluded, setExcluded] = useState<string[]>([])
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
  if (view === 'list') return <section className="le-calendar-grid-page"><div className="le-calendar-controls">{(['month', 'week', 'day', 'list'] as const).map(v => <Chip key={v} pressed={v === view} onClick={() => change(v, date)}>{de.calendar[v]}</Chip>)}</div><ListView /></section>
  return <section className="le-calendar-grid-page" aria-label={de.calendar.title}>
    <h1 className="title">{de.calendar.title}</h1>
    <div className="le-calendar-controls"><Button variant="secondary" onClick={() => change(view, todayLocal())}>{de.calendar.today}</Button><Button variant="ghost" onClick={() => change(view, shift(view, date, -1))}>{de.calendar.previous}</Button><Button variant="ghost" onClick={() => change(view, shift(view, date, 1))}>{de.calendar.next}</Button><strong>{periodTitle(view, date)}</strong>
      {(['month', 'week', 'day', 'list'] as const).map(v => <Chip key={v} pressed={v === view} onClick={() => change(v, date)}>{de.calendar[v]}</Chip>)}
      <Button variant="ghost" disabled={!selected.length || refreshing} onClick={() => { void refresh(selected.map(s => s.id), false) }}>{de.calendar.refresh}</Button><Link to="/accounts" className="le-link">{de.calendar.manage}</Link>
    </div>
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
      return <Chip key={day} pressed={day === date} onClick={() => change('day', day)}>{calendarDate(day)}</Chip>
    })}</div>}
    {view === 'month' ? <MonthView date={date} rows={rows} sources={selected} mobile={mobile} onSelectDay={d => change('month', d)} onDay={d => change('day', d)} onSlot={() => {}} onOpen={open} /> : <TimeGrid from={range.from} to={range.to} rows={rows} sources={selected} onSlot={() => {}} onOpen={open} />}
  </section>
}

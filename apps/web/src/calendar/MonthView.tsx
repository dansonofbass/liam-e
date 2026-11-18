// i18n-exempt: route paths and CSS classes.
import { Link } from '@tanstack/react-router'
import { Button } from '../ds'
import type { ApiRoutersApiV1CalendarSchemasOccurrenceOut as OccurrenceOut, SourceOut } from '../api/generated/types.gen'
import { de } from '../i18n/de'
import { allDaySpans, monthCells } from './grid'
import { addDays, calendarDate, calendarTime, localBoundary } from './state'

export function occurrenceLabel(row: OccurrenceOut, source?: SourceOut) {
  const date = row.start_date ?? row.start_at!
  const day = new Intl.DateTimeFormat('de-DE', { weekday: 'long', day: 'numeric', month: 'long', ...(row.start_date ? { timeZone: 'UTC' } : {}) }).format(new Date(date))
  return `${row.title}, ${day}, ${row.start_date ? de.calendar.allDay : `${calendarTime(row.start_at!)}–${calendarTime(row.end_at!)}`}, ${source?.name ?? ''}`
}
export function rowsOnDay(rows: OccurrenceOut[], day: string) {
  const next = addDays(day, 1), start = localBoundary(day), end = localBoundary(next)
  return rows.filter(row => row.start_date && row.end_date ? row.start_date < next && row.end_date > day : row.start_at && row.end_at && Date.parse(row.start_at) < end && (Date.parse(row.end_at) > start || (row.end_at === row.start_at && Date.parse(row.start_at) >= start)))
}
type Props = { date: string; rows: OccurrenceOut[]; sources: SourceOut[]; onDay(day: string): void; onSlot(start: { date: string; minute?: number }): void; onOpen(id: string): void; mobile?: boolean; onSelectDay?(day: string): void }
export function MonthView({ date, rows, sources, onDay, onSlot, onOpen, mobile = false, onSelectDay }: Props) {
  const cells = monthCells(date)
  if (mobile) return <div className="le-month-mobile"><div className="le-month-mobile-grid">{cells.map(({ day, inMonth }) => <Button key={day} id={`calendar-day-${day}`} variant="ghost" className={`le-month-date${inMonth ? '' : ' le-month-date--outside'}`} aria-pressed={day === date} aria-label={calendarDate(day)} onClick={() => onSelectDay?.(day)} onKeyDown={e => {
    const delta = e.key === 'ArrowLeft' ? -1 : e.key === 'ArrowRight' ? 1 : e.key === 'ArrowUp' ? -7 : e.key === 'ArrowDown' ? 7 : 0
    if (delta) { e.preventDefault(); document.getElementById(`calendar-day-${addDays(day, delta)}`)?.focus() }
  }}>{Number(day.slice(8))}{rowsOnDay(rows, day).length > 0 && <span className="le-month-dot" aria-hidden="true" />}</Button>)}</div><div className="le-month-mobile-list"><h2 className="heading">{calendarDate(date)}</h2>{rowsOnDay(rows, date).map(row => <Link key={row.id} className="le-calendar-row" to="/calendar/$occurrenceId" params={{ occurrenceId: row.id }} aria-label={occurrenceLabel(row, sources.find(s => s.id === row.source_id))} onClick={e => { e.preventDefault(); onOpen(row.id) }}><span>{row.start_date ? de.calendar.allDay : calendarTime(row.start_at!)}</span><strong>{row.title}</strong><span>{sources.find(s => s.id === row.source_id)?.name}</span></Link>)}</div></div>
  return <div className="le-month-grid">{Array.from({ length: 6 }, (_, week) => {
    const days = cells.slice(week * 7, week * 7 + 7)
    const from = days[0]!.day, to = addDays(from, 7)
    const occupied = Array.from({ length: 7 }, () => [false, false, false])
    const hidden = Array.from({ length: 7 }, () => 0)
    const entries: { row: OccurrenceOut; start: number; span: number; lane: number }[] = []
    for (const { row, startCol, span } of allDaySpans(rows, from, to)) {
      const lane = [0, 1, 2].find(i => occupied.slice(startCol, startCol + span).every(day => !day[i]))
      if (lane === undefined) { for (let i = startCol; i < startCol + span; i++) hidden[i]!++; continue }
      for (let i = startCol; i < startCol + span; i++) occupied[i]![lane] = true
      entries.push({ row, start: startCol, span, lane })
    }
    days.forEach(({ day }, col) => {
      for (const row of rowsOnDay(rows.filter(r => !r.start_date), day)) {
        const lane = occupied[col]!.findIndex(x => !x)
        if (lane < 0) { hidden[col]!++; continue }
        occupied[col]![lane] = true
        entries.push({ row, start: col, span: 1, lane })
      }
    })
    return <div key={from} className="le-month-week">
      {days.map(({ day, inMonth }, col) => <div key={day} className={`le-month-cell${inMonth ? '' : ' le-month-cell--outside'}`} style={{ gridColumn: col + 1, gridRow: '1 / span 5' }} />)}
      {days.map(({ day }, col) => <Button key={day} variant="ghost" className="le-month-date" style={{ gridColumn: col + 1, gridRow: 1 }} onClick={() => onSlot({ date: day })} onKeyDown={e => {
        const delta = e.key === 'ArrowLeft' ? -1 : e.key === 'ArrowRight' ? 1 : e.key === 'ArrowUp' ? -7 : e.key === 'ArrowDown' ? 7 : 0
        if (delta) { e.preventDefault(); document.getElementById(`calendar-day-${addDays(day, delta)}`)?.focus() }
      }} id={`calendar-day-${day}`}>{calendarDate(day)}</Button>)}
      {entries.map(({ row, start, span, lane }) => <Link key={`${row.id}-${start}`} className="le-month-event" style={{ gridColumn: `${start + 1} / span ${span}`, gridRow: lane + 2 }} to="/calendar/$occurrenceId" params={{ occurrenceId: row.id }} aria-label={occurrenceLabel(row, sources.find(s => s.id === row.source_id))} onClick={e => { e.preventDefault(); onOpen(row.id) }}>{row.title}</Link>)}
      {days.map(({ day }, col) => hidden[col]! > 0 && <Button key={day} variant="ghost" className="le-month-more" style={{ gridColumn: col + 1, gridRow: 5 }} onClick={() => onDay(day)}>{de.calendar.further(hidden[col]!)}</Button>)}
    </div>
  })}</div>
}

// i18n-exempt: route paths and CSS classes.
import { Link } from '@tanstack/react-router'
import { useEffect, useRef } from 'react'
import type { ApiRoutersApiV1CalendarSchemasOccurrenceOut as OccurrenceOut, SourceOut } from '../api/generated/types.gen'
import { Button } from '../ds'
import { de } from '../i18n/de'
import { layoutDay } from './grid'
import { addDays, calendarDate, calendarTime, localBoundary, todayLocal } from './state'
import { occurrenceLabel, rowsOnDay } from './MonthView'

type Props = { from: string; to: string; rows: OccurrenceOut[]; sources: SourceOut[]; onSlot(start: { date: string; minute?: number }): void; onOpen(id: string): void }
export function TimeGrid({ from, to, rows, sources, onSlot, onOpen }: Props) {
  const days: string[] = []
  for (let d = from; d < to; d = addDays(d, 1)) days.push(d)
  const scroll = useRef<HTMLDivElement>(null)
  useEffect(() => { if (scroll.current) scroll.current.scrollTop = Math.max(7, new Date().getHours()) * 48 }, [])
  const source = (row: OccurrenceOut) => sources.find(s => s.id === row.source_id)
  return <div className="le-time-grid">
    <div className="le-time-days" style={{ gridTemplateColumns: `repeat(${days.length}, minmax(0, 1fr))` }}>{days.map(day => <div key={day}><strong>{calendarDate(day)}</strong>{rowsOnDay(rows.filter(r => !!r.start_date), day).map(row => <Link key={row.id} className="le-time-all-day" to="/calendar/$occurrenceId" params={{ occurrenceId: row.id }} aria-label={occurrenceLabel(row, source(row))} onClick={e => { e.preventDefault(); onOpen(row.id) }}>{row.title}</Link>)}</div>)}</div>
    <div className="le-time-scroll" ref={scroll}><div className="le-time-columns" style={{ gridTemplateColumns: `repeat(${days.length}, minmax(0, 1fr))` }}>{days.map(day => {
      const minutes = (localBoundary(addDays(day, 1)) - localBoundary(day)) / 60_000
      return <div key={day} className="le-time-column" style={{ height: `${minutes * 0.8}px` }}>
        {Array.from({ length: Math.ceil(minutes / 60) }, (_, hour) => {
          const label = calendarTime(new Date(localBoundary(day) + hour * 3_600_000).toISOString())
          const [hours, mins] = label.split(':').map(Number)
          return <Button key={hour} variant="ghost" className="le-time-slot" style={{ top: `${hour * 48}px` }} aria-label={`${calendarDate(day)}, ${label}`} onClick={() => onSlot({ date: day, minute: hours! * 60 + mins! })}>{label}</Button>
        })}
        {layoutDay(rows, day).map(p => <Link key={p.row.id} className="le-time-event" to="/calendar/$occurrenceId" params={{ occurrenceId: p.row.id }} aria-label={occurrenceLabel(p.row, source(p.row))} onClick={e => { e.preventDefault(); onOpen(p.row.id) }} style={{ top: `${p.startMinute * 0.8}px`, height: `${Math.max((p.endMinute - p.startMinute) * 0.8, 12)}px`, left: `${p.column / p.columns * 100}%`, width: `${100 / p.columns}%` }}>{p.row.title}</Link>)}
        {day === todayLocal() && <div className="le-time-now" aria-hidden="true" style={{ top: `${(Date.now() - localBoundary(day)) / 60_000 * 0.8}px` }} />}
      </div>
    })}</div></div>
    <span className="le-hint">{de.calendar.allDay}</span>
  </div>
}

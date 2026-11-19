// i18n-exempt: route paths and CSS classes.
import { Link } from '@tanstack/react-router'
import { useEffect, useRef, useState } from 'react'
import type { ApiRoutersApiV1CalendarSchemasOccurrenceOut as OccurrenceOut, SourceOut } from '../api/generated/types.gen'
import { Button } from '../ds'
import { formatMinuteOfDay, formatShortWeekday } from '../i18n/format'
import { useI18n } from '../i18n/I18n'
import { allDaySpans, dayHours, layoutDay, wallMinute } from './grid'
import { addDays, calendarDate, calendarTime, todayLocal } from './state'
import { occurrenceLabel } from './MonthView'
import { useCoarsePointer } from '../shell/useBreakpoint'

type Props = { from: string; to: string; rows: OccurrenceOut[]; sources: SourceOut[]; onSlot(start: { date: string; minute?: number }): void; onOpen(id: string): void }
export function TimeGrid({ from, to, rows, sources, onSlot, onOpen }: Props) {
  const { texts, locale } = useI18n()
  const days: string[] = []
  for (let d = from; d < to; d = addDays(d, 1)) days.push(d)
  const scroll = useRef<HTMLDivElement>(null)
  const [now, setNow] = useState(Date.now)
  useEffect(() => { const timer = setInterval(() => setNow(Date.now()), 60_000); return () => clearInterval(timer) }, [])
  useEffect(() => {
    const current = new Date()
    const hour = days.includes(todayLocal()) && current.getHours() > 8 ? current.getHours() - 1 : 7
    if (scroll.current) scroll.current.scrollTop = hour * 48
  }, [from, to])
  const source = (row: OccurrenceOut) => sources.find(s => s.id === row.source_id)
  const color = (row: OccurrenceOut) => `var(--acc-${Math.max(0, sources.findIndex(s => s.id === row.source_id)) % 4 + 1})`
  const coarse = useCoarsePointer()
  const gutterWidth = 56
  const touchTarget = 44
  const columns = `${gutterWidth}px repeat(${days.length}, minmax(0, 1fr))`
  // Reserve the rendered minimum height when assigning lanes, and room for each 44 px
  // lane in the common header and body on touch screens. Leave room for the border
  // and a non-overlay vertical scrollbar.
  const placements = days.map(day => layoutDay(rows, day, undefined, (coarse ? touchTarget : 20) / 0.8))
  const lanes = Math.max(1, ...placements.flat().map(event => event.columns))
  const minWidth = coarse ? gutterWidth + days.length * (lanes * touchTarget + 1) + 16 : undefined
  return <div className="le-time-grid">
    <div className="le-time-content" style={{ minWidth }}>
      <div className="le-time-days" style={{ gridTemplateColumns: columns }}><div />{days.map(day => <div key={day} aria-current={day === todayLocal() ? 'date' : undefined}><span>{formatShortWeekday(new Date(day), 'UTC', locale)}</span> <strong>{Number(day.slice(8))}{locale === 'de' ? '.' : ''}</strong></div>)}</div>
      <div className="le-time-all-days" style={{ gridTemplateColumns: columns }}><span className="le-time-all-label">{texts.calendar.allDayGutter}</span>{allDaySpans(rows, from, to).map(({ row, startCol, span }) => <Link key={row.id} className="le-time-all-day" style={{ gridColumn: `${startCol + 2} / span ${span}`, background: `color-mix(in srgb, ${color(row)} 14%, var(--surface))`, borderLeft: `3px solid ${color(row)}` }} to="/calendar/$occurrenceId" params={{ occurrenceId: row.id }} aria-label={occurrenceLabel(row, source(row), locale)} onClick={e => { e.preventDefault(); onOpen(row.id) }}>{row.title}</Link>)}</div>
      <div className="le-time-scroll" ref={scroll}><div className="le-time-columns" style={{ gridTemplateColumns: columns }}>
        <div className="le-time-gutter">{Array.from({ length: 23 }, (_, i) => <span className="le-time-hour" key={i} style={{ top: `${(i + 1) * 48}px` }}>{formatMinuteOfDay((i + 1) * 60, locale)}</span>)}</div>
        {/* Rows follow the wall clock like the gutter; a spring-forward day leaves its missing hour empty. */}
        {days.map((day, index) => {
          const dateLabel = calendarDate(day, undefined, locale)
          return <div key={day} className="le-time-column" style={{ height: `${24 * 48}px` }}>
            {dayHours(day).map(hour => {
              const minute = hour * 60
              const label = formatMinuteOfDay(minute, locale)
              return <Button key={hour} variant="ghost" className="le-time-slot" style={{ top: `${hour * 48}px` }} aria-label={`${dateLabel}, ${label}`} onClick={() => onSlot({ date: day, minute })} />
            })}
            {placements[index]!.map(p => <Link key={p.row.id} className="le-time-event" to="/calendar/$occurrenceId" params={{ occurrenceId: p.row.id }} aria-label={occurrenceLabel(p.row, source(p.row), locale)} onClick={e => { e.preventDefault(); onOpen(p.row.id) }} style={{ top: `${p.startMinute * 0.8}px`, height: `${Math.max((p.endMinute - p.startMinute) * 0.8, 20)}px`, left: `${p.column / p.columns * 100}%`, width: `${100 / p.columns}%`, background: `color-mix(in srgb, ${color(p.row)} 14%, var(--surface))`, borderLeft: `3px solid ${color(p.row)}` }}><span>{calendarTime(p.row.start_at!, undefined, locale)}–{calendarTime(p.row.end_at!, undefined, locale)}</span><strong>{p.row.title}</strong></Link>)}
            {day === todayLocal() && <div className="le-time-now" aria-hidden="true" style={{ top: `${wallMinute(now) * 0.8}px` }} />}
          </div>
        })}</div></div>
    </div>
  </div>
}

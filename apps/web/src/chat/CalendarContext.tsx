// i18n-exempt: route paths and CSS identifiers.
import { useQuery } from '@tanstack/react-query'
import { Link, useNavigate } from '@tanstack/react-router'
import { calendarDetailQuery, calendarSourcesQuery } from '../api/queries'
import { Button, Chip, Notice } from '../ds'
import { de } from '../i18n/de'
import { calendarDate, calendarTime, occurrenceDay } from '../calendar/state'
import { SourceStatus } from '../calendar/CalendarPage'
import { useCalendarScope, useChatSession } from './session'

export function CalendarScope({ conversationId, disabled }: { conversationId?: string; disabled: boolean }) {
  const selection = useCalendarScope(conversationId)
  const sources = useQuery(calendarSourcesQuery())
  const active = sources.data?.filter(source => source.is_active) ?? []
  return <section className="le-chat-scope" aria-label={de.calendar.chatScope}>
    <strong>{de.calendar.chatScope}</strong>
    <p className="le-hint">{de.calendar.scopeHint}</p>
    <div className="le-calendar-controls">
      {!selection.ids.length && <span className="le-hint">{de.calendar.noSelection}</span>}
      {active.map(source => <Chip key={source.id} disabled={disabled || !selection.ready} pressed={selection.ids.includes(source.id)} onClick={() => selection.set(selection.ids.includes(source.id) ? selection.ids.filter(id => id !== source.id) : [...selection.ids, source.id])}>{source.name}</Chip>)}
      {selection.ids.filter(id => !active.some(source => source.id === id)).map(id => <Chip key={id} pressed disabled={disabled || sources.isPending} onClick={() => selection.set(selection.ids.filter(item => item !== id))}>{de.calendar.unavailableSource}</Chip>)}
    </div>
    {sources.isError && <Notice tone="danger">{de.calendar.error}</Notice>}
  </section>
}

function occurrenceGone(error: unknown): boolean {
  const cause = error instanceof Error ? error.cause : undefined
  return typeof cause === 'object' && cause !== null && (cause as { detail?: unknown }).detail === 'occurrence_not_found'
}

/** Stored references contain only identities; titles and provenance always come from active sources. */
export function CalendarReference({ occurrenceId, sourceId }: { occurrenceId: string; sourceId?: string }) {
  const sources = useQuery(calendarSourcesQuery())
  const permitted = !sourceId || sources.data?.some(source => source.id === sourceId && source.is_active)
  const detail = useQuery({ ...calendarDetailQuery(occurrenceId), enabled: !!permitted && sources.isSuccess, retry: false })
  const row = detail.data
  const source = sources.data?.find(item => item.id === row?.source_id && item.is_active)
  if (sources.isError) return <Notice tone="danger" action={{ label: de.calendar.retry, onClick: () => { void sources.refetch() } }}>{de.calendar.error}</Notice>
  if (!sources.isSuccess) return <p role="status">{de.calendar.referenceLoading}</p>
  // A paused source or an occurrence the index no longer has is gone, not a passing failure.
  if (!permitted || (detail.isError && occurrenceGone(detail.error)) || (detail.isSuccess && (!source || (sourceId && row?.source_id !== sourceId)))) return <Notice tone="info">{de.calendar.missing}</Notice>
  if (detail.isError) return <Notice tone="danger" action={{ label: de.calendar.retry, onClick: () => { void detail.refetch() } }}>{de.calendar.error}</Notice>
  if (!row || !source) return <p role="status">{de.calendar.referenceLoading}</p>
  return <article className="le-calendar-status">
    <Link className="le-link" to="/calendar/$occurrenceId" params={{ occurrenceId: row.id }}>{row.title}</Link>
    <span>{calendarDate(occurrenceDay(row))} · {row.start_date ? de.calendar.allDay : calendarTime(row.start_at!)}</span>
    <SourceStatus source={source} />
  </article>
}

export function AskAboutCalendar({ occurrenceId, sourceId }: { occurrenceId: string; sourceId: string }) {
  const session = useChatSession(), navigate = useNavigate()
  return <Button variant="secondary" onClick={() => {
    session.setCalendarScope('new', [sourceId])
    void navigate({ to: '/', search: { calendarAbout: occurrenceId } })
  }}>{de.calendar.ask}</Button>
}

// i18n-exempt: route paths and CSS identifiers.
import { useQuery } from '@tanstack/react-query'
import { Link, useNavigate } from '@tanstack/react-router'
import { calendarDetailQuery, chatCalendarSourcesQuery } from '../api/queries'
import { Button, Notice } from '../ds'
import { useI18n } from '../i18n/I18n'
import { calendarDate, calendarTime, occurrenceDay } from '../calendar/state'
import { SourceStatus } from '../calendar/CalendarPage'
import type { SourceOut } from '../api/generated/types.gen'

export function readableCalendar(source: SourceOut) {
  return source.is_active && (source.chat_access === 'writable' || source.chat_access === 'read_only')
}

export function calendarScopeChanged(snapshot: string | undefined, ids: Set<string>) {
  try {
    const previous: unknown = JSON.parse(snapshot ?? '[]')
    return !Array.isArray(previous) || new Set(previous).size !== ids.size || !previous.every(id => typeof id === 'string' && ids.has(id))
  } catch { return true }
}

function occurrenceGone(error: unknown): boolean {
  const cause = error instanceof Error ? error.cause : undefined
  return typeof cause === 'object' && cause !== null && (cause as { detail?: unknown }).detail === 'occurrence_not_found'
}

/** Stored references contain only identities; titles and provenance always come from active sources. */
export function CalendarReference({ occurrenceId, sourceId }: { occurrenceId: string; sourceId?: string }) {
  const { texts, locale } = useI18n()
  const sources = useQuery(chatCalendarSourcesQuery())
  const permitted = !sourceId || sources.data?.some(source => source.id === sourceId && readableCalendar(source))
  const detail = useQuery({ ...calendarDetailQuery(occurrenceId, true), enabled: !!permitted && sources.isSuccess, retry: false })
  const row = detail.data
  const source = sources.data?.find(item => item.id === row?.source_id && readableCalendar(item))
  if (sources.isError) return <Notice tone="danger" action={{ label: texts.calendar.retry, onClick: () => { void sources.refetch() } }}>{texts.calendar.error}</Notice>
  if (!sources.isSuccess) return <p role="status">{texts.calendar.referenceLoading}</p>
  // A paused source or an occurrence the index no longer has is gone, not a passing failure.
  if (!permitted || (detail.isError && occurrenceGone(detail.error)) || (detail.isSuccess && (!source || (sourceId && row?.source_id !== sourceId)))) return <Notice tone="info">{texts.calendar.missing}</Notice>
  if (detail.isError) return <Notice tone="danger" action={{ label: texts.calendar.retry, onClick: () => { void detail.refetch() } }}>{texts.calendar.error}</Notice>
  if (!row || !source) return <p role="status">{texts.calendar.referenceLoading}</p>
  return <article className="le-calendar-status">
    <Link className="le-link" to="/calendar/$occurrenceId" params={{ occurrenceId: row.id }}>{row.title}</Link>
    <span>{calendarDate(occurrenceDay(row), undefined, locale)} · {row.start_date ? texts.calendar.allDay : calendarTime(row.start_at!, undefined, locale)}</span>
    <SourceStatus source={source} />
  </article>
}

export function AskAboutCalendar({ occurrenceId }: { occurrenceId: string }) {
  const { texts } = useI18n()
  const navigate = useNavigate()
  return <Button variant="secondary" onClick={() => {
    void navigate({ to: '/', search: { calendarAbout: occurrenceId } })
  }}>{texts.calendar.ask}</Button>
}

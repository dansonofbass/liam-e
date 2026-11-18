// i18n-exempt: CSS classes, query keys and protocol literals.
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useLayoutEffect, useRef, useState } from 'react'
import { chatProposalCancel, chatProposalCheck, chatProposalConfirm } from '../api/generated/sdk.gen'
import type { CalendarValues, ChatMessageOut, LiveEvent } from '../api/generated/types.gen'
import { calendarSourcesQuery } from '../api/queries'
import { errorCode } from '../api/unwrap'
import { Button, Notice } from '../ds'
import { Dot } from '../ds/Chip'
import { de } from '../i18n/de'
import { addDays, calendarDate } from '../calendar/state'
import { writeError } from '../calendar/write-state'
import './calendar-proposal.css'

function Values({ value, zone }: { value: CalendarValues | LiveEvent; zone: string }) {
  const at = (instant?: string | null) => instant ? new Intl.DateTimeFormat('de-DE', { dateStyle: 'medium', timeStyle: 'short', timeZone: zone }).format(new Date(instant)) : ''
  const local = (text?: string | null) => text ? `${calendarDate(text.slice(0, 10))} ${text.slice(11, 16)}` : ''
  const start = 'start_at' in value ? at(value.start_at) : local((value as CalendarValues).start_local)
  const end = 'end_at' in value ? at(value.end_at) : local((value as CalendarValues).end_local)
  return <><strong>{value.title}</strong><p>{value.start_date ? `${calendarDate(value.start_date)} – ${calendarDate(addDays(value.end_date!, -1))} · ${de.calendar.allDay}` : `${start} – ${end}`}</p>{value.location && <p>{value.location}</p>}{value.description && <p className="le-calendar-proposal-description">{value.description}</p>}</>
}
export function CalendarProposal({ message }: { message: ChatMessageOut }) {
  const client = useQueryClient(), sources = useQuery(calendarSourcesQuery())
  const [updated, setUpdated] = useState<ChatMessageOut>()
  const settled = ['done', 'failed', 'cancelled'].includes(message.proposal_status ?? '')
  const current = updated?.id === message.id && !settled ? updated : message
  const command = current.proposal?.calendar
  const [busy, setBusy] = useState(false), [error, setError] = useState<string>()
  const pending = useRef(false), focus = useRef(false), region = useRef<HTMLElement>(null)
  useLayoutEffect(() => { if (focus.current) { focus.current = false; region.current?.focus() } })
  const apply = async (action: 'confirm' | 'cancel' | 'check') => {
    if (pending.current) return
    pending.current = true; setBusy(true); setError(undefined)
    try {
      const path = { proposal_id: current.id }
      const result = action === 'confirm' ? await chatProposalConfirm({ path, body: { selected_ids: [] } }) : action === 'cancel' ? await chatProposalCancel({ path }) : await chatProposalCheck({ path })
      if (!result.data || (result.response && result.response.status >= 400)) {
        const code = errorCode(result.error)
        if (action === 'confirm' && (!result.response || result.response.status >= 500)) { setUpdated({ ...current, proposal_status: 'unknown' }); focus.current = true }
        setError(code === 'proposal_context_revoked' ? de.proposalErrors.proposal_context_revoked : code === 'proposal_not_pending' ? de.proposalErrors.proposal_not_pending : writeError(code))
        return
      }
      setUpdated(result.data); focus.current = true
      client.setQueryData<ChatMessageOut[]>(['history', current.conversation_id], rows => rows?.map(row => row.id === result.data!.id ? result.data! : row))
    } catch {
      setError(de.calendar.writeErrors.calendar_write_unknown)
      if (action === 'confirm') { setUpdated({ ...current, proposal_status: 'unknown' }); focus.current = true }
    }
    finally {
      void client.invalidateQueries({ queryKey: ['calendar'] })
      void client.invalidateQueries({ queryKey: ['history', current.conversation_id] })
      pending.current = false; setBusy(false)
    }
  }
  if (!command) return null
  const source = sources.data?.find(s => s.id === command.source_id)
  const failed = current.proposal?.result?.failed?.[0]?.code
  const status = current.proposal_status
  return <section className="le-confirm le-calendar-proposal" ref={region} tabIndex={-1} aria-label={de.calendar.cardActions[command.action]}>
    <h3 className="heading">{de.calendar.cardActions[command.action]}</h3>
    {status === 'done' ? <Notice tone="success">{de.calendar.cardDone[command.action]}</Notice> : status === 'cancelled' ? <p>{de.proposal.cancelled}</p> : <>
      {sources.isPending && <><p role="status">{de.calendar.loading}</p><div className="le-calendar-proposal-placeholder" aria-hidden="true" /></>}
      {sources.isError && <Notice tone="danger" action={{ label: de.calendar.retry, onClick: () => { void sources.refetch() } }}>{de.calendar.error}</Notice>}
      {sources.isSuccess && !source?.is_active && <Notice tone="info">{de.calendar.writeErrors.calendar_unavailable}</Notice>}
      {source?.is_active && !sources.isError && <><p><Dot colorIndex={sources.data!.filter(s => s.is_active).findIndex(s => s.id === source.id)} /> {source.name}</p><p>{current.proposal?.reason}</p>
        <div className="le-calendar-proposal-values">{command.before && <section><h4>{de.calendar.cardBefore}</h4><Values value={command.before} zone={command.timezone} /></section>}{command.after && <section><h4>{de.calendar.cardAfter}</h4><Values value={command.after} zone={command.timezone} /></section>}</div>
        <p>{de.calendar.eventZone}: {command.timezone}</p>
        {command.action === 'delete' && <p>{de.calendar.deleteWarning}</p>}<p className="le-hint">{de.calendar.writeRisk}</p>
      </>}
      {status === 'failed' && <Notice tone="danger">{failed === 'calendar_event_changed' ? de.calendar.cardChanged : failed === 'calendar_write_not_applied' ? de.calendar.cardNotApplied : writeError(failed)}</Notice>}
      {(status === 'unknown' || status === 'running') && <p role="status">{de.calendar.checking}</p>}
      <div className="le-calendar-proposal-actions">
        {status === 'pending' && <><Button variant="primary" disabled={busy || !source?.is_active || !source.capabilities.includes('write') || sources.isError} onClick={() => { void apply('confirm') }}>{de.calendar.cardConfirm}</Button><Button variant="ghost" disabled={busy} onClick={() => { void apply('cancel') }}>{de.controls.cancel}</Button></>}
        {/* running: a confirm may have died after claiming the card; the server answers while one is still in flight. */}
        {(status === 'unknown' || status === 'running') && <Button variant="secondary" disabled={busy} onClick={() => { void apply('check') }}>{de.calendar.check}</Button>}
      </div>
    </>}
    {error && <Notice tone="danger">{error}</Notice>}
  </section>
}

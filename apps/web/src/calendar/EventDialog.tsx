// i18n-exempt: CSS classes, input types and protocol literals.
import { useId, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { useQueryClient } from '@tanstack/react-query'
import { calendarEventCreate, calendarEventUpdate, calendarOccurrenceLive, calendarWriteCheck } from '../api/generated/sdk.gen'
import type { EventCreateIn, EventUpdateIn, LiveEvent, SourceOut, WriteOutcome } from '../api/generated/types.gen'
import { Button, Chip, Notice, TextField } from '../ds'
import { useFocusTrap } from '../ds/useFocusTrap'
import { de } from '../i18n/de'
import { addDays, browserZone } from './state'
import { EventReading } from './EventReading'
import { writeError, writeOutcome } from './write-state'

type Slot = { date: string; minute?: number }
type Form = { source: string; title: string; allDay: boolean; start: string; end: string; location: string; description: string }
function localTime(instant: string): string {
  const parts = new Intl.DateTimeFormat('sv-SE', { timeZone: browserZone(), year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }).formatToParts(new Date(instant))
  const get = (type: string) => parts.find(p => p.type === type)!.value
  return `${get('year')}-${get('month')}-${get('day')}T${get('hour')}:${get('minute')}`
}
function slotTime(date: string, minute: number): string {
  return `${addDays(date, Math.floor(minute / 1440))}T${String(Math.floor(minute % 1440 / 60)).padStart(2, '0')}:${String(minute % 60).padStart(2, '0')}`
}
function formFor(initial: Slot | LiveEvent, source: string): Form {
  if ('date' in initial) return { source, title: '', allDay: initial.minute === undefined, start: initial.minute === undefined ? initial.date : slotTime(initial.date, initial.minute), end: initial.minute === undefined ? initial.date : slotTime(initial.date, initial.minute + 60), location: '', description: '' }
  return { source: initial.source_id, title: initial.title, allDay: !!initial.start_date, start: initial.start_date ?? localTime(initial.start_at!), end: initial.end_date ? addDays(initial.end_date, -1) : localTime(initial.end_at!), location: initial.location ?? '', description: initial.description ?? '' }
}
export function EventDialog({ mode, initial, sources, onClose }: { mode: 'create' | 'edit'; initial: Slot | LiveEvent; sources: SourceOut[]; onClose(): void }) {
  const client = useQueryClient(), titleId = useId()
  const writable = sources.filter(s => s.is_active && s.capabilities.includes('write'))
  const [base, setBase] = useState(() => formFor(initial, writable[0]?.id ?? ''))
  const [form, setForm] = useState(base)
  const [live, setLive] = useState<LiveEvent | undefined>('date' in initial ? undefined : initial)
  const [writeId, setWriteId] = useState(() => crypto.randomUUID())
  const [outcome, setOutcome] = useState<WriteOutcome>()
  const [error, setError] = useState<string>()
  const [busy, setBusy] = useState(false), pending = useRef(false)
  const close = () => { if (!pending.current) onClose() }
  const ref = useFocusTrap(true, close)
  const locked = busy || !!outcome
  const set = <K extends keyof Form>(key: K, value: Form[K]) => setForm(f => ({ ...f, [key]: value }))
  const valid = form.title.trim().length > 0 && !!form.start && !!form.end && (form.allDay ? form.end >= form.start : form.end > form.start) && writable.some(s => s.id === form.source)
  const changed = JSON.stringify(form) !== JSON.stringify(base)
  const payload = (): Omit<EventCreateIn, 'source_id' | 'write_id' | 'title'> & { title?: string } => {
    const result: ReturnType<typeof payload> = {}
    for (const key of ['title', 'location', 'description'] as const) if (mode === 'create' || form[key] !== base[key]) result[key] = form[key]
    if (mode === 'create' || form.allDay !== base.allDay || form.start !== base.start || form.end !== base.end) {
      if (form.allDay) { result.start_date = form.start; result.end_date = addDays(form.end, 1) }
      else { result.start_local = form.start; result.end_local = form.end; result.timezone = browserZone() }
    }
    return result
  }
  const run = async (check = false) => {
    if (pending.current || (!check && (!valid || outcome || (mode === 'edit' && !changed)))) return
    pending.current = true; setBusy(true); setError(undefined)
    try {
      const fields = payload()
      const result = check ? await calendarWriteCheck({ path: { write_id: writeId } }) : mode === 'create'
        ? await calendarEventCreate({ body: { ...fields, source_id: form.source, title: form.title, write_id: writeId } })
        : await calendarEventUpdate({ path: { occurrence_id: live!.occurrence_id! }, body: { ...fields, expected_revision: live!.revision!, write_id: writeId } as EventUpdateIn })
      const next = writeOutcome(result); setOutcome(next)
      if (next.status === 'done') { void client.invalidateQueries({ queryKey: ['calendar'] }); onClose() }
      else ref.current?.focus()
    } catch { setOutcome({ status: 'unknown', write_id: writeId, error_code: 'calendar_write_unknown' }); ref.current?.focus() }
    finally { pending.current = false; setBusy(false) }
  }
  const adopt = async () => {
    if (pending.current || !live?.occurrence_id) return
    pending.current = true; setBusy(true); setError(undefined)
    try {
      const result = await calendarOccurrenceLive({ path: { occurrence_id: live.occurrence_id } })
      if (!result.data || (result.response && result.response.status >= 400)) throw new Error()
      if (!result.data.editable || !result.data.revision) { setError(de.calendar.writeErrors.calendar_event_not_editable); return }
      const next = formFor(result.data, result.data.source_id)
      setLive(result.data); setBase(next); setForm(next); setOutcome(undefined); setWriteId(crypto.randomUUID()); ref.current?.focus()
    } catch { setError(de.calendar.writeErrors.calendar_unavailable) }
    finally { pending.current = false; setBusy(false) }
  }
  const checking = outcome?.status === 'unknown' || outcome?.status === 'running'
  return createPortal(<div className="le-scrim" onMouseDown={e => { if (e.target === e.currentTarget) close() }}><div ref={ref} className="le-dialog le-dialog--wide" role="dialog" aria-modal="true" aria-labelledby={titleId} tabIndex={-1}>
    <h2 className="heading" id={titleId}>{mode === 'create' ? de.calendar.newEvent : de.calendar.editEvent}</h2>
    <form className="le-event-form" onSubmit={e => { e.preventDefault(); void run() }}>
      {!writable.length && <Notice tone="info">{de.calendar.noWritable}</Notice>}
      {mode === 'create' ? <div role="group" aria-label={de.calendar.title}><p>{de.calendar.title}</p><div className="le-calendar-controls">{writable.map(s => <Chip key={s.id} type="button" disabled={locked} pressed={s.id === form.source} onClick={() => set('source', s.id)}>{s.name}</Chip>)}</div></div> : <p>{sources.find(s => s.id === form.source)?.name}</p>}
      <TextField label={de.calendar.eventTitle} value={form.title} maxLength={500} required disabled={locked} onChange={e => set('title', e.target.value)} />
      <div className="le-google-choice"><TextField label={de.calendar.allDay} type="checkbox" checked={form.allDay} disabled={locked} onChange={e => { const allDay = e.target.checked; setForm(f => ({ ...f, allDay, start: allDay ? f.start.slice(0, 10) : `${f.start}T09:00`, end: allDay ? f.end.slice(0, 10) : `${f.end}T10:00` })) }} /></div>
      <div className="le-calendar-range"><TextField label={form.allDay ? de.calendar.eventDate : de.calendar.eventStart} type={form.allDay ? 'date' : 'datetime-local'} value={form.start} required disabled={locked} onChange={e => set('start', e.target.value)} /><TextField label={form.allDay ? de.calendar.eventEndDate : de.calendar.eventEnd} type={form.allDay ? 'date' : 'datetime-local'} value={form.end} required disabled={locked} onChange={e => set('end', e.target.value)} /></div>
      <p>{de.calendar.eventZone}: {browserZone()}</p>
      <TextField label={de.calendar.eventLocation} value={form.location} maxLength={1000} disabled={locked} onChange={e => set('location', e.target.value)} />
      <TextField label={de.calendar.eventDescription} multiline value={form.description} maxLength={8000} disabled={locked} hint={live?.description_was_html ? de.calendar.htmlDescription : undefined} onChange={e => set('description', e.target.value)} />
      <p className="le-hint">{de.calendar.writeRisk}</p>
      {!valid && form.title && <Notice tone="info">{de.calendar.writeErrors.calendar_time_invalid}</Notice>}
      {error && <Notice tone="danger">{error}</Notice>}
      {outcome?.error_code && <Notice tone="danger">{writeError(outcome.error_code)}</Notice>}
      {outcome?.current && <section><h3 className="heading">{de.calendar.currentValues}</h3><EventReading event={outcome.current} /><Button type="button" variant="secondary" disabled={busy} onClick={() => { void adopt() }}>{de.calendar.adoptEdit}</Button></section>}
      {checking && <p role="status">{de.calendar.checking}</p>}
      {busy && <p role="status">{de.calendar.eventSaving}</p>}
      <div className="le-dialog-actions"><Button type="button" variant="secondary" disabled={busy} onClick={close}>{de.controls.cancel}</Button>
        {!outcome && <Button type="submit" variant="primary" disabled={busy || !valid || (mode === 'edit' && (!changed || !live?.revision || !live.editable))}>{de.calendar.eventSave}</Button>}
        {checking && <Button type="button" variant="secondary" disabled={busy} onClick={() => { void run(true) }}>{de.calendar.check}</Button>}
        {outcome?.status === 'not_applied' && !outcome.current && <Button type="button" variant="secondary" disabled={busy} onClick={() => { setWriteId(crypto.randomUUID()); setOutcome(undefined) }}>{de.calendar.retryWrite}</Button>}
      </div>
    </form>
  </div></div>, document.body)
}

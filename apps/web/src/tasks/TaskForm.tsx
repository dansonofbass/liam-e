// i18n-exempt: technical values, input types and CSS classes.
import { useInfiniteQuery, useQuery } from '@tanstack/react-query'
import { useEffect, useMemo, useRef, useState } from 'react'
import { tasksPreview } from '../api/generated/sdk.gen'
import type { PreviewIn, TaskCreate } from '../api/generated/types.gen'
import { unwrap } from '../api/unwrap'
import { messagesInfiniteQuery } from '../api/queries'
import { Button, Chip, Notice, TextField } from '../ds'
import { de } from '../i18n/de'
import { recurrenceRule, timedUntil, type Recurrence, type Weekday } from './recurrence'
import { formatTaskDue } from './format'
import { TaskSelect } from './TaskSelect'
import './tasks.css'

const labels = de.tasks
const days: Weekday[] = ['MO', 'TU', 'WE', 'TH', 'FR', 'SA', 'SU']
const browserZone = () => Intl.DateTimeFormat().resolvedOptions().timeZone || ''
function through(start: string): string {
  const date = new Date(`${start.slice(0, 10)}T00:00:00Z`)
  date.setUTCDate(date.getUTCDate() + 365)
  return date.toISOString().slice(0, 10) + (start.length > 10 ? 'T23:59:59' : '')
}

/** This component is independent of the creation flow so proposal editors can reuse it. */
export function SchedulePreview({ input, onValid }: { input: PreviewIn | null; onValid?: (valid: boolean) => void }) {
  const query = useQuery({
    queryKey: ['task-preview', input], enabled: !!input, retry: false,
    queryFn: ({ signal }) => unwrap(tasksPreview({ body: input!, signal, throwOnError: true })),
  })
  // The keyed query never presents a previous schedule as the current one.
  const valid = !!input && query.isSuccess && !query.isFetching
  useEffect(() => { onValid?.(valid) }, [valid, onValid])
  return <section aria-label={labels.preview}><h3>{labels.preview}</h3>{!input ? <p>{labels.invalid}</p> : query.isPending || query.isFetching ? <p role="status">{labels.previewLoading}</p> : query.isError ? <Notice tone="danger" action={{ label: labels.retry, onClick: () => { void query.refetch() } }}>{labels.previewError}</Notice> : <><ol>{query.data.occurrences.map(value => <li key={value}>{formatTaskDue(value)}</li>)}</ol>{query.data.exceptions.length > 0 && <><p>{labels.exceptions}</p><ul>{query.data.exceptions.map((entry, index) => <li key={`${entry.local}-${index}`}>{entry.reason === 'invalid_date' ? labels.invalidDay(entry.local, entry.monthday) : labels.invalidTime(formatTaskDue(entry.local))}</li>)}</ul></>}{!query.data.complete && <p>{labels.previewIncomplete}</p>}</>}</section>
}

export function TaskForm({ save, busy, error }: { save: (body: TaskCreate) => void; busy: boolean; error?: string }) {
  const [title, setTitle] = useState(''), [description, setDescription] = useState('')
  const [date, setDate] = useState(''), [time, setTime] = useState(''), [zone, setZone] = useState(browserZone)
  const [mode, setMode] = useState('none'), [frequency, setFrequency] = useState<Recurrence['frequency']>('DAILY')
  const [interval, setInterval] = useState(1), [weekdays, setWeekdays] = useState<Weekday[]>([]), [monthday, setMonthday] = useState('1')
  const [end, setEnd] = useState('none'), [endDate, setEndDate] = useState(''), [count, setCount] = useState(1)
  const [previewValid, setPreviewValid] = useState(false)
  const [selectingMail, setSelectingMail] = useState(false), [mailSearch, setMailSearch] = useState('')
  const [mail, setMail] = useState<{ id: string; account_id: string; subject: string }>()
  const mails = useInfiniteQuery({ ...messagesInfiniteQuery({ q: mailSearch || undefined, limit: 50 }), enabled: selectingMail })
  const creationKey = useRef(crypto.randomUUID())
  const start = date + (time ? `T${time}` : '')
  const rule = useMemo(() => {
    try {
      if (mode === 'none') return null
      const freq = mode === 'custom' ? frequency : ({ daily: 'DAILY', weekly: 'WEEKLY', monthly: 'MONTHLY' } as const)[mode as 'daily' | 'weekly' | 'monthly']
      const ending: Recurrence['end'] = end === 'count' ? { kind: 'count', count } : end === 'date' ? { kind: 'until', value: time ? timedUntil(endDate, zone) : endDate.replaceAll('-', '') } : undefined
      return recurrenceRule({ frequency: freq, interval: mode === 'custom' ? interval : 1, weekdays: mode === 'custom' && freq === 'WEEKLY' ? weekdays : undefined, monthday: mode === 'custom' && freq === 'MONTHLY' ? (monthday === 'last' ? 'last' : Number(monthday)) : undefined, end: ending })
    } catch { return undefined }
  }, [mode, frequency, interval, weekdays, monthday, end, count, endDate, time, zone])
  let input: PreviewIn | null = null
  const validZone = Intl.supportedValuesOf('timeZone').includes(zone) || zone === 'UTC'
  try {
    if (!validZone) throw new RangeError('Invalid time zone')
    if (date && zone && rule !== undefined && (mode === 'none' || end !== 'date' || endDate >= date) && !(mode === 'custom' && frequency === 'WEEKLY' && !weekdays.length)) input = { start, through: through(start), timezone: zone, rrule: rule, limit: 5 }
  } catch { /* Invalid fields disable preview and save. */ }
  return <form className="le-tasks le-task-form" onSubmit={event => { event.preventDefault(); if (input && title.trim() && previewValid) save({ creation_key: creationKey.current, title: title.trim(), description, start, timezone: zone, rrule: rule, source_message_id: mail?.id, source_account_id: mail?.account_id }) }}>
    <h2 className="heading">{labels.create}</h2>
    <TextField label={labels.name} value={title} onChange={e => setTitle(e.target.value)} required maxLength={500} autoFocus />
    <TextField label={labels.note} multiline value={description} onChange={e => setDescription(e.target.value)} maxLength={10000} />
    {mail ? <p>{labels.source}: {mail.subject || de.mail.noSubject} <Button variant="ghost" onClick={() => setMail(undefined)}>{labels.removeMail}</Button></p> : <Button variant="secondary" onClick={() => setSelectingMail(value => !value)}>{labels.selectMail}</Button>}
    {selectingMail && !mail && <section aria-label={labels.selectMail}><TextField label={labels.searchMail} value={mailSearch} onChange={event => setMailSearch(event.target.value)} />{mails.isPending && <p role="status">{labels.mailLoading}</p>}{mails.isError && <Notice tone="danger" action={{ label: labels.retry, onClick: () => { void mails.refetch() } }}>{labels.mailError}</Notice>}<ul>{mails.data?.pages.flatMap(page => page.items).map(item => <li key={item.id}><Button variant="ghost" onClick={() => { setMail(item); setSelectingMail(false) }}>{item.subject || de.mail.noSubject} · {item.sender_name || item.sender_address}</Button></li>)}</ul>{mails.hasNextPage && <Button variant="secondary" onClick={() => { void mails.fetchNextPage() }}>{labels.moreMail}</Button>}</section>}
    <TextField label={labels.date} type="date" value={date} onChange={e => { setPreviewValid(false); setDate(e.target.value) }} required />
    <TextField label={labels.time} type="time" value={time} onChange={e => { setPreviewValid(false); setTime(e.target.value) }} />
    <TextField label={labels.zone} value={zone} onChange={e => { setPreviewValid(false); setZone(e.target.value) }} error={zone && !validZone ? labels.invalidZone : undefined} required />
    <TaskSelect label={labels.recurrence} value={mode} onChange={value => { setPreviewValid(false); setMode(value) }} options={[{ value: 'none', label: labels.none }, { value: 'daily', label: labels.daily }, { value: 'weekly', label: labels.weekly }, { value: 'monthly', label: labels.monthly }, { value: 'custom', label: labels.custom }]} />
    {mode === 'custom' && <><TaskSelect label={labels.frequency} value={frequency} onChange={value => { setPreviewValid(false); setFrequency(value as Recurrence['frequency']) }} options={[{ value: 'DAILY', label: labels.daily }, { value: 'WEEKLY', label: labels.weekly }, { value: 'MONTHLY', label: labels.monthly }]} /><TextField label={labels.interval} type="number" min={1} max={366} value={interval} onChange={e => { setPreviewValid(false); setInterval(Number(e.target.value)) }} />{frequency === 'WEEKLY' && <fieldset><legend>{labels.weekdays}</legend>{days.map((day, i) => <Chip key={day} pressed={weekdays.includes(day)} onClick={() => { setPreviewValid(false); setWeekdays(weekdays.includes(day) ? weekdays.filter(d => d !== day) : [...weekdays, day]) }}>{labels.days[i]}</Chip>)}</fieldset>}{frequency === 'MONTHLY' && <TaskSelect label={labels.monthday} value={monthday} onChange={value => { setPreviewValid(false); setMonthday(value) }} options={[...Array.from({ length: 31 }, (_, i) => ({ value: String(i + 1), label: labels.dayNumber(i + 1) })), { value: 'last', label: labels.lastDay }]} />}</>}
    {mode !== 'none' && <><TaskSelect label={labels.end} value={end} onChange={value => { setPreviewValid(false); setEnd(value) }} options={[{ value: 'none', label: labels.noEnd }, { value: 'date', label: labels.endDate }, { value: 'count', label: labels.count }]} />{end === 'date' && <TextField label={labels.endDate} type="date" value={endDate} onChange={e => { setPreviewValid(false); setEndDate(e.target.value) }} />}{end === 'count' && <TextField label={labels.count} type="number" min={1} max={10000} value={count} onChange={e => { setPreviewValid(false); setCount(Number(e.target.value)) }} />}</>}
    <SchedulePreview input={input} onValid={setPreviewValid} />
    {error && <Notice tone="danger">{error}</Notice>}
    <Button variant="primary" type="submit" disabled={busy || !input || !title.trim() || !previewValid}>{busy ? labels.saving : labels.save}</Button>
  </form>
}

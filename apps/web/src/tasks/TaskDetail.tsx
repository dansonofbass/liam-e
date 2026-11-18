// i18n-exempt: route paths, CSS classes and API values.
import { useInfiniteQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useNavigate } from '@tanstack/react-router'
import { useEffect, useId, useState } from 'react'
import { createPortal } from 'react-dom'
import { useFocusTrap } from '../ds/useFocusTrap'
import { tasksArchive, tasksDelete, tasksOccurrenceComplete, tasksOccurrenceReopen, tasksOccurrenceSkip, tasksUpdate } from '../api/generated/sdk.gen'
import type { ApiRoutersApiV1TasksSchemasOccurrenceOut as Occurrence } from '../api/generated/types.gen'
import { taskDetailQuery } from '../api/queries'
import { Button, Notice, TextField } from '../ds'
import { useI18n } from '../i18n/I18n'
import { reconcileTask } from './reconcile'
import { taskWindow } from './window'
import { SourceMail } from './SourceMail'
import { TaskSelect } from './TaskSelect'
import { formatTaskDue, formatTaskRule } from './format'
import './tasks.css'

export function TaskDetail({ id }: { id: string }) {
  const { texts, locale } = useI18n()
  const t = texts.tasks
  const [period, setPeriod] = useState(0), [base] = useState(() => new Date()), client = useQueryClient()
  const navigate = useNavigate()
  const window = taskWindow(base, period)
  const query = useInfiniteQuery(taskDetailQuery(id, { ...window, limit: 100 }))
  const [busy, setBusy] = useState(false), [error, setError] = useState<string>(), [conflict, setConflict] = useState(false)
  const [reconciling, setReconciling] = useState(false), [reconcileFailed, setReconcileFailed] = useState(false), [attempt, setAttempt] = useState(0)
  const [editing, setEditing] = useState<Occurrence>(), [start, setStart] = useState(''), [scope, setScope] = useState<'occurrence' | 'this_and_following'>('occurrence'), [deleting, setDeleting] = useState(false)
  const series = query.data?.pages[0]?.series
  useEffect(() => {
    if (!series || series.archived) return
    const controller = new AbortController()
    setReconciling(true); setReconcileFailed(false)
    void reconcileTask(id, { signal: controller.signal }).then(() => { if (!controller.signal.aborted) void client.invalidateQueries({ queryKey: ['tasks'] }) }).catch(() => { if (!controller.signal.aborted) setReconcileFailed(true) }).finally(() => { if (!controller.signal.aborted) setReconciling(false) })
    return () => controller.abort()
  }, [id, series?.archived, attempt, client])
  const run = async (action: () => Promise<{ response?: Response; error?: unknown }>, done?: () => void) => {
    if (busy || conflict) return
    setBusy(true); setError(undefined)
    try {
      const response = await action()
      if (!response.response?.ok) { setDeleting(false); if (response.response?.status === 409) { setConflict(true); setError(t.conflict) } else setError(t.saveError); return }
      await client.invalidateQueries({ queryKey: ['tasks'] }); done?.()
    } catch { setDeleting(false); setError(t.saveError) } finally { setBusy(false) }
  }
  const refresh = () => { void query.refetch().then(result => { if (!result.isError) { setConflict(false); setError(undefined); setEditing(undefined); setDeleting(false) } }) }
  if (!series) return <main className="le-tasks"><Link to="/tasks" search={true} className="le-link">{t.back}</Link>{query.isPending ? <p role="status">{t.loading}</p> : <Notice tone="danger" action={{ label: t.retry, onClick: refresh }}>{t.error}</Notice>}</main>
  const occurrences = query.data?.pages.flatMap(page => page.occurrences.items) ?? []
  const transition = (item: Occurrence, kind: 'complete' | 'skip' | 'reopen') => {
    const fn = kind === 'complete' ? tasksOccurrenceComplete : kind === 'skip' ? tasksOccurrenceSkip : tasksOccurrenceReopen
    void run(() => fn({ path: { occurrence_id: item.id }, body: { version: item.version } }))
  }
  return <main className="le-tasks"><Link to="/tasks" search={true} className="le-link">{t.back}</Link><h1 className="title">{series.title}</h1>{series.archived && <p>{t.archived}</p>}<p>{series.description}</p><p>{series.schedule?.timezone ?? 'UTC'} · {formatTaskRule(series.schedule?.rrule, locale)}</p>
    {series.source_message_id && <SourceMail id={series.source_message_id} />}
    {(reconciling || !series.complete) && <p role="status">{t.incomplete} {formatTaskDue(window.due_from, locale)} – {formatTaskDue(window.due_to, locale)}</p>}
    {reconcileFailed && <Notice tone="danger" action={{ label: t.retry, onClick: () => setAttempt(value => value + 1) }}>{t.error}</Notice>}
    {error && <Notice tone="danger" action={conflict ? { label: t.refresh, onClick: refresh } : undefined}>{error}</Notice>}
    <h2>{t.detail}</h2><p>{t.period}: {formatTaskDue(window.due_from, locale)} – {formatTaskDue(window.due_to, locale)}</p><div><Button variant="secondary" onClick={() => setPeriod(value => value - 1)}>{t.previousPeriod}</Button><Button variant="secondary" onClick={() => setPeriod(value => value + 1)}>{t.nextPeriod}</Button></div><ul>{occurrences.map(item => <li key={item.id}><span>{formatTaskDue(item.due_local, locale)} · {item.status === 'open' ? t.open : item.status === 'completed' ? t.completed : item.status === 'skipped' ? t.skipped : t.cancelled}</span>{item.status === 'open' && <><Button variant="secondary" disabled={busy || conflict} onClick={() => transition(item, 'complete')}>{t.complete}</Button><Button variant="secondary" disabled={busy || conflict} onClick={() => transition(item, 'skip')}>{t.skip}</Button>{!series.archived && <Button variant="ghost" disabled={busy || conflict} onClick={() => { setEditing(item); setStart(item.due_local); setScope('occurrence') }}>{t.edit}</Button>}</>}{(item.status === 'completed' || item.status === 'skipped') && <Button variant="secondary" disabled={busy || conflict} onClick={() => transition(item, 'reopen')}>{t.reopen}</Button>}</li>)}</ul>
    {query.hasNextPage && <Button variant="secondary" onClick={() => { void query.fetchNextPage() }}>{t.more}</Button>}
    {editing && <form onSubmit={event => { event.preventDefault(); void run(() => tasksUpdate({ path: { series_id: id }, body: { expected_version: series.version, occurrence_id: editing.id, expected_occurrence_version: editing.version, scope, start, ...(scope === 'this_and_following' ? { timezone: series.schedule?.timezone ?? 'UTC' } : {}) } }), () => setEditing(undefined)) }}><h2>{t.edit}</h2><TaskSelect label={t.scope} value={scope} onChange={value => setScope(value as typeof scope)} options={[{ value: 'occurrence', label: t.onlyThis }, { value: 'this_and_following', label: t.following }]} /><TextField label={t.date} type={editing.due_local.includes('T') ? 'datetime-local' : 'date'} value={start} onChange={event => setStart(event.target.value)} required /><Button variant="primary" type="submit" disabled={busy || conflict}>{t.saveEdit}</Button><Button variant="secondary" onClick={() => setEditing(undefined)}>{t.cancel}</Button></form>}
    {!series.archived && <Button variant="secondary" disabled={busy || conflict} onClick={() => { void run(() => tasksArchive({ path: { series_id: id }, body: { expected_version: series.version } })) }}>{t.archive}</Button>}
    <Button variant="danger" disabled={busy || conflict} onClick={() => setDeleting(true)}>{t.delete}</Button>
    {deleting && <DeleteDialog busy={busy} close={() => setDeleting(false)} remove={() => { void run(() => tasksDelete({ path: { series_id: id }, body: { expected_version: series.version, confirm_history_loss: true } }), () => { void navigate({ to: '/tasks', search: true }) }) }} />}
  </main>
}
function DeleteDialog({ busy, close, remove }: { busy: boolean; close: () => void; remove: () => void }) {
  const { texts } = useI18n()
  const t = texts.tasks
  const ref = useFocusTrap(true, () => { if (!busy) close() }), title = useId()
  return createPortal(<div className="le-scrim" onMouseDown={event => { if (!busy && event.target === event.currentTarget) close() }}><div className="le-dialog" role="dialog" aria-modal="true" aria-labelledby={title} ref={ref} tabIndex={-1}><h2 id={title} className="heading">{t.delete}</h2><p>{t.deleteWarning}</p><div className="le-dialog-actions"><Button variant="secondary" disabled={busy} onClick={close}>{t.cancel}</Button><Button variant="danger" disabled={busy} onClick={remove}>{t.delete}</Button></div></div></div>, document.body)
}

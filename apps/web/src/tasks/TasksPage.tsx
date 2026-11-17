// i18n-exempt: route paths, CSS classes and API values.
import { useInfiniteQuery, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import { tasksCreate } from '../api/generated/sdk.gen'
import type { TaskCreate } from '../api/generated/types.gen'
import { accountsQuery, taskListQuery, taskOccurrencesQuery } from '../api/queries'
import { unwrap } from '../api/unwrap'
import { Button, Notice } from '../ds'
import { de } from '../i18n/de'
import { TaskForm } from './TaskForm'
import { localToday, taskWindow } from './window'
import { reconcileTask } from './reconcile'
import { SourceMail } from './SourceMail'
import { formatTaskDue, formatTaskRule } from './format'

const t = de.tasks
export function TasksPage() {
  const [creating, setCreating] = useState(false), [busy, setBusy] = useState(false), [error, setError] = useState<string>()
  const [status, setStatus] = useState<'open' | 'completed' | 'archived'>('open')
  const [source, setSource] = useState('all'), [retryReconcile, setRetryReconcile] = useState(0)
  useEffect(() => {
    const params = new URLSearchParams(globalThis.window.location.search)
    const savedStatus = params.get('status')
    if (savedStatus === 'open' || savedStatus === 'completed' || savedStatus === 'archived') setStatus(savedStatus)
    setSource(params.get('source') || 'all')
  }, [])
  const persistFilter = (key: string, value: string) => {
    const url = new URL(globalThis.window.location.href)
    if (value === 'all' || (key === 'status' && value === 'open')) url.searchParams.delete(key)
    else url.searchParams.set(key, value)
    globalThis.window.history.replaceState(globalThis.window.history.state, '', url)
  }
  const [period, setPeriod] = useState(0), [base] = useState(() => new Date())
  const window = taskWindow(base, period)
  const client = useQueryClient(), accounts = useQuery(accountsQuery())
  const sourceFilter = source === 'all' ? { source: 'all' as const } : source === 'unlinked' ? { source: 'unlinked' as const } : { source: 'account' as const, source_account_id: source }
  const series = useInfiniteQuery(taskListQuery({ ...window, ...sourceFilter, status: status === 'archived' ? 'archived' : undefined, limit: 100 }))
  const occurrences = useInfiniteQuery(taskOccurrencesQuery({ ...window, status: status === 'completed' ? 'completed' : 'open', limit: 100 }))
  const seen = useRef(new Set<string>())
  const [reconciling, setReconciling] = useState(false), [reconcileError, setReconcileError] = useState(false)
  const rows = series.data?.pages.flatMap(p => p.items) ?? []
  const entries = occurrences.data?.pages.flatMap(p => p.items) ?? []
  useEffect(() => {
    const selected = (series.data?.pages.flatMap(page => page.items) ?? []).filter(row => !row.archived && !seen.current.has(row.id)).slice(0, 20).map(row => row.id)
    if (!selected.length) return
    const controller = new AbortController()
    selected.forEach(id => seen.current.add(id))
    setReconciling(true)
    void (async () => {
      let changed = false
      const finished = new Set<string>()
      try {
        for (const id of selected) {
          if (controller.signal.aborted) break
          await reconcileTask(id, { signal: controller.signal }); finished.add(id); changed = true
        }
      } catch { if (!controller.signal.aborted) setReconcileError(true) }
      finally {
        if (controller.signal.aborted) selected.filter(id => !finished.has(id)).forEach(id => seen.current.delete(id))
        if (!controller.signal.aborted) { setReconciling(false); if (changed) void client.invalidateQueries({ queryKey: ['tasks'] }) }
      }
    })()
    return () => controller.abort()
  }, [series.data, client, retryReconcile])
  const save = async (body: TaskCreate) => {
    if (busy) return
    setBusy(true); setError(undefined)
    try { await unwrap(tasksCreate({ body, throwOnError: true })); await client.invalidateQueries({ queryKey: ['tasks'] }); setCreating(false) }
    catch { setError(t.saveError) } finally { setBusy(false) }
  }
  if (creating) return <div><Button variant="ghost" onClick={() => setCreating(false)}>{t.back}</Button><TaskForm save={body => { void save(body) }} busy={busy} error={error} /></div>
  const visible = rows.filter(row => status !== 'archived' || row.archived)
  const joined = visible.flatMap(row => entries.filter(item => item.series_id === row.id).map(item => ({ row, item })))
  const groups = [t.overdue, t.today, t.later] as const
  const group = (day: string, zone: string | null) => { const today = localToday(zone); return day < today ? t.overdue : day === today ? t.today : t.later }
  return <main className="le-prompts"><h1 className="heading">{t.title}</h1><Button variant="primary" onClick={() => { setError(undefined); setCreating(true) }}>{t.create}</Button>
    <div>{(['open', 'completed', 'archived'] as const).map(value => <Button key={value} variant={status === value ? 'primary' : 'secondary'} aria-pressed={status === value} onClick={() => { setStatus(value); persistFilter('status', value) }}>{value === 'open' ? t.open : value === 'completed' ? t.completed : t.archived}</Button>)}</div>
    <label className="le-field"><span className="le-label">{t.source}</span><select className="le-input" value={source} onChange={event => { setSource(event.target.value); persistFilter('source', event.target.value) }}><option value="all">{t.allSources}</option><option value="unlinked">{t.unlinked}</option>{accounts.data?.map(account => <option key={account.id} value={account.id}>{account.email_address}</option>)}</select></label>
    <p>{t.period}: {window.due_from} – {window.due_to}</p><div><Button variant="secondary" onClick={() => setPeriod(value => value - 1)}>{t.previousPeriod}</Button><Button variant="secondary" onClick={() => setPeriod(value => value + 1)}>{t.nextPeriod}</Button></div>
    {(series.isPending || occurrences.isPending) && <><p role="status">{t.loading}</p>{[0, 1, 2].map(i => <div key={i} className="le-prompt-placeholder" aria-hidden="true" />)}</>}
    {(series.isError || occurrences.isError) && <Notice tone="danger" action={{ label: t.retry, onClick: () => { void series.refetch(); void occurrences.refetch() } }}>{t.error}</Notice>}
    {(reconciling || rows.some(row => !row.complete)) && <p role="status">{t.incomplete} {window.due_from} – {window.due_to}</p>}
    {reconcileError && <Notice tone="danger" action={{ label: t.retry, onClick: () => { seen.current.clear(); setReconcileError(false); setRetryReconcile(value => value + 1) } }}>{t.error}</Notice>}
    {!series.isPending && !occurrences.isPending && status !== 'archived' && !joined.length && !series.hasNextPage && !occurrences.hasNextPage && !reconciling && <p>{status === 'completed' ? t.emptyCompleted : t.empty}</p>}
    {status === 'archived' ? <ul>{visible.map(row => <li key={row.id}><a className="le-link" href={`/tasks/${encodeURIComponent(row.id)}`}>{row.title}</a>{row.schedule && <> · {formatTaskDue(row.schedule.start_local)} · {formatTaskRule(row.schedule.rrule)}</>}{row.source_message_id && <> · <SourceMail id={row.source_message_id} /></>}</li>)}</ul> : groups.map(label => { const items = joined.filter(({ row, item }) => group(item.due_local.slice(0, 10), row.schedule?.timezone ?? null) === label); return items.length ? <section key={label}><h2>{label}</h2><ul>{items.map(({ row, item }) => <li key={item.id}><a className="le-link" href={`/tasks/${encodeURIComponent(row.id)}`}>{row.title}</a> · {formatTaskDue(item.due_local)} · {formatTaskRule(row.schedule?.rrule)}{row.source_message_id && <> · <SourceMail id={row.source_message_id} /></>}</li>)}</ul></section> : null })}
    {(series.hasNextPage || occurrences.hasNextPage) && <Button variant="secondary" onClick={() => { if (series.hasNextPage) void series.fetchNextPage(); if (occurrences.hasNextPage) void occurrences.fetchNextPage() }}>{t.more}</Button>}
  </main>
}

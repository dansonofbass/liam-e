// i18n-exempt: route paths, CSS classes and API values.
import { useInfiniteQuery, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate, useSearch } from '@tanstack/react-router'
import { useEffect, useRef, useState } from 'react'
import { tasksCreate } from '../api/generated/sdk.gen'
import type { TaskCreate } from '../api/generated/types.gen'
import { accountsQuery, taskListQuery, taskOccurrencesQuery } from '../api/queries'
import { unwrap } from '../api/unwrap'
import { Button, Notice } from '../ds'
import { de } from '../i18n/de'
import { TaskForm } from './TaskForm'
import { TaskSelect } from './TaskSelect'
import { localToday, taskWindow } from './window'
import { reconcileTask } from './reconcile'
import { SourceMail } from './SourceMail'
import { formatTaskDue, formatTaskRule } from './format'
import type { TaskSearch } from './filters'

const t = de.tasks
export function TasksPage() {
  const [creating, setCreating] = useState(false), [busy, setBusy] = useState(false), [error, setError] = useState<string>()
  const search = useSearch({ strict: false }) as TaskSearch
  const navigate = useNavigate()
  const status = search.status ?? 'open'
  const source = search.source === 'account' ? search.source_account_id! : search.source ?? 'all'
  const changeSearch = (change: Partial<TaskSearch>) => { void navigate({ to: '/tasks', search: previous => ({ ...previous, ...change }), replace: true }) }
  const [retryReconcile, setRetryReconcile] = useState(0)
  const [period, setPeriod] = useState(0), [base] = useState(() => new Date())
  const window = taskWindow(base, period)
  const client = useQueryClient(), accounts = useQuery(accountsQuery())
  const sourceFilter = source === 'all' ? { source: 'all' as const } : source === 'unlinked' ? { source: 'unlinked' as const } : { source: 'account' as const, source_account_id: source }
  const series = useInfiniteQuery(taskListQuery({ ...window, ...sourceFilter, status: status === 'archived' ? 'archived' : undefined, limit: 100 }))
  const occurrences = useInfiniteQuery(taskOccurrencesQuery({ ...window, status: status === 'completed' ? 'completed' : 'open', limit: 100 }))
  const skipped = useInfiniteQuery({ ...taskOccurrencesQuery({ ...window, status: 'skipped', limit: 100 }), enabled: status === 'completed' })
  const skippedActive = status === 'completed'
  const loading = series.isPending || occurrences.isPending || (skippedActive && skipped.isPending)
  const failed = series.isError || occurrences.isError || (skippedActive && skipped.isError)
  const hasMore = series.hasNextPage || occurrences.hasNextPage || (skippedActive && skipped.hasNextPage)
  const seen = useRef(new Set<string>())
  const [reconciling, setReconciling] = useState(false), [reconcileError, setReconcileError] = useState(false)
  const rows = series.data?.pages.flatMap(p => p.items) ?? []
  const entries = [...(occurrences.data?.pages.flatMap(p => p.items) ?? []), ...(skippedActive ? skipped.data?.pages.flatMap(p => p.items) ?? [] : [])]
    .sort((a, b) => a.due_local.localeCompare(b.due_local) || a.id.localeCompare(b.id))
  useEffect(() => {
    const selected = (series.data?.pages.flatMap(page => page.items) ?? []).filter(row => !row.archived && !seen.current.has(row.id)).slice(0, 20).map(row => row.id)
    if (!selected.length) return
    const controller = new AbortController()
    const finished = new Set<string>()
    selected.forEach(id => seen.current.add(id))
    setReconciling(true)
    void (async () => {
      let changed = false
      try {
        for (const id of selected) {
          if (controller.signal.aborted) break
          await reconcileTask(id, { signal: controller.signal })
          if (controller.signal.aborted) break
          finished.add(id); changed = true
        }
      } catch { if (!controller.signal.aborted) setReconcileError(true) }
      finally {
        if (!controller.signal.aborted) { setReconciling(false); if (changed) void client.invalidateQueries({ queryKey: ['tasks'] }) }
      }
    })()
    return () => {
      controller.abort()
      // Cleanup owns its reservations and runs before a replacement effect starts.
      selected.filter(id => !finished.has(id)).forEach(id => seen.current.delete(id))
      setReconciling(false)
    }
  }, [series.data, client, retryReconcile])
  const save = async (body: TaskCreate) => {
    if (busy) return
    setBusy(true); setError(undefined)
    try { await unwrap(tasksCreate({ body, throwOnError: true })); await client.invalidateQueries({ queryKey: ['tasks'] }); setCreating(false) }
    catch { setError(t.saveError) } finally { setBusy(false) }
  }
  if (creating) return <div><Button variant="ghost" onClick={() => setCreating(false)}>{t.back}</Button><TaskForm save={body => { void save(body) }} busy={busy} error={error} /></div>
  const visible = rows.filter(row => status !== 'archived' || row.archived)
  const seriesById = new Map(visible.map(row => [row.id, row]))
  const joined = entries.flatMap(item => { const row = seriesById.get(item.series_id); return row ? [{ row, item }] : [] })
  const groups = [t.overdue, t.today, t.later] as const
  const group = (day: string, zone: string | null) => { const today = localToday(zone); return day < today ? t.overdue : day === today ? t.today : t.later }
  return <main className="le-prompts"><h1 className="heading">{t.title}</h1><Button variant="primary" onClick={() => { setError(undefined); setCreating(true) }}>{t.create}</Button>
    <div>{(['open', 'completed', 'archived'] as const).map(value => <Button key={value} variant={status === value ? 'primary' : 'secondary'} aria-pressed={status === value} onClick={() => changeSearch({ status: value === 'open' ? undefined : value })}>{value === 'open' ? t.open : value === 'completed' ? t.completed : t.archived}</Button>)}</div>
    <TaskSelect label={t.source} value={source} onChange={value => changeSearch(value === 'all' ? { source: undefined, source_account_id: undefined } : value === 'unlinked' ? { source: 'unlinked', source_account_id: undefined } : { source: 'account', source_account_id: value })} options={[{ value: 'all', label: t.allSources }, { value: 'unlinked', label: t.unlinked }, ...(accounts.data?.map(account => ({ value: account.id, label: account.email_address })) ?? [])]} />
    <p>{t.period}: {formatTaskDue(window.due_from)} – {formatTaskDue(window.due_to)}</p><div><Button variant="secondary" onClick={() => setPeriod(value => value - 1)}>{t.previousPeriod}</Button><Button variant="secondary" onClick={() => setPeriod(value => value + 1)}>{t.nextPeriod}</Button></div>
    {loading && <><p role="status">{t.loading}</p>{[0, 1, 2].map(i => <div key={i} className="le-prompt-placeholder" aria-hidden="true" />)}</>}
    {failed && <Notice tone="danger" action={{ label: t.retry, onClick: () => { void series.refetch(); void occurrences.refetch(); if (skippedActive) void skipped.refetch() } }}>{t.error}</Notice>}
    {reconciling && <p role="status">{t.incomplete} {formatTaskDue(window.due_from)} – {formatTaskDue(window.due_to)}</p>}
    {reconcileError && <Notice tone="danger" action={{ label: t.retry, onClick: () => { seen.current.clear(); setReconcileError(false); setRetryReconcile(value => value + 1) } }}>{t.error}</Notice>}
    {!loading && !failed && status !== 'archived' && !joined.length && !hasMore && !reconciling && <p>{status === 'completed' ? t.emptyCompleted : t.empty}</p>}
    {status === 'archived' ? <ul>{visible.map(row => <li key={row.id}><a className="le-link" href={`/tasks/${encodeURIComponent(row.id)}`}>{row.title}</a>{row.schedule && <> · {formatTaskDue(row.schedule.start_local)} · {formatTaskRule(row.schedule.rrule)}</>}{row.source_message_id && <> · <SourceMail id={row.source_message_id} /></>}</li>)}</ul> : groups.map(label => { const items = joined.filter(({ row, item }) => group(item.due_local.slice(0, 10), row.schedule?.timezone ?? null) === label); return items.length ? <section key={label}><h2>{label}</h2><ul>{items.map(({ row, item }) => <li key={item.id}><a className="le-link" href={`/tasks/${encodeURIComponent(row.id)}`}>{row.title}</a> · {formatTaskDue(item.due_local)} · {formatTaskRule(row.schedule?.rrule)}{item.status === 'skipped' && <> · {t.skipped}</>}{row.source_message_id && <> · <SourceMail id={row.source_message_id} /></>}</li>)}</ul></section> : null })}
    {hasMore && <Button variant="secondary" onClick={() => { if (series.hasNextPage) void series.fetchNextPage(); if (occurrences.hasNextPage) void occurrences.fetchNextPage(); if (skippedActive && skipped.hasNextPage) void skipped.fetchNextPage() }}>{t.more}</Button>}
  </main>
}

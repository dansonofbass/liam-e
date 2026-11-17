import { useQueryClient, type InfiniteData, type QueryKey } from '@tanstack/react-query'
import { createContext, createElement, useContext, useEffect, useRef, useState, type ReactNode } from 'react'
import { mailActionsUndo, mailMessageAction } from '../api/generated/sdk.gen'
import type { MessageDetailOut, MessageListItemOut, MessagePageOut } from '../api/generated/types.gen'
import { de } from '../i18n/de'
import { errorCode } from '../api/unwrap'
import { useBreakpoint } from '../shell/useBreakpoint'

export type Clock = { now(): number; setTimeout(fn: () => void, ms: number): ReturnType<typeof setTimeout>; clearTimeout(id: ReturnType<typeof setTimeout>): void }
const systemClock: Clock = { now: () => Date.now(), setTimeout: (fn, ms) => setTimeout(fn, ms), clearTimeout: id => clearTimeout(id) }
type Removal = 'archive' | 'trash' | 'spam'
type Kind = Removal | 'mark_read' | 'mark_unread'
const removes = (kind: Kind | 'remove'): kind is Removal => kind === 'archive' || kind === 'trash' || kind === 'spam'
type Toast = { tone: 'success' | 'danger'; text: string; undoable: boolean }
type Change = { key: QueryKey; page: number; index: number; row: MessageListItemOut }
export type UndoEntry = { actionId: string; messageId: string; kind: Kind; changes: Change[]; previousRead?: boolean; text: string; label: string; deadline: number; pending: boolean }
const LIMIT = 20
// A provider can stop responding; release the queue after fifteen seconds.
const UNDO_TIMEOUT_MS = 15_000

export function useMailActions({ clock = systemClock }: { clock?: Clock } = {}) {
  const client = useQueryClient()
  const breakpoint = useBreakpoint()
  const [entries, setEntries] = useState<UndoEntry[]>([])
  const entriesRef = useRef<UndoEntry[]>([])
  const [notice, setNotice] = useState<string | null>(null)
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
  const noticeTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
  const reservations = useRef(0)
  const [reserved, setReserved] = useState(0)
  const pending = useRef(0)
  const queues = useRef(new Map<string, Promise<unknown>>())
  const reconcile = useRef(false)
  const settle = () => {
    if (--pending.current === 0 && reconcile.current) {
      reconcile.current = false
      void client.invalidateQueries({ queryKey: ['messages'] })
    }
  }
  const schedule = (next: UndoEntry[]) => {
    if (timer.current !== undefined) clock.clearTimeout(timer.current)
    timer.current = undefined
    const deadlines = next.filter(entry => !entry.pending).map(entry => entry.deadline)
    if (deadlines.length) timer.current = clock.setTimeout(() => {
      timer.current = undefined
      publish(entriesRef.current.filter(entry => entry.pending || entry.deadline > clock.now()))
    }, Math.max(0, Math.min(...deadlines) - clock.now()))
  }
  const publish = (next: UndoEntry[]) => {
    entriesRef.current = next
    setEntries(next)
    schedule(next)
  }
  const notify = (text: string) => {
    setNotice(text)
    if (noticeTimer.current !== undefined) clock.clearTimeout(noticeTimer.current)
    noticeTimer.current = clock.setTimeout(() => { noticeTimer.current = undefined; setNotice(null) }, 10_000)
  }
  useEffect(() => () => {
    if (timer.current !== undefined) clock.clearTimeout(timer.current)
    if (noticeTimer.current !== undefined) clock.clearTimeout(noticeTimer.current)
  }, [clock])
  const restore = (changes: Change[], removal: boolean) => {
    for (const { key, page, index, row } of changes) {
      client.setQueryData<InfiniteData<MessagePageOut>>(key, data => {
        if (!data) return data
        if (removal && data.pages.some(p => p.items.some(item => item.id === row.id))) return data
        return { ...data, pages: data.pages.map((p, i) => {
          if (removal && i === page) {
            const items = [...p.items]
            items.splice(Math.min(index, items.length), 0, row)
            return { ...p, items }
          }
          return removal ? p : { ...p, items: p.items.map(item => item.id === row.id ? { ...item, is_read: row.is_read } : item) }
        }) }
      })
    }
  }
  const update = (id: string, kind: Kind | 'remove') => {
    client.setQueriesData<InfiniteData<MessagePageOut>>({ queryKey: ['messages'] }, data => data && ({
      ...data, pages: data.pages.map(page => ({ ...page, items: removes(kind) || kind === 'remove'
        ? page.items.filter(item => item.id !== id)
        : page.items.map(item => item.id === id ? { ...item, is_read: kind === 'mark_read' } : item) })),
    }))
  }
  // Both mutations and undo share the per-message queue. Reserve capacity before enqueueing.
  const enqueue = <T,>(id: string, execute: () => Promise<T>): Promise<T> => {
    const previous = queues.current.get(id)
    const work = previous ? previous.catch(() => {}).then(execute) : execute()
    queues.current.set(id, work)
    void work.then(() => { if (queues.current.get(id) === work) queues.current.delete(id) }, () => { if (queues.current.get(id) === work) queues.current.delete(id) })
    return work
  }
  const checkCapacity = () => {
    const active = entriesRef.current.filter(entry => entry.pending || entry.deadline > clock.now())
    if (active.length !== entriesRef.current.length) publish(active)
    if (active.length + reservations.current < LIMIT) return true
    notify(de.inbox.undoCapacity)
    return false
  }
  const run = (id: string, kind: Kind, options?: { silent?: boolean }) => {
    // Refused before anything changed: nothing was removed, so nothing came back.
    if (!options?.silent && !checkCapacity()) return Promise.resolve(false)
    if (!options?.silent) { reservations.current++; setReserved(reservations.current) }
    return enqueue(id, () => execute(id, kind, options))
  }
  const execute = async (id: string, kind: Kind, options?: { silent?: boolean }) => {
    ++pending.current
    const changes: Change[] = []
    const removal = removes(kind)
    let previousRead: boolean | undefined
    const rollback = () => {
      restore(changes, removal)
      if (previousRead !== undefined) client.setQueryData<MessageDetailOut>(['message', id], data => data && { ...data, is_read: previousRead! })
      reconcile.current = true
    }
    try {
      await client.cancelQueries({ queryKey: ['messages'] })
      if (!removal) {
        await client.cancelQueries({ queryKey: ['message', id], exact: true })
        previousRead = client.getQueryData<MessageDetailOut>(['message', id])?.is_read
        client.setQueryData<MessageDetailOut>(['message', id], data => data && { ...data, is_read: kind === 'mark_read' })
      }
      for (const [key, data] of client.getQueriesData<InfiniteData<MessagePageOut>>({ queryKey: ['messages'] })) {
        data?.pages.forEach((page, pageIndex) => page.items.forEach((row, index) => {
          if (row.id === id) changes.push({ key, page: pageIndex, index, row })
        }))
      }
      update(id, kind)
      const result = await mailMessageAction({ path: { message_id: id }, body: { kind } })
      if (result.response?.status === 404) {
        update(id, 'remove')
        if (!options?.silent) notify(de.proposalErrors.item_gone)
      } else if (result.response?.status === 409) {
        rollback()
        if (!options?.silent) notify(de.proposalErrors.action_unsupported)
        return changes.length > 0
      } else if (!result.data || result.response?.status !== 200) {
        rollback()
        if (!options?.silent) notify(result.response?.status === 502 && errorCode(result.error) === 'provider_failed' ? de.errors.provider_failed : de.errors.action_uncertain)
        return changes.length > 0
      } else {
        if (removal) reconcile.current = true
        if (!options?.silent) {
          const text = breakpoint === 'mobile' ? de.inbox.doneShort[kind] : de.inbox.done[kind](result.data.message.subject)
          setNotice(null)
          publish([...entriesRef.current, { actionId: result.data.action_id, messageId: id, kind, changes, previousRead, text, label: de.inbox.done[kind](result.data.message.subject), deadline: clock.now() + 10_000, pending: false }])
        }
        void client.invalidateQueries({ queryKey: ['summary'] })
        void client.invalidateQueries({ queryKey: ['message', id] })
      }
    } catch {
      rollback()
      if (!options?.silent) notify(de.errors.action_uncertain)
      return changes.length > 0
    } finally {
      if (!options?.silent) { reservations.current--; setReserved(reservations.current) }
      settle()
    }
  }
  const undo = (actionId?: string) => {
    const selected = actionId ? entriesRef.current.find(entry => entry.actionId === actionId) : entriesRef.current.at(-1)
    if (!selected || selected.pending) return Promise.resolve()
    if (clock.now() >= selected.deadline) { publish(entriesRef.current.filter(entry => entry !== selected)); return Promise.resolve() }
    publish(entriesRef.current.map(entry => entry === selected ? { ...entry, pending: true } : entry))
    return enqueue(selected.messageId, async () => {
      ++pending.current
      const controller = new AbortController()
      let timedOut = false
      let timeout: ReturnType<typeof setTimeout> | undefined
      const deadline = new Promise<never>((_, reject) => {
        timeout = clock.setTimeout(() => {
          timedOut = true
          controller.abort()
          reject(new Error('undo_timeout')) // i18n-exempt
        }, UNDO_TIMEOUT_MS)
      })
      try {
        const result = await Promise.race([mailActionsUndo({ body: { action_ids: [selected.actionId] }, signal: controller.signal }), deadline])
        if (result.data?.restored.includes(selected.actionId)) {
          restore(selected.changes, removes(selected.kind))
          if (!removes(selected.kind) && selected.previousRead !== undefined) client.setQueryData<MessageDetailOut>(['message', selected.messageId], data => data && { ...data, is_read: selected.previousRead! })
        } else if (result.data?.skipped.includes(selected.actionId)) notify(de.inbox.undoSkipped)
        else if (result.data?.expired.includes(selected.actionId)) notify(de.inbox.undoExpired)
        else if (result.data?.failed.includes(selected.actionId)) notify(de.inbox.undoFailed)
        else notify(de.inbox.undoUncertain)
      } catch { notify(timedOut ? de.inbox.undoTimeout : de.inbox.undoUncertain) }
      finally {
        if (timeout !== undefined) clock.clearTimeout(timeout)
        publish(timedOut
          ? entriesRef.current.map(entry => entry.actionId === selected.actionId ? { ...entry, pending: false, deadline: clock.now() + 10_000 } : entry)
          : entriesRef.current.filter(entry => entry.actionId !== selected.actionId))
        reconcile.current = true
        void client.invalidateQueries({ queryKey: ['summary'] })
        void client.invalidateQueries({ queryKey: ['message', selected.messageId] })
        settle()
      }
    })
  }
  const latest = entries.at(-1)
  const toast: Toast | null = notice ? { tone: 'danger', text: notice, undoable: false } : latest ? { tone: 'success', text: latest.text, undoable: true } : null
  return { run, undo, notify, toast, entries, checkCapacity, capacityAvailable: entries.filter(entry => entry.pending || entry.deadline > clock.now()).length + reserved < LIMIT }
}

const MailActionsContext = createContext<ReturnType<typeof useMailActions> | null>(null)

export function MailActionsProvider({ children, clock }: { children: ReactNode; clock?: Clock }) {
  const actions = useMailActions({ clock })
  return createElement(MailActionsContext.Provider, { value: actions }, children)
}

export function useMailActionsContext() {
  const actions = useContext(MailActionsContext)
  if (!actions) throw new Error('useMailActionsContext must be used within MailActionsProvider')
  return actions
}

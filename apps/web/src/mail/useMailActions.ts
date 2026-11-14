import { useQueryClient, type InfiniteData, type QueryKey } from '@tanstack/react-query'
import { createContext, createElement, useContext, useEffect, useRef, useState, type ReactNode } from 'react'
import { mailActionsUndo, mailMessageAction } from '../api/generated/sdk.gen'
import type { MessageDetailOut, MessageListItemOut, MessagePageOut } from '../api/generated/types.gen'
import { de } from '../i18n/de'
import { useBreakpoint } from '../shell/useBreakpoint'

export type Clock = { now(): number; setTimeout(fn: () => void, ms: number): ReturnType<typeof setTimeout>; clearTimeout(id: ReturnType<typeof setTimeout>): void }
const systemClock: Clock = { now: () => Date.now(), setTimeout: (fn, ms) => setTimeout(fn, ms), clearTimeout: id => clearTimeout(id) }
type Kind = 'archive' | 'trash' | 'mark_read' | 'mark_unread'
type Toast = { tone: 'success' | 'danger'; text: string; undoable: boolean }
type Change = { key: QueryKey; page: number; index: number; row: MessageListItemOut }

export function useMailActions({ clock = systemClock }: { clock?: Clock } = {}) {
  const client = useQueryClient()
  const breakpoint = useBreakpoint()
  const [toast, setToast] = useState<Toast | null>(null)
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
  const target = useRef<{ actionId: string; changes: Change[]; deadline: number } | null>(null)
  const sequence = useRef(0)
  const undoPending = useRef(false)
  const pending = useRef(0)
  const queues = useRef(new Map<string, Promise<unknown>>())
  const reconcile = useRef(false)
  const settle = () => {
    if (--pending.current === 0 && reconcile.current) {
      reconcile.current = false
      void client.invalidateQueries({ queryKey: ['messages'] })
    }
  }

  const clear = () => {
    if (timer.current !== undefined) clock.clearTimeout(timer.current)
    timer.current = undefined
    target.current = null
    setToast(null)
  }
  const show = (value: Toast, undoTarget?: { actionId: string; changes: Change[] }) => {
    clear()
    if (undoTarget) target.current = { ...undoTarget, deadline: clock.now() + 10_000 }
    setToast(value)
    timer.current = clock.setTimeout(() => { timer.current = undefined; target.current = null; setToast(null) }, 10_000)
  }
  useEffect(() => () => { if (timer.current !== undefined) clock.clearTimeout(timer.current) }, [clock])
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
      ...data, pages: data.pages.map(page => ({ ...page, items: kind === 'archive' || kind === 'trash' || kind === 'remove'
        ? page.items.filter(item => item.id !== id)
        : page.items.map(item => item.id === id ? { ...item, is_read: kind === 'mark_read' } : item) })),
    }))
  }
  const run = (id: string, kind: Kind, options?: { silent?: boolean }) => {
    const current = options?.silent ? sequence.current : ++sequence.current
    if (!options?.silent) clear()
    const previous = queues.current.get(id)
    const work = previous ? previous.catch(() => {}).then(() => execute(id, kind, options, current)) : execute(id, kind, options, current)
    queues.current.set(id, work)
    void work.then(() => { if (queues.current.get(id) === work) queues.current.delete(id) }, () => { if (queues.current.get(id) === work) queues.current.delete(id) })
    return work
  }
  const execute = async (id: string, kind: Kind, options: { silent?: boolean } | undefined, current: number) => {
    ++pending.current
    const changes: Change[] = []
    const removal = kind === 'archive' || kind === 'trash'
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
        if (!options?.silent && current === sequence.current) show({ tone: 'danger', text: de.proposalErrors.item_gone, undoable: false })
      } else if (result.response?.status === 409) {
        rollback()
        if (!options?.silent && current === sequence.current) show({ tone: 'danger', text: de.proposalErrors.action_unsupported, undoable: false })
        return changes.length > 0
      } else if (!result.data || result.response?.status !== 200) {
        rollback()
        if (!options?.silent && current === sequence.current) show({ tone: 'danger', text: de.errors.provider_failed, undoable: false })
        return changes.length > 0
      } else {
        if (removal) reconcile.current = true
        if (!options?.silent && (kind === 'archive' || kind === 'trash') && current === sequence.current) {
          const text = breakpoint === 'mobile' ? de.inbox.doneShort[kind] : de.inbox.done[kind](result.data.message.subject)
          show({ tone: 'success', text, undoable: true }, { actionId: result.data.action_id, changes })
        }
        void client.invalidateQueries({ queryKey: ['summary'] })
        void client.invalidateQueries({ queryKey: ['message', id] })
      }
    } catch {
      rollback()
      if (!options?.silent && current === sequence.current) show({ tone: 'danger', text: de.errors.provider_failed, undoable: false })
      return changes.length > 0
    } finally { settle() }
  }
  const undo = async () => {
    const selected = target.current
    if (!selected || undoPending.current) return
    if (clock.now() >= selected.deadline) { clear(); return }
    undoPending.current = true
    ++pending.current
    try {
      const result = await mailActionsUndo({ body: { action_ids: [selected.actionId] } })
      if (result.data?.restored.includes(selected.actionId)) {
        restore(selected.changes, true)
        if (target.current === selected) clear()
        reconcile.current = true
        void client.invalidateQueries({ queryKey: ['summary'] })
      } else if (target.current === selected) show({ tone: 'danger', text: de.proposal.requestError, undoable: false })
    } catch {
      if (target.current === selected) show({ tone: 'danger', text: de.proposal.requestError, undoable: false })
    } finally { undoPending.current = false; settle() }
  }
  const notify = (text: string) => {
    ++sequence.current
    show({ tone: 'danger', text, undoable: false })
  }
  return { run, undo, notify, toast }
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

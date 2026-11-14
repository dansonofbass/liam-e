import { useQueryClient, type InfiniteData, type QueryKey } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import { mailActionsUndo, mailMessageAction } from '../api/generated/sdk.gen'
import type { MessagePageOut } from '../api/generated/types.gen'
import { de } from '../i18n/de'
import { useBreakpoint } from '../shell/useBreakpoint'

export type Clock = { now(): number; setTimeout(fn: () => void, ms: number): ReturnType<typeof setTimeout>; clearTimeout(id: ReturnType<typeof setTimeout>): void }
const systemClock: Clock = { now: () => Date.now(), setTimeout: (fn, ms) => setTimeout(fn, ms), clearTimeout: id => clearTimeout(id) }
type Kind = 'archive' | 'trash' | 'mark_read' | 'mark_unread'
type Toast = { tone: 'success' | 'danger'; text: string; undoable: boolean }
type Snapshot = [QueryKey, InfiniteData<MessagePageOut> | undefined][]

export function useMailActions({ clock = systemClock }: { clock?: Clock } = {}) {
  const client = useQueryClient()
  const breakpoint = useBreakpoint()
  const [toast, setToast] = useState<Toast | null>(null)
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
  const target = useRef<{ actionId: string; snapshot: Snapshot; deadline: number } | null>(null)
  const sequence = useRef(0)
  const undoPending = useRef(false)

  const clear = () => {
    if (timer.current !== undefined) clock.clearTimeout(timer.current)
    timer.current = undefined
    target.current = null
    setToast(null)
  }
  const show = (value: Toast, undoTarget?: { actionId: string; snapshot: Snapshot }) => {
    clear()
    if (undoTarget) target.current = { ...undoTarget, deadline: clock.now() + 10_000 }
    setToast(value)
    timer.current = clock.setTimeout(() => { timer.current = undefined; target.current = null; setToast(null) }, 10_000)
  }
  useEffect(() => () => { if (timer.current !== undefined) clock.clearTimeout(timer.current) }, [clock])
  const restore = (snapshot: Snapshot) => { for (const [key, data] of snapshot) client.setQueryData(key, data) }
  const update = (id: string, kind: Kind | 'remove') => {
    client.setQueriesData<InfiniteData<MessagePageOut>>({ queryKey: ['messages'] }, data => data && ({
      ...data, pages: data.pages.map(page => ({ ...page, items: kind === 'archive' || kind === 'trash' || kind === 'remove'
        ? page.items.filter(item => item.id !== id)
        : page.items.map(item => item.id === id ? { ...item, is_read: kind === 'mark_read' } : item) })),
    }))
  }
  const run = async (id: string, kind: Kind) => {
    const current = ++sequence.current
    clear()
    await client.cancelQueries({ queryKey: ['messages'] })
    const snapshot = client.getQueriesData<InfiniteData<MessagePageOut>>({ queryKey: ['messages'] })
    update(id, kind)
    try {
      const result = await mailMessageAction({ path: { message_id: id }, body: { kind } })
      if (result.response?.status === 404) {
        update(id, 'remove')
        if (current === sequence.current) show({ tone: 'danger', text: de.proposalErrors.item_gone, undoable: false })
      } else if (result.response?.status === 409) {
        restore(snapshot)
        if (current === sequence.current) show({ tone: 'danger', text: de.proposalErrors.action_unsupported, undoable: false })
      } else if (!result.data || result.response?.status !== 200) {
        restore(snapshot)
        if (current === sequence.current) show({ tone: 'danger', text: de.errors.provider_failed, undoable: false })
      } else {
        if ((kind === 'archive' || kind === 'trash') && current === sequence.current) {
          const text = breakpoint === 'mobile' ? de.inbox.doneShort[kind] : de.inbox.done[kind](result.data.message.subject)
          show({ tone: 'success', text, undoable: true }, { actionId: result.data.action_id, snapshot })
        }
        void client.invalidateQueries({ queryKey: ['summary'] })
        void client.invalidateQueries({ queryKey: ['message', id] })
      }
    } catch {
      restore(snapshot)
      if (current === sequence.current) show({ tone: 'danger', text: de.errors.provider_failed, undoable: false })
    }
  }
  const undo = async () => {
    const selected = target.current
    if (!selected || undoPending.current) return
    if (clock.now() >= selected.deadline) { clear(); return }
    undoPending.current = true
    try {
      const result = await mailActionsUndo({ body: { action_ids: [selected.actionId] } })
      if (target.current !== selected) return
      if (result.data?.restored.includes(selected.actionId)) {
        restore(selected.snapshot)
        clear()
        void client.invalidateQueries({ queryKey: ['messages'] })
        void client.invalidateQueries({ queryKey: ['summary'] })
      } else show({ tone: 'danger', text: de.proposal.requestError, undoable: false })
    } catch {
      if (target.current === selected) show({ tone: 'danger', text: de.proposal.requestError, undoable: false })
    } finally { undoPending.current = false }
  }
  return { run, undo, toast }
}

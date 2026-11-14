import { useQueryClient, type QueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import { chatProposalCancel, chatProposalConfirm, mailActionsUndo } from '../api/generated/sdk.gen'
import type { ChatMessageOut, Proposal } from '../api/generated/types.gen'
import { errorCode, unwrap } from '../api/unwrap'
import { ConfirmCard, Notice } from '../ds'
import { de } from '../i18n/de'

type Clock = { now: () => number; setTimeout: (fn: () => void, ms: number) => ReturnType<typeof setTimeout>; clearTimeout: (id: ReturnType<typeof setTimeout>) => void }
const systemClock: Clock = { now: () => Date.now(), setTimeout: (fn, ms) => setTimeout(fn, ms), clearTimeout: id => clearTimeout(id) }
// A live card can be replaced by its history row; preserve edits and the undo deadline.
type CardState = { deadline?: number; deselected?: Set<string>; body?: string }
const cards = new WeakMap<QueryClient, Map<string, CardState>>()
function cardState(client: QueryClient, id: string): CardState {
  let entries = cards.get(client)
  if (!entries) { entries = new Map(); cards.set(client, entries) }
  let entry = entries.get(id)
  if (!entry) { entry = {}; entries.set(id, entry) }
  return entry
}
function useUndoWindow(client: QueryClient, id: string, clock: Clock) {
  const [deadline] = useState(() => {
    const entry = cardState(client, id)
    return entry.deadline ??= clock.now() + 10_000
  })
  const [visible, setVisible] = useState(() => clock.now() < deadline)
  useEffect(() => {
    const remaining = deadline - clock.now()
    if (remaining <= 0) { setVisible(false); return }
    const timer = clock.setTimeout(() => setVisible(false), remaining)
    return () => clock.clearTimeout(timer)
  }, [clock, deadline])
  return {
    visible: visible && clock.now() < deadline,
    beforeDeadline: () => clock.now() < deadline,
    expire: () => { cardState(client, id).deadline = 0; setVisible(false) },
  }
}

function safeLink(value: string | null): string | null {
  if (!value || !/^https?:/u.test(value)) return null
  try {
    const url = new URL(value)
    return url.protocol === 'http:' || url.protocol === 'https:' ? url.href : null
  } catch { return null }
}

function failureText(code: string | undefined, kind: Proposal['kind']): string {
  switch (code) {
    case 'item_gone': return kind === 'unsubscribe' ? de.proposalErrors.sender_gone : de.proposalErrors.item_gone
    case 'action_unsupported': return de.proposalErrors.action_unsupported
    case 'credentials_invalid': return de.proposalErrors.credentials_invalid
    case 'send_failed': return de.proposalErrors.send_failed
    case 'account_gone': return de.proposalErrors.account_gone
    case 'unsubscribe_rejected': case 'unsubscribe_blocked': case 'unsubscribe_unreachable': case 'unsubscribe_invalid': case 'unsubscribe_send_failed': return de.proposalErrors.unsubscribe_failed
    case 'proposal_not_pending': return de.proposalErrors.proposal_not_pending
    case 'selection_empty': return de.proposalErrors.selection_empty
    case 'host_not_allowed': return de.errors.host_not_allowed
    default: return de.proposal.requestError
  }
}

function Result({ message, proposal, clock }: { message: ChatMessageOut; proposal: Proposal; clock: Clock }) {
  const client = useQueryClient()
  const { visible, beforeDeadline, expire } = useUndoWindow(client, message.id, clock)
  const [undone, setUndone] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(false)
  const pending = useRef(false)
  const result = proposal.result
  const ids = result?.undo_action_ids ?? []
  const undo = async () => {
    if (pending.current || !beforeDeadline()) return
    pending.current = true; setBusy(true); setError(false)
    try {
      const outcome = await unwrap(mailActionsUndo({ body: { action_ids: ids }, throwOnError: true }))
      if (outcome.expired.length || outcome.failed.length || outcome.skipped.length) setError(true)
      else { expire(); setUndone(true) }
      void client.invalidateQueries({ queryKey: ['summary'] })
    } catch { setError(true) } finally { pending.current = false; setBusy(false) }
  }
  if (undone) return <Notice tone="info">{de.proposal.undone}</Notice>
  const text = proposal.kind === 'unsubscribe' ? de.proposal.results.unsubscribe(result?.done ?? 0, ids.length) : de.proposal.results[proposal.kind](result?.done ?? 0)
  return <><Notice tone={message.proposal_status === 'done' ? 'success' : 'info'} action={ids.length && visible && !busy ? { label: de.proposal.undo, onClick: () => { void undo() } } : undefined}>
    <span>{text}{message.proposal_status === 'partial' && de.proposal.partial[proposal.kind](result?.failed?.length ?? 0)}</span>
  </Notice>{result?.manual?.map(entry => {
    const href = safeLink(entry.link)
    const item = proposal.items.find(candidate => candidate.id === entry.id)
    return href ? <p key={entry.id}>{item?.title}{item && ': '}<a href={href} target="_blank" rel="noopener noreferrer">{de.proposal.manualLink}</a></p> : null
  })}{error && <Notice tone="danger">{de.proposal.requestError}</Notice>}</>
}

export function ProposalCard({ message, clock = systemClock }: { message: ChatMessageOut; clock?: Clock }) {
  const client = useQueryClient()
  const [updated, setUpdated] = useState<ChatMessageOut | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string>()
  const [, refresh] = useState(0)
  const pending = useRef(false)
  const current = updated?.id === message.id ? updated : message
  const proposal = current.proposal
  const apply = async (operation: () => Promise<ChatMessageOut>) => {
    if (pending.current) return
    pending.current = true; setBusy(true); setError(undefined)
    try {
      const result = await operation()
      setUpdated(result)
      client.setQueryData<ChatMessageOut[]>(['history', current.conversation_id], rows => rows?.map(row => row.id === result.id ? result : row))
      void client.invalidateQueries({ queryKey: ['history', current.conversation_id] })
      void client.invalidateQueries({ queryKey: ['summary'] })
    } catch (failure) { setError(errorCode(failure instanceof Error ? failure.cause : failure) ?? 'action_failed') } finally { pending.current = false; setBusy(false) }
  }
  if (!proposal) return null
  if (current.proposal_status === 'cancelled') return <p className="le-hint">{de.proposal.cancelled}</p>
  if (current.proposal_status === 'failed') return <Notice tone="danger">{failureText(proposal.result?.failed?.[0]?.code, proposal.kind)}</Notice>
  if (current.proposal_status === 'done' || current.proposal_status === 'partial') return <Result key={current.id} message={current} proposal={proposal} clock={clock} />
  if (current.proposal_status !== 'pending') return null
  const saved = cardState(client, current.id)
  const items = proposal.items.map(item => item.kind === 'sender' && !['one_click', 'one-click', 'post', 'mailto'].includes(item.method ?? '') ? { ...item, subtitle: `${item.subtitle} · ${de.proposal.manualSubtitle}` } : item)
  const irreversibleNote = proposal.irreversible ? proposal.kind === 'unsubscribe' ? de.proposal.irreversibleUnsubscribe : proposal.kind === 'send' ? de.proposal.irreversibleSend : undefined : undefined
  return <><ConfirmCard key={current.id} title={de.proposal.titles[proposal.kind](items.length)} reason={proposal.reason} items={items} irreversibleNote={irreversibleNote} confirmLabel={de.proposal.confirm[proposal.kind]} draft={proposal.kind === 'send' ? proposal.draft ?? undefined : undefined} deselected={saved.deselected ?? new Set<string>()} onDeselectedChange={value => { saved.deselected = value; refresh(n => n + 1) }} body={saved.body ?? proposal.draft?.body ?? ''} onBodyChange={value => { saved.body = value; refresh(n => n + 1) }} busy={busy} onConfirm={(selected_ids, body) => { void apply(() => unwrap(chatProposalConfirm({ path: { proposal_id: current.id }, body: { selected_ids, body }, throwOnError: true }))) }} onCancel={() => { void apply(() => unwrap(chatProposalCancel({ path: { proposal_id: current.id }, throwOnError: true }))) }} />{error && <Notice tone="danger">{failureText(error, proposal.kind)}</Notice>}</>
}

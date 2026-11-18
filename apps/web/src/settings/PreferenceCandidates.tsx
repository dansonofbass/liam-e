// i18n-exempt: route paths, API keys and CSS classes.
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useNavigate } from '@tanstack/react-router'
import { useRef, useState } from 'react'
import type { CandidateOut } from '../api/generated/types.gen'
import { preferenceCandidatePropose } from '../api/generated/sdk.gen'
import { errorCode, unwrap } from '../api/unwrap'
import { Button, Notice } from '../ds'
import { de } from '../i18n/de'
import { preferenceCandidatesQuery } from './preferenceQueries'

const t = de.preferenceCandidates
export function PreferenceCandidates() {
  const query = useQuery(preferenceCandidatesQuery())
  const rows = query.data?.filter(row => row.status === 'pending')
  return <section className="le-prompts" aria-label={t.title}>
    <h2 className="heading">{t.title}</h2><p>{t.description}</p>
    {query.isPending && <><p role="status">{t.loading}</p>{[0, 1, 2].map(i => <div className="le-prompt-placeholder" key={i} aria-hidden="true" />)}</>}
    {query.isError && <Notice tone="danger" action={{ label: de.chat.retry, onClick: () => { void query.refetch() } }}>{t.error}</Notice>}
    {rows?.length === 0 && <p>{t.empty}</p>}
    {rows?.map(row => <Candidate key={row.id} row={row} />)}
  </section>
}

function Candidate({ row }: { row: CandidateOut }) {
  const client = useQueryClient(), navigate = useNavigate()
  const [busy, setBusy] = useState(false), [blocked, setBlocked] = useState(false), [error, setError] = useState<string>()
  const lock = useRef(false)
  const propose = async () => {
    if (lock.current) return
    lock.current = true; setBusy(true); setError(undefined); setBlocked(false)
    try {
      const updated = await unwrap(preferenceCandidatePropose({ path: { candidate_id: row.id }, body: {}, throwOnError: true }))
      if (updated.proposal_id) {
        await client.invalidateQueries({ queryKey: ['history', row.conversation_id] })
        void navigate({ to: '/chat/$conversationId', params: { conversationId: row.conversation_id }, hash: `message-${updated.proposal_id}` })
      } else setBlocked(true)
      void client.invalidateQueries({ queryKey: ['preference-candidates'] })
    } catch (cause) {
      setError(errorCode(cause instanceof Error ? cause.cause : cause) === 'preference_candidate_gone' ? t.gone : t.error)
    } finally { lock.current = false; setBusy(false) }
  }
  return <div className="le-prompt-row">
    <strong>{de.preferences.keys[row.key]}</strong><span className="le-prompt-preview">{row.value}</span>
    <small>{row.scope === '*' ? de.preferences.global : row.account_name ?? de.prompts.scopeUnavailable}</small>
    {row.proposal_id ? <Link className="le-btn le-btn--secondary" to="/chat/$conversationId" params={{ conversationId: row.conversation_id }} hash={`message-${row.proposal_id}`}>{t.open}</Link>
      : <Button variant="secondary" disabled={busy} onClick={() => { void propose() }}>{t.review}</Button>}
    {blocked && <><Notice tone="info">{t.busySlot}</Notice><Link className="le-link" to="/chat/$conversationId" params={{ conversationId: row.conversation_id }}>{t.openConversation}</Link></>}
    {error && <Notice tone="danger">{error}</Notice>}
  </div>
}

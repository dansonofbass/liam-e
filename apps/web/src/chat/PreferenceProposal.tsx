// i18n-exempt: protocol values, query keys and CSS classes.
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useRef, useState } from 'react'
import type { PreferenceDecision } from '../api/generated/types.gen'
import { preferenceCandidatePropose } from '../api/generated/sdk.gen'
import { unwrap } from '../api/unwrap'
import { Button, Notice } from '../ds'
import { de } from '../i18n/de'
import { preferenceCandidatesQuery } from '../settings/preferenceQueries'
import './preference-proposal.css'

const t = de.preferenceCandidates
export function PreferenceProposal({ id, busy, error, clearError, confirm, cancel }: {
  id: string; busy: boolean; error?: string; clearError: () => void;
  confirm: (decision: PreferenceDecision) => void; cancel: () => void;
}) {
  const query = useQuery(preferenceCandidatesQuery(id)), client = useQueryClient()
  const [refreshing, setRefreshing] = useState(false), [refreshError, setRefreshError] = useState(false)
  const lock = useRef(false), heading = useRef<HTMLHeadingElement>(null)
  const row = query.data?.find(item => item.id === id)
  const conflict = error === 'preference_candidate_conflict'
  const review = async () => {
    if (lock.current) return
    lock.current = true; setRefreshing(true); setRefreshError(false)
    try {
      const updated = await unwrap(preferenceCandidatePropose({ path: { candidate_id: id }, body: { refresh: true }, throwOnError: true }))
      client.setQueryData(preferenceCandidatesQuery(id).queryKey, [updated])
      clearError()
      heading.current?.focus()
    } catch { setRefreshError(true) } finally { lock.current = false; setRefreshing(false) }
  }
  const decide = (choice: PreferenceDecision['choice']) => {
    if (row) confirm({ choice, expected_version: row.expected_version, expected_revision_id: row.expected_revision_id })
  }
  if (query.isPending) return <section className="le-confirm"><div className="le-confirm-head"><p role="status">{t.loading}</p><div className="le-prompt-placeholder" aria-hidden="true" /></div></section>
  if (query.isError) return <Notice tone="danger" action={{ label: de.chat.retry, onClick: () => { void query.refetch() } }}>{t.error}</Notice>
  if (!row || row.status !== 'pending' || !row.value || error === 'preference_candidate_gone') return <Notice tone="info">{t.gone}</Notice>
  const identical = row.previous_value === row.value
  return <section className="le-confirm le-preference-proposal">
    <div className="le-confirm-head"><h3 ref={heading} tabIndex={-1} className="le-confirm-title">{t.cardTitle}</h3>
      <p>{de.preferences.keys[row.key]} · {row.scope === '*' ? de.preferences.global : row.account_name ?? de.prompts.scopeUnavailable}</p>
    </div>
    <div className="le-preference-values">
      <div><h4>{t.before}</h4><p>{row.previous_value ?? t.none}</p></div>
      <div><h4>{t.proposed}</h4><p>{row.value}</p></div>
    </div>
    <details className="le-preference-source"><summary>{t.source}</summary><blockquote>{row.source_text}</blockquote></details>
    {identical && <Notice tone="info">{t.identical}</Notice>}
    <p className="le-preference-hint le-hint">{t.notSaved}</p>
    {conflict && <div className="le-preference-conflict"><Notice tone="info">{t.conflict}</Notice><h4>{t.current}</h4><p>{row.current_value ?? t.none}</p><Button variant="secondary" disabled={busy || refreshing} onClick={() => { void review() }}>{t.reviewCurrent}</Button></div>}
    {refreshError && <Notice tone="danger">{t.error}</Notice>}
    {error && !conflict && <Notice tone="danger">{error === 'preference_quota' ? t.quota : error === 'proposal_context_revoked' ? de.proposalErrors.proposal_context_revoked : error === 'proposal_not_pending' ? de.proposalErrors.proposal_not_pending : t.saveError}</Notice>}
    <div className="le-confirm-foot">
      <Button variant="primary" disabled={busy || refreshing || conflict} onClick={() => decide('replace')}>{row.previous_value !== null && !identical ? t.replace : de.preferences.save}</Button>
      {row.previous_value !== null && <Button variant="secondary" disabled={busy || refreshing || conflict} onClick={() => decide('keep')}>{t.keep}</Button>}
      <Button variant="ghost" disabled={busy || refreshing} onClick={cancel}>{de.controls.cancel}</Button>
    </div>
  </section>
}

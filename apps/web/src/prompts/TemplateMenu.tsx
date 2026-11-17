// i18n-exempt: route paths, query keys and CSS classes.
import { useQueries, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from '@tanstack/react-router'
import { useRef, useState } from 'react'
import { chatConversationUpdate } from '../api/generated/sdk.gen'
import type { ConversationOut } from '../api/generated/types.gen'
import { conversationsQuery, promptQuery, promptsQuery } from '../api/queries'
import { errorCode, unwrap } from '../api/unwrap'
import { useChatSession, useConversationScope, useRestartConversation } from '../chat/session'
import { Chip, Icon, Menu, Notice } from '../ds'
import { de } from '../i18n/de'
import './prompts.css'

export function TemplateMenu({ conversationId, revision = null, onChange }: { conversationId?: string; revision?: string | null; onChange?: (id: string | null) => void }) {
  const { saved } = useConversationScope(conversationId)
  const { state } = useChatSession()
  const restart = useRestartConversation(conversationId)
  const list = useQuery(promptsQuery()), client = useQueryClient(), navigate = useNavigate()
  const details = useQueries({ queries: (list.data ?? []).map(item => promptQuery(item.id)) })
  const selected = conversationId ? saved?.prompt_revision_id ?? null : revision
  const owner = details.find(item => item.data?.revisions.some(value => value.id === selected))?.data
  const resolved = list.isSuccess && details.every(item => item.isSuccess)
  const current = list.data?.find(item => item.revision_id === selected) ?? owner
  const [pending, setPending] = useState(false), [error, setError] = useState<string>(), lock = useRef(false)
  const busy = pending || state.phase === 'working' || state.phase === 'streaming'
  const reload = async () => { await client.fetchQuery({ ...conversationsQuery(), staleTime: 0 }); setError(undefined) }
  const choose = async (id: string | null) => {
    if (busy || lock.current) return
    if (!conversationId) { onChange?.(id); return }
    if (!saved) return
    lock.current = true; setPending(true); setError(undefined)
    try {
      const updated = await unwrap(chatConversationUpdate({ path: { conversation_id: conversationId }, body: { expected_version: saved.version, prompt_revision_id: id }, throwOnError: true }))
      client.setQueryData<ConversationOut[]>(['conversations'], previous => previous?.map(item => item.id === updated.id ? updated : item))
      void client.invalidateQueries({ queryKey: ['conversations'] })
    } catch (cause) {
      const code = errorCode(cause instanceof Error ? cause.cause : cause)
      setError(code === 'version_conflict' ? de.prompts.selectionConflict : de.prompts.selectionError)
    } finally { lock.current = false; setPending(false) }
  }
  return <div className="le-template-control"><Menu placement="down-end" trigger={props => <Chip {...props} quiet disabled={busy || (!!conversationId && !saved)}>{de.prompts.chip(current?.name ?? (selected ? resolved ? de.prompts.removed : de.prompts.loading : de.prompts.standard))}<Icon name="chevron-down" size="sm" /></Chip>} items={[
    { label: de.prompts.standard, checked: selected === null, onSelect: () => { void choose(null) } },
    ...(list.data?.length === 0 ? [{ label: de.prompts.empty, disabled: true, onSelect: () => {} }] : []),
    ...(list.data ?? []).map(item => ({ label: item.name, hint: item.text, checked: item.revision_id === selected, onSelect: () => { void choose(item.revision_id) } })),
    ...details.flatMap(result => result.data ? result.data.revisions.filter(item => item.id !== result.data!.revision_id).map(item => ({ label: `${result.data!.name} · ${de.prompts.version(item.number)}`, hint: item.content, checked: item.id === selected, onSelect: () => { void choose(item.id) } })) : []),
    { label: de.prompts.manage, onSelect: () => { void navigate({ to: '/settings/prompts' }) } },
  ]} /><small className="le-hint">{de.prompts.next}</small>
    {list.isPending && <span role="status">{de.prompts.loading}</span>}
    {(list.isError || details.some(item => item.isError)) && <Notice tone="danger" action={{ label: de.chat.retry, onClick: () => { void client.invalidateQueries({ queryKey: ['prompts'] }) } }}>{de.prompts.error}</Notice>}
    {owner && owner.revision_id !== selected && <Notice tone="info" action={busy ? undefined : { label: de.prompts.adopt, onClick: () => { void choose(owner.revision_id) } }}>{de.prompts.newer}</Notice>}
    {error && <Notice tone="danger" action={{ label: de.prompts.loadCurrent, onClick: () => { void reload().catch(() => setError(de.prompts.selectionError)) } }}>{error}</Notice>}
    {selected && !current && resolved && <Notice tone="info" action={{ label: conversationId ? de.prompts.restart : de.prompts.useStandard, onClick: () => { if (conversationId) restart(); else onChange?.(null) } }}>{de.prompts.removed}</Notice>}
  </div>
}

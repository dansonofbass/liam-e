import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useContext, useState } from 'react'
import { createPortal } from 'react-dom'
import { chatConversationUpdate } from '../api/generated/sdk.gen'
import { conversationsQuery, modelsQuery } from '../api/queries'
import { errorCode, unwrap } from '../api/unwrap'
import { Chip, Icon, Menu, Notice, Tooltip } from '../ds'
import { useI18n } from '../i18n/I18n'
import { MobileModelSlot } from '../shell/MobileHeader'
import { ModelDetails } from './ModelDetails'
import { modelMenuItems } from './model-menu-items'
import { useChatSession, useConversationScope } from './session'

// With a conversation the choice is saved on it. Without one (the start page) the parent owns the choice: it is reported via onChange and shown from `model`; the first message carries it.
export function ModelMenu({ conversationId, model, onChange }: { conversationId?: string; model?: string; onChange?: (model: string) => void }) {
  const { texts } = useI18n()
  const catalogue = useQuery(modelsQuery())
  const models = catalogue.data ?? []
  const mobileSlot = useContext(MobileModelSlot)
  const { saved } = useConversationScope(conversationId)
  const { state } = useChatSession()
  const client = useQueryClient()
  const [saving, setSaving] = useState(false)
  const [detailsOpen, setDetailsOpen] = useState(false)
  const [error, setError] = useState<string>()
  const answering = state.phase === 'working' || state.phase === 'streaming'
  const busy = saving || (answering && (!conversationId || state.conversationId === conversationId))
  // An empty choice uses the configured default. A conversation still loading has no known choice.
  const selected = conversationId ? saved?.model : model ?? ''
  const id = selected === '' ? models.find(item => item.is_default)?.id : selected
  const label = models.find(item => item.id === id)?.label ?? id
  const select = async (next: string) => {
    if (busy) return
    if (!conversationId) { onChange?.(next); return }
    if (!saved) return
    setSaving(true); setError(undefined)
    try {
      const updated = await unwrap(chatConversationUpdate({ path: { conversation_id: conversationId }, body: { model: next, expected_version: saved.version }, throwOnError: true }))
      client.setQueryData(conversationsQuery().queryKey, rows => rows?.map(row =>
        row.id === updated.id && row.version <= updated.version ? updated : row))
      void client.invalidateQueries({ queryKey: ['history', conversationId] })
      void client.invalidateQueries({ queryKey: ['conversations'] })
    } catch (failure) {
      const code = errorCode(failure instanceof Error ? failure.cause : failure)
      if (code === 'version_conflict') {
        try {
          const current = (await client.fetchQuery({ ...conversationsQuery(), staleTime: 0 })).find(item => item.id === conversationId)
          if (!current) { setError(texts.errors.conversation_not_found); return }
          setError(texts.chat.modelConflict)
          void client.invalidateQueries({ queryKey: ['history', conversationId] })
        } catch { setError(texts.chat.modelConflictReloadError) }
      } else if (code === 'model_unknown' || code === 'model_catalog_unavailable') {
        setError(texts.errors[code])
        void catalogue.refetch()
      } else if (code === 'conversation_not_found') setError(texts.errors.conversation_not_found)
      else setError(texts.chat.modelError)
    } finally { setSaving(false) }
  }
  const unverified = catalogue.isError || catalogue.isPending || (catalogue.fetchStatus !== 'idle' && catalogue.isStale) || models.some(item => item.availability === 'unverified')
  const refresh = () => { void catalogue.refetch() }
  const { items, details } = modelMenuItems(models, id, unverified, texts.chat, select, refresh, () => setDetailsOpen(true))
  const control = <span className="le-model-control"><Menu placement="down-end" label={texts.chat.modelTip} items={items}
    onOpen={() => { if (catalogue.isStale || unverified) refresh() }}
    trigger={props => <Tooltip content={texts.chat.modelTip} pos="bottom"><Chip {...props} quiet aria-description={texts.chat.modelTip} disabled={busy || Boolean(conversationId && !saved)}><span className="le-model-label">{label ?? texts.chat.modelChoice}</span><Icon name="chevron-down" size="sm" /></Chip></Tooltip>} /></span>
  return <>{error && <Notice tone="danger">{error}</Notice>}{mobileSlot ? createPortal(control, mobileSlot) : control}
    {detailsOpen && <ModelDetails models={details} unavailable={unverified} onRefresh={refresh} onClose={() => setDetailsOpen(false)} />}
  </>
}

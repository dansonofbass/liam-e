import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { chatConversationUpdate } from '../api/generated/sdk.gen'
import { conversationsQuery, modelsQuery } from '../api/queries'
import { errorCode, unwrap } from '../api/unwrap'
import { Chip, Icon, Menu, Notice, Tooltip } from '../ds'
import { useI18n } from '../i18n/I18n'

// With a conversation the choice is saved on it. Without one (the start page) the parent owns the choice: it is reported via onChange and shown from `model`; the first message carries it.
export function ModelMenu({ conversationId, model, onChange }: { conversationId?: string; model?: string; onChange?: (model: string) => void }) {
  const { texts } = useI18n()
  const { data: models = [] } = useQuery(modelsQuery())
  const client = useQueryClient()
  const [chosen, setChosen] = useState<string>()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string>()
  const id = chosen ?? model ?? models.find(item => item.is_default)?.id
  const label = models.find(item => item.id === id)?.label ?? id
  const select = async (next: string) => {
    if (busy) return
    if (!conversationId) { onChange?.(next); return }
    setBusy(true); setError(undefined)
    try {
      const current = (await client.fetchQuery({ ...conversationsQuery(), staleTime: 0 })).find(item => item.id === conversationId)
      if (!current) { setError(texts.errors.conversation_not_found); return }
      await unwrap(chatConversationUpdate({ path: { conversation_id: conversationId }, body: { model: next, expected_version: current.version }, throwOnError: true }))
      setChosen(next)
      onChange?.(next)
      void client.invalidateQueries({ queryKey: ['history', conversationId] })
      void client.invalidateQueries({ queryKey: ['conversations'] })
    } catch (failure) {
      const code = errorCode(failure instanceof Error ? failure.cause : failure)
      if (code === 'version_conflict') {
        try {
          const current = (await client.fetchQuery({ ...conversationsQuery(), staleTime: 0 })).find(item => item.id === conversationId)
          if (!current) { setError(texts.errors.conversation_not_found); return }
          setChosen(current.model || models.find(item => item.is_default)?.id)
          onChange?.(current.model)
          setError(texts.chat.modelConflict)
          void client.invalidateQueries({ queryKey: ['history', conversationId] })
        } catch { setError(texts.chat.modelConflictReloadError) }
      } else setError(code === 'model_unknown' ? texts.chat.modelUnknown : texts.chat.modelError)
    } finally { setBusy(false) }
  }
  const descriptions: Partial<Record<string, string>> = texts.chat.modelDescriptions
  return <>{label && <Menu placement="down-end" trigger={props => <Tooltip content={texts.chat.modelTip} pos="bottom"><Chip {...props} quiet disabled={busy}>{label}<Icon name="chevron-down" size="sm" /></Chip></Tooltip>} items={models.map(item => { const description = descriptions[item.id] ?? item.description; return { label: description ? `${item.label} · ${description}` : item.label, onSelect: () => { void select(item.id) } } })} />}{error && <Notice tone="danger">{error}</Notice>}</>
}

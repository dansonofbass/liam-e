import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { chatConversationUpdate } from '../api/generated/sdk.gen'
import { modelsQuery } from '../api/queries'
import { errorCode, unwrap } from '../api/unwrap'
import { Chip, Icon, Menu, Notice, Tooltip } from '../ds'
import { de } from '../i18n/de'

// With a conversation the choice is saved on it. Without one (the start page) the parent owns the choice: it is reported via onChange and shown from `model`; the first message carries it.
export function ModelMenu({ conversationId, model, onChange }: { conversationId?: string; model?: string; onChange?: (model: string) => void }) {
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
      await unwrap(chatConversationUpdate({ path: { conversation_id: conversationId }, body: { model: next }, throwOnError: true }))
      setChosen(next)
      onChange?.(next)
      void client.invalidateQueries({ queryKey: ['history', conversationId] })
    } catch (failure) { setError(errorCode(failure instanceof Error ? failure.cause : failure) === 'model_unknown' ? de.chat.modelUnknown : de.chat.modelError) } finally { setBusy(false) }
  }
  return <>{label && <Menu placement="down-end" trigger={props => <Tooltip content={de.chat.modelTip} pos="bottom"><Chip {...props} quiet disabled={busy}>{label}<Icon name="chevron-down" size="sm" /></Chip></Tooltip>} items={models.map(item => ({ label: item.description ? `${item.label} · ${item.description}` : item.label, onSelect: () => { void select(item.id) } }))} />}{error && <Notice tone="danger">{error}</Notice>}</>
}

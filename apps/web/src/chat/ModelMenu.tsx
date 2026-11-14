import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { chatConversationUpdate } from '../api/generated/sdk.gen'
import { modelsQuery } from '../api/queries'
import { unwrap } from '../api/unwrap'
import { Chip, Icon, Menu, Notice } from '../ds'
import { de } from '../i18n/de'

export function ModelMenu({ conversationId, model, onChange }: { conversationId?: string; model?: string; onChange?: (model: string) => void }) {
  const { data: models = [] } = useQuery(modelsQuery())
  const client = useQueryClient()
  const [chosen, setChosen] = useState<string>()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(false)
  const id = chosen ?? model ?? models.find(item => item.is_default)?.id
  const label = models.find(item => item.id === id)?.label ?? id
  if (!conversationId) return label ? <span className="le-hint">{label}</span> : null
  const select = async (next: string) => {
    if (busy) return
    setBusy(true); setError(false)
    try {
      await unwrap(chatConversationUpdate({ path: { conversation_id: conversationId }, body: { model: next }, throwOnError: true }))
      setChosen(next)
      onChange?.(next)
      void client.invalidateQueries({ queryKey: ['history', conversationId] })
    } catch { setError(true) } finally { setBusy(false) }
  }
  return <>{label && <Menu trigger={props => <Chip {...props} quiet disabled={busy}>{label}<Icon name="chevron-down" size="sm" /></Chip>} items={models.map(item => ({ label: item.description ? `${item.label} · ${item.description}` : item.label, onSelect: () => { void select(item.id) } }))} />}{error && <Notice tone="danger">{de.chat.modelError}</Notice>}</>
}

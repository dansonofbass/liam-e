// i18n-exempt: API query keys and CSS classes.
import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import type { ContextOut } from '../api/generated/types.gen'
import { preferenceContextGet } from '../api/generated/sdk.gen'
import { unwrap } from '../api/unwrap'
import { Button, Notice } from '../ds'
import { useI18n } from '../i18n/I18n'
import { PreferenceDialog } from '../settings/Preferences'

export function PreferenceContext({ context }: { context: ContextOut }) {
  const { texts } = useI18n()
  const [open, setOpen] = useState(false)
  const query = useQuery({ queryKey: ['preference-context', context.id], queryFn: () => unwrap(preferenceContextGet({ path: { context_id: context.id }, throwOnError: true })), enabled: open, gcTime: 0 })
  const ids = JSON.parse(context.preference_revision_ids_json ?? '[]') as string[]
  // Only an answer that used preferences names them: with usage off or nothing matching there is nothing to open,
  // and a hint under every answer would be noise.
  if (!context.preferences_enabled || ids.length === 0) return null
  return <><Button variant="ghost" onClick={() => setOpen(true)}>{texts.preferences.used(ids.length)}</Button>
    {open && <PreferenceDialog title={texts.preferences.historical} close={() => setOpen(false)}>
      {query.isPending && <p role="status">{texts.preferences.loading}</p>}
      {query.isError && <Notice tone="danger" action={{ label: texts.chat.retry, onClick: () => { void query.refetch() } }}>{texts.preferences.error}</Notice>}
      {query.data?.revisions.map(rev => <div key={rev.revision_id}>{rev.removed ? <p>{texts.preferences.removed}</p> : <><strong>{rev.key && texts.preferences.keys[rev.key]}</strong><p>{rev.value}</p><small>{rev.source === 'confirmed_candidate' ? texts.preferences.confirmedSource : texts.preferences.source}</small></>}</div>)}
      <Button variant="secondary" onClick={() => setOpen(false)}>{texts.preferences.close}</Button>
    </PreferenceDialog>}
  </>
}

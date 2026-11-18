// i18n-exempt: API query keys and CSS classes.
import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import type { ContextOut } from '../api/generated/types.gen'
import { preferenceContextGet } from '../api/generated/sdk.gen'
import { unwrap } from '../api/unwrap'
import { Button, Notice } from '../ds'
import { de } from '../i18n/de'
import { PreferenceDialog } from '../settings/Preferences'

export function PreferenceContext({ context }: { context: ContextOut }) {
  const [open, setOpen] = useState(false)
  const query = useQuery({ queryKey: ['preference-context', context.id], queryFn: () => unwrap(preferenceContextGet({ path: { context_id: context.id }, throwOnError: true })), enabled: open, gcTime: 0 })
  const ids = JSON.parse(context.preference_revision_ids_json ?? '[]') as string[]
  // Only an answer that used preferences names them: with usage off or nothing matching there is nothing to open,
  // and a hint under every answer would be noise.
  if (!context.preferences_enabled || ids.length === 0) return null
  return <><Button variant="ghost" onClick={() => setOpen(true)}>{de.preferences.used(ids.length)}</Button>
    {open && <PreferenceDialog title={de.preferences.historical} close={() => setOpen(false)}>
      {query.isPending && <p role="status">{de.preferences.loading}</p>}
      {query.isError && <Notice tone="danger" action={{ label: de.chat.retry, onClick: () => { void query.refetch() } }}>{de.preferences.error}</Notice>}
      {query.data?.revisions.map(rev => <div key={rev.revision_id}>{rev.removed ? <p>{de.preferences.removed}</p> : <><strong>{rev.key && de.preferences.keys[rev.key]}</strong><p>{rev.value}</p><small>{de.preferences.source}</small></>}</div>)}
      <Button variant="secondary" onClick={() => setOpen(false)}>{de.preferences.close}</Button>
    </PreferenceDialog>}
  </>
}

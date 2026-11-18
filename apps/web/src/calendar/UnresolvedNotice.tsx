// i18n-exempt: query keys.
import { useQueryClient } from '@tanstack/react-query'
import { useRef, useState } from 'react'
import { calendarWriteCheck } from '../api/generated/sdk.gen'
import { Notice } from '../ds'
import { de } from '../i18n/de'
import { trackWrite, writeOutcome, type UnresolvedWrite } from './write-state'

/** Offers the check for writes whose outcome is still open; nothing is sent again. */
export function UnresolvedNotice({ writes }: { writes: UnresolvedWrite[] }) {
  const client = useQueryClient(), [busy, setBusy] = useState(false), pending = useRef(false)
  if (!writes.length) return null
  const check = async () => {
    if (pending.current) return
    pending.current = true; setBusy(true)
    try {
      for (const write of writes) {
        try { trackWrite(write, writeOutcome(await calendarWriteCheck({ path: { write_id: write.writeId } })).status) } catch { /* stays open */ }
      }
    } finally {
      pending.current = false; setBusy(false)
      void client.invalidateQueries({ queryKey: ['calendar'] })
    }
  }
  return <Notice tone="info" action={busy ? undefined : { label: de.calendar.check, onClick: () => { void check() } }}>{busy ? de.calendar.checking : de.calendar.unresolved}</Notice>
}

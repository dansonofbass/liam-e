// i18n-exempt: query keys.
import { useQueryClient } from '@tanstack/react-query'
import { useRef, useState } from 'react'
import { calendarWriteCheck } from '../api/generated/sdk.gen'
import { Notice } from '../ds'
import { useI18n } from '../i18n/I18n'
import { trackWrite, writeOutcome, type UnresolvedWrite } from './write-state'

/** Offers the check for writes whose outcome is still open; nothing is sent again. */
export function UnresolvedNotice({ writes }: { writes: UnresolvedWrite[] }) {
  const { texts } = useI18n()
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
  return <Notice tone="info" action={busy ? undefined : { label: texts.calendar.check, onClick: () => { void check() } }}>{busy ? texts.calendar.checking : texts.calendar.unresolved}</Notice>
}

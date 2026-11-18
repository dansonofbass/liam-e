// i18n-exempt: CSS classes and protocol statuses.
import { useId, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import type { LiveEvent, WriteOutcome } from '../api/generated/types.gen'
import { calendarEventDelete, calendarWriteCheck } from '../api/generated/sdk.gen'
import { Button, Notice } from '../ds'
import { useFocusTrap } from '../ds/useFocusTrap'
import { de } from '../i18n/de'
import { EventReading } from './EventReading'
import { writeError, writeOutcome } from './write-state'

export function DeleteEventDialog({ event, onClose, onDone }: { event: LiveEvent; onClose(): void; onDone(): void }) {
  const [writeId, setWriteId] = useState(() => crypto.randomUUID())
  const [outcome, setOutcome] = useState<WriteOutcome>()
  const [busy, setBusy] = useState(false), pending = useRef(false)
  const close = () => { if (!pending.current) onClose() }
  const ref = useFocusTrap(true, close), titleId = useId()
  const run = async (check = false) => {
    if (pending.current) return
    pending.current = true; setBusy(true)
    try {
      const result = check ? await calendarWriteCheck({ path: { write_id: writeId } }) : await calendarEventDelete({ path: { occurrence_id: event.occurrence_id! }, body: { write_id: writeId, expected_revision: event.revision! } })
      const next = writeOutcome(result); setOutcome(next)
      if (next.status === 'done') onDone()
      else ref.current?.focus()
    } catch { setOutcome({ write_id: writeId, status: 'unknown', error_code: 'calendar_write_unknown' }) }
    finally { pending.current = false; setBusy(false) }
  }
  const checking = outcome?.status === 'unknown' || outcome?.status === 'running'
  return createPortal(<div className="le-scrim" onMouseDown={e => { if (e.target === e.currentTarget) close() }}><div ref={ref} className="le-dialog" role="dialog" aria-modal="true" aria-labelledby={titleId} tabIndex={-1}>
    <h2 id={titleId} className="heading">{de.calendar.deleteTitle}</h2><EventReading event={outcome?.current ?? event} />
    <p>{de.calendar.deleteWarning}</p><p>{de.calendar.writeRisk}</p>
    {outcome?.error_code && <Notice tone="danger">{writeError(outcome.error_code)}</Notice>}
    {checking && <p role="status">{de.calendar.checking}</p>}
    <div className="le-dialog-actions"><Button variant="secondary" disabled={busy} onClick={close}>{de.controls.cancel}</Button>
      {!outcome && <Button variant="danger" disabled={busy} onClick={() => { void run() }}>{de.calendar.deleteEvent}</Button>}
      {checking && <Button variant="secondary" disabled={busy} onClick={() => { void run(true) }}>{de.calendar.check}</Button>}
      {((outcome?.status === 'not_applied' && !outcome.current) || outcome?.status === 'failed') && <Button variant="secondary" disabled={busy} onClick={() => { setWriteId(crypto.randomUUID()); setOutcome(undefined) }}>{de.calendar.retryWrite}</Button>}
    </div>
  </div></div>, document.body)
}

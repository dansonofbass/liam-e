// i18n-exempt: CSS classes, browser API options, request keys and dialog roles.
import { useEffect, useId, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { useQueryClient } from '@tanstack/react-query'
import { calendarFeedSubscribe, calendarFeedValidate, calendarFeedValidationDiscard } from '../api/generated/sdk.gen'
import type { CalendarFeedValidateResponse, SourceOut } from '../api/generated/types.gen'
import { Button, Notice, TextField } from '../ds'
import { useFocusTrap } from '../ds/useFocusTrap'
import { de } from '../i18n/de'

/** Secret addresses live only in this dialog's state, never in queries or browser storage. */
export function FeedSetup({ source, close, saved }: { source?: SourceOut; close: () => void; saved: () => void }) {
  const [name, setName] = useState(source?.name ?? ''), [url, setUrl] = useState('')
  const [zone, setZone] = useState(source?.timezone ?? Intl.DateTimeFormat().resolvedOptions().timeZone)
  const [preview, setPreview] = useState<CalendarFeedValidateResponse>(), [error, setError] = useState(''), [pending, setPending] = useState(false)
  const proof = useRef<string | undefined>(undefined), busy = useRef(false), mounted = useRef(true)
  const abort = useRef<AbortController | undefined>(undefined), title = useId()
  const dismiss = () => { if (!busy.current) close() }
  const trap = useFocusTrap(true, dismiss)
  const discard = () => {
    const token = proof.current
    proof.current = undefined
    if (token) void calendarFeedValidationDiscard({ body: { validation_id: token } }).catch(() => {})
  }
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; abort.current?.abort(); discard() } }, [])
  const changed = () => { discard(); setPreview(undefined); setError('') }
  const body = () => ({ name, url, timezone: zone, source_id: source?.id, expected_revision: source?.revision })
  const check = async () => {
    if (busy.current) return
    busy.current = true; setPending(true); changed()
    // Display the normalized scheme before sending; the server repeats full validation.
    const normalized = url.replace(/^webcal:/, 'https:')
    setUrl(normalized)
    abort.current = new AbortController()
    try {
      const result = await calendarFeedValidate({ body: { ...body(), url: normalized }, signal: abort.current.signal })
      if (result.error || !result.data) throw new Error()
      if (!mounted.current) {
        void calendarFeedValidationDiscard({ body: { validation_id: result.data.validation_id } })
        return
      }
      proof.current = result.data.validation_id
      setPreview(result.data)
    } catch { if (mounted.current) setError(de.calendar.feedError) }
    finally { busy.current = false; if (mounted.current) setPending(false) }
  }
  const subscribe = async () => {
    if (busy.current || !preview) return
    busy.current = true; setPending(true); setError('')
    try {
      const result = await calendarFeedSubscribe({ body: { ...body(), validation_id: preview.validation_id } })
      if (result.error || !result.data) throw new Error()
      proof.current = undefined
      saved()
    } catch { changed(); setError(de.calendar.feedSaveError) }
    finally { busy.current = false; if (mounted.current) setPending(false) }
  }
  const day = (value: string) => new Intl.DateTimeFormat('de-DE', { dateStyle: 'medium', timeZone: 'UTC' }).format(new Date(value))
  return createPortal(<div className="le-scrim"><div className="le-dialog le-feed-form" role="dialog" aria-modal="true" aria-labelledby={title} ref={trap} tabIndex={-1}>
    <h2 className="heading" id={title}>{source ? de.calendar.replaceAddress : de.calendar.subscribe}</h2>
    <p>{de.calendar.feedReadOnly}</p>
    <TextField label={de.calendar.feedName} hint={de.calendar.feedNameHint} value={name} maxLength={80} disabled={pending} onChange={event => { changed(); setName(event.target.value) }} />
    <TextField label={de.calendar.feedAddress} hint={de.calendar.feedNormalize} value={url} maxLength={4096} autoComplete="off" spellCheck={false} disabled={pending} onChange={event => { changed(); setUrl(event.target.value) }} />
    <TextField label={de.calendar.feedZone} hint={de.calendar.feedZoneHint} value={zone} maxLength={100} disabled={pending} onChange={event => { changed(); setZone(event.target.value) }} />
    {pending && <p role="status">{de.calendar.feedChecking}</p>}
    {error && <Notice tone="danger">{error}</Notice>}
    {preview && <section aria-label={de.calendar.feedPreview} aria-live="polite">
      <h3 className="heading">{preview.name}</h3><p>{day(preview.coverage_start)} – {day(preview.coverage_end)}</p>
      <p>{de.calendar.feedCount(preview.occurrence_count)}</p><p>{de.calendar.feedExpires}</p>
    </section>}
    <div className="le-dialog-actions">
      <Button variant="secondary" disabled={pending} onClick={dismiss}>{de.calendar.cancel}</Button>
      {preview ? <Button variant="primary" disabled={pending} onClick={() => { void subscribe() }}>{source ? de.calendar.replaceAddress : de.calendar.subscribeConfirm}</Button>
        : <Button variant="primary" disabled={pending || !name.trim() || !url || !zone} onClick={() => { void check() }}>{de.calendar.feedCheck}</Button>}
    </div>
  </div></div>, document.body)
}

/** The one entry to a new subscription, on the accounts page and in the empty agenda. */
export function CalendarSetup({ primary = false }: { primary?: boolean }) {
  const [open, setOpen] = useState(false), client = useQueryClient()
  return <><Button variant={primary ? 'primary' : 'secondary'} onClick={() => setOpen(true)}>{de.calendar.subscribe}</Button>
    {open && <FeedSetup close={() => setOpen(false)} saved={() => { setOpen(false); void client.invalidateQueries({ queryKey: ['calendar'] }) }} />}</>
}

// i18n-exempt: CSS classes, browser API options, request keys and dialog roles.
import { useEffect, useId, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { calendarGoogleCalendarsList, calendarGoogleConnect } from '../api/generated/sdk.gen'
import type { GoogleCalendarOut } from '../api/generated/types.gen'
import { Button, Notice, TextField } from '../ds'
import { useFocusTrap } from '../ds/useFocusTrap'
import { de } from '../i18n/de'

/** Discovery is dialog-local: a new opening rechecks the current connector identity. */
export function GoogleSetup({ close, saved }: { close: () => void; saved: () => void }) {
  const [calendars, setCalendars] = useState<GoogleCalendarOut[]>([])
  const [selected, setSelected] = useState<string[]>([])
  const [loading, setLoading] = useState(true), [pending, setPending] = useState(false)
  const [error, setError] = useState(''), [saveError, setSaveError] = useState('')
  const busy = useRef(false), mounted = useRef(true), abort = useRef<AbortController | undefined>(undefined)
  const title = useId(), dismiss = () => { if (!busy.current) close() }
  const trap = useFocusTrap(true, dismiss)
  const load = async () => {
    abort.current?.abort()
    const request = new AbortController()
    abort.current = request
    setLoading(true); setError(''); setSelected([]); setCalendars([]); setSaveError('')
    try {
      const result = await calendarGoogleCalendarsList({ signal: request.signal })
      if (!mounted.current || request.signal.aborted) return
      if (result.response?.status === 409) { setError(de.calendar.googleNotConnected); return }
      if (result.error || !result.data) throw new Error()
      setCalendars(result.data.calendars)
    } catch { if (mounted.current && !request.signal.aborted) setError(de.calendar.googleError) }
    finally { if (mounted.current && !request.signal.aborted) setLoading(false) }
  }
  useEffect(() => {
    mounted.current = true
    void load()
    return () => { mounted.current = false; abort.current?.abort() }
  }, [])
  const connect = async () => {
    if (busy.current || !selected.length) return
    busy.current = true; setPending(true); setSaveError('')
    try {
      const result = await calendarGoogleConnect({ body: { calendar_ids: selected } })
      if (result.response?.status === 409) { if (mounted.current) setSaveError(de.calendar.googleNotConnected); return }
      if (result.error || !result.data) throw new Error()
      saved()
    } catch { if (mounted.current) setSaveError(de.calendar.googleSaveError) }
    finally { busy.current = false; if (mounted.current) setPending(false) }
  }
  return createPortal(<div className="le-scrim" onClick={event => { if (event.target === event.currentTarget) dismiss() }}>
    <div className="le-dialog le-feed-form" role="dialog" aria-modal="true" aria-labelledby={title} ref={trap} tabIndex={-1}>
      <h2 className="heading" id={title}>{de.calendar.googleConnect}</h2>
      <p>{de.calendar.googleChoose}</p>
      {loading && <><p role="status">{de.calendar.googleLoading}</p>{[0, 1, 2].map(row => <div key={row} className="le-calendar-placeholder" aria-hidden="true" />)}</>}
      {error && <Notice tone="danger" action={{ label: de.calendar.retry, onClick: () => { void load() } }}>{error}</Notice>}
      {!loading && !error && <>
        {calendars.length === 0 && <Notice tone="info" action={{ label: de.calendar.retry, onClick: () => { void load() } }}>{de.calendar.googleEmpty}</Notice>}
        {selected.length >= 20 && <Notice tone="info">{de.calendar.googleLimit}</Notice>}
        {calendars.map(calendar => <div key={calendar.id} className="le-google-choice">
          <TextField type="checkbox" label={calendar.name} hint={calendar.source_id ? de.calendar.googleConnected : undefined}
            checked={Boolean(calendar.source_id) || selected.includes(calendar.id)} disabled={pending || Boolean(calendar.source_id) || (selected.length >= 20 && !selected.includes(calendar.id))}
            onChange={event => { setSelected(current => event.target.checked ? [...current, calendar.id] : current.filter(id => id !== calendar.id)) }} />
        </div>)}
      </>}
      {pending && <p role="status">{de.calendar.googleConnecting}</p>}
      {saveError && <Notice tone="danger">{saveError}</Notice>}
      <div className="le-dialog-actions">
        <Button variant="secondary" disabled={pending} onClick={dismiss}>{de.calendar.cancel}</Button>
        <Button variant="primary" disabled={loading || Boolean(error) || pending || selected.length === 0} onClick={() => { void connect() }}>{de.calendar.googleConnectCount(selected.length)}</Button>
      </div>
    </div>
  </div>, document.body)
}

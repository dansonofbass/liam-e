import { useId, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { mailAccountDelete } from '../api/generated/sdk.gen'
import type { AccountOut } from '../api/generated/types.gen'
import { errorCode } from '../api/unwrap'
import { Button, Notice } from '../ds'
import { useFocusTrap } from '../ds/useFocusTrap'
import { de } from '../i18n/de'

export function RemoveDialog({ account, onClose, onRemoved }: { account: AccountOut; onClose: () => void; onRemoved: () => void }) {
  const [pending, setPending] = useState(false), [error, setError] = useState<string>()
  const pendingRef = useRef(false)
  const close = () => { if (!pendingRef.current) onClose() }
  const ref = useFocusTrap(true, close)
  const titleId = useId()
  const remove = async () => {
    if (pendingRef.current) return
    pendingRef.current = true; setPending(true); setError(undefined)
    try {
      const result = await mailAccountDelete({ path: { account_id: account.id } })
      if (result.error || !result.response?.ok) throw result.error
      onRemoved()
    } catch (cause) {
      const code = errorCode(cause), text = code ? (de.errors as Record<string, unknown>)[code] : undefined
      setError(typeof text === 'string' ? text : de.accounts.actionError)
    } finally { pendingRef.current = false; setPending(false) }
  }
  // In the body, so the scrim also covers what stacks above the page (the sticky label in the sidebar).
  return createPortal(<div className="le-scrim" onMouseDown={event => { if (event.target === event.currentTarget) close() }}><div className="le-dialog" role="dialog" aria-modal="true" aria-labelledby={titleId} tabIndex={-1} ref={ref}>
    <h2 className="heading" id={titleId}>{de.accounts.removeTitle(account.display_name || account.email_address)}</h2>
    <p>{de.accounts.removeDescription}</p>
    {error && <Notice tone="danger">{error}</Notice>}
    <div className="le-dialog-actions"><Button variant="secondary" disabled={pending} onClick={close}>{de.controls.cancel}</Button><Button variant="danger" disabled={pending} onClick={() => { void remove() }}>{de.accounts.removeConfirm}</Button></div>
  </div></div>, document.body)
}

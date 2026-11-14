import { useEffect, useRef, useState } from 'react'
import { mailAccountConnectImap } from '../api/generated/sdk.gen'
import type { AccountOut, ImapPresetOut } from '../api/generated/types.gen'
import { errorCode } from '../api/unwrap'
import { Button, Notice, TextField, Tooltip } from '../ds'
import { de } from '../i18n/de'

type FieldErrors = { email?: string; imap?: string; smtp?: string; secret?: string }
export function ImapForm({ presets, initialAddress = '', focusSecret = false, onCancel, onConnected, onBusyChange }: { presets: ImapPresetOut[]; initialAddress?: string; focusSecret?: boolean; onCancel: () => void; onConnected: (account: AccountOut) => void; onBusyChange: (busy: boolean) => void }) {
  const [email, setEmail] = useState(initialAddress), [imap, setImap] = useState(''), [smtp, setSmtp] = useState(''), [secret, setSecret] = useState('')
  const [errors, setErrors] = useState<FieldErrors>({}), [notice, setNotice] = useState<string>(), [pending, setPending] = useState(false)
  const editedImap = useRef(false), editedSmtp = useRef(false), pendingRef = useRef(false), formRef = useRef<HTMLFormElement>(null)
  const domain = email.trim().split('@')[1]?.toLowerCase() ?? ''
  useEffect(() => {
    const preset = presets.find(item => item.domain.toLowerCase() === domain)
    if (preset) { if (!editedImap.current) setImap(preset.imap_host); if (!editedSmtp.current) setSmtp(preset.smtp_host) }
  }, [domain, presets])
  useEffect(() => { if (focusSecret) formRef.current?.querySelector<HTMLInputElement>('[name="password_secret"]')?.focus() }, [focusSecret])
  const submit = async () => {
    if (pendingRef.current) return
    const parts = email.trim().split('@'), problems: FieldErrors = {}
    if (parts.length !== 2 || !parts[0]?.trim() || !parts[1]?.trim()) problems.email = de.accounts.emailInvalid
    if (!imap.trim()) problems.imap = de.accounts.serverInvalid
    if (!smtp.trim()) problems.smtp = de.accounts.serverInvalid
    if (!secret.trim()) problems.secret = de.accounts.secretInvalid
    setErrors(problems); setNotice(undefined)
    if (Object.keys(problems).length) return
    pendingRef.current = true; setPending(true); onBusyChange(true)
    try {
      const preset = presets.find(item => item.domain.toLowerCase() === domain)
      const imapHost = imap.trim(), smtpHost = smtp.trim()
      const result = await mailAccountConnectImap({ body: { email_address: email.trim(), ...(imapHost.toLowerCase() !== preset?.imap_host.toLowerCase() && { imap_host: imapHost }), ...(smtpHost.toLowerCase() !== preset?.smtp_host.toLowerCase() && { smtp_host: smtpHost }), password_secret: secret.trim() } })
      if (result.error || !result.data) throw result.error
      onConnected(result.data)
    } catch (error) {
      const code = errorCode(error), text = code ? (de.errors as Record<string, unknown>)[code] : undefined
      const message = typeof text === 'string' ? text : de.accounts.actionError
      if (code === 'secret_not_allowed' || code === 'secret_not_found') setErrors({ secret: message })
      else setNotice(message)
    } finally { pendingRef.current = false; setPending(false); onBusyChange(false) }
  }
  return <form ref={formRef} className="le-imap-form" noValidate onSubmit={event => { event.preventDefault(); void submit() }}>
    <TextField label={de.accounts.email} type="email" autoComplete="off" value={email} onChange={event => setEmail(event.target.value)} error={errors.email} />
    <div className="le-imap-servers"><TextField label={de.accounts.imapServer} value={imap} onChange={event => { editedImap.current = true; setImap(event.target.value) }} error={errors.imap} /><TextField label={de.accounts.smtpServer} value={smtp} onChange={event => { editedSmtp.current = true; setSmtp(event.target.value) }} error={errors.smtp} /></div>
    <TextField label={de.accounts.secret} name="password_secret" hint={de.accounts.secretHint} placeholder={de.accounts.secretPlaceholder(domain.split('.')[0] ?? '')} value={secret} onChange={event => setSecret(event.target.value)} error={errors.secret} />
    {notice && <Notice tone="danger">{notice}</Notice>}
    <div className="le-connect-actions"><Tooltip content={de.accounts.imapTip}><Button variant="primary" type="submit" disabled={pending} aria-busy={pending}>{de.accounts.connect}</Button></Tooltip><Button variant="ghost" disabled={pending} onClick={onCancel}>{de.controls.cancel}</Button></div>
    <Notice tone="info">{de.accounts.secretNotice}</Notice>
  </form>
}

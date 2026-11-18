// i18n-exempt: API keys, route paths and CSS classes.
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { useId, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { preferenceCreate, preferenceUpdate, preferenceDelete, settingsUpdate } from '../api/generated/sdk.gen'
import type { PreferenceOut, PreferenceCreate } from '../api/generated/types.gen'
import { summaryQuery } from '../api/queries'
import { errorCode, unwrap } from '../api/unwrap'
import { Button, Chip, Menu, Notice, TextField } from '../ds'
import { useFocusTrap } from '../ds/useFocusTrap'
import { de } from '../i18n/de'
import { preferencesQuery, personalizationQuery } from './preferenceQueries'

const t = de.preferences
const codeOf = (cause: unknown) => errorCode(cause instanceof Error ? cause.cause : cause)
function useRefresh() {
  const client = useQueryClient()
  return () => { for (const key of ['preferences', 'personalization', 'preference-context', 'history']) void client.invalidateQueries({ queryKey: [key] }) }
}

export function Personalization({ saved = false }: { saved?: boolean }) {
  const query = useQuery(personalizationQuery()), refresh = useRefresh()
  const [confirm, setConfirm] = useState(false), [busy, setBusy] = useState(false), [error, setError] = useState(false)
  const lock = useRef(false)
  const config = query.data?.personalization
  const change = async (use: boolean) => {
    if (!config || lock.current) return
    lock.current = true; setBusy(true); setError(false)
    try {
      await unwrap(settingsUpdate({ body: { personalization: { expected_version: config.version, use_preferences: use } }, throwOnError: true }))
      setConfirm(false); refresh()
    } catch { setError(true) } finally { lock.current = false; setBusy(false) }
  }
  if (!config) return query.isPending ? <p role="status">{t.loading}</p> : <Notice tone="danger" action={{ label: de.chat.retry, onClick: () => { void query.refetch() } }}>{t.error}</Notice>
  return <div className="le-prompts">
    <Notice tone="info" action={{ label: config.use_preferences ? t.disable : t.enable, onClick: () => { if (busy) return; if (config.use_preferences) void change(false); else setConfirm(true) } }}>{saved ? config.use_preferences ? t.saved : t.savedOff : config.use_preferences ? t.on : t.off}</Notice>
    <Button variant="secondary" disabled>{t.suggestions}</Button><p className="le-hint">{t.suggestionsUnavailable}</p>
    {error && <Notice tone="danger" action={{ label: t.reload, onClick: () => { void query.refetch() } }}>{t.conflict}</Notice>}
    {confirm && <PreferenceDialog title={t.enable} close={() => { if (!busy) setConfirm(false) }}><p>{t.transfer}</p><div className="le-dialog-actions"><Button variant="secondary" disabled={busy} onClick={() => setConfirm(false)}>{de.controls.cancel}</Button><Button variant="primary" disabled={busy} onClick={() => { void change(true) }}>{t.enable}</Button></div></PreferenceDialog>}
  </div>
}

export function Preferences() {
  const query = useQuery(preferencesQuery())
  const { data: summary } = useQuery(summaryQuery())
  const scope = (id: string) => id === '*' ? t.global : summary?.accounts.find(a => a.id === id)?.display_name || summary?.accounts.find(a => a.id === id)?.email_address || t.chooseAccount
  return <section className="le-prompts"><div className="le-prompt-actions"><h2 className="heading">{t.title}</h2><Link className="le-btn le-btn--primary" to="/settings/preferences/new">{t.add}</Link></div>
    <Personalization />
    {query.isPending && <><p role="status">{t.loading}</p>{[0, 1, 2].map(i => <div className="le-prompt-placeholder" key={i} aria-hidden="true" />)}</>}
    {query.isError && <Notice tone="danger" action={{ label: de.chat.retry, onClick: () => { void query.refetch() } }}>{t.error}</Notice>}
    {query.data?.length === 0 && <p>{t.empty}</p>}
    {query.data?.map(row => <div className="le-prompt-row" key={row.id}><strong>{t.keys[row.key]}</strong><span className="le-prompt-preview">{row.value}</span><small>{scope(row.scope)} · {t.source} · {t.statuses[row.status]}</small><Link className="le-btn le-btn--secondary" to="/settings/preferences/$preferenceId" params={{ preferenceId: row.id }}>{t.edit}</Link></div>)}
  </section>
}

export function PreferenceEditor({ id }: { id?: string }) {
  const query = useQuery({ ...preferencesQuery(), enabled: !!id })
  const [generation, setGeneration] = useState(0)
  const row = query.data?.find(p => p.id === id)
  if (id && !row) return <>{query.isPending ? <p role="status">{t.loading}</p> : <Notice tone="danger" action={{ label: t.reload, onClick: () => { void query.refetch() } }}>{query.isError ? t.error : t.unavailable}</Notice>}<Link to="/settings/preferences">{t.back}</Link></>
  return <PreferenceForm key={`${id ?? 'new'}-${generation}`} initial={row} reload={async () => { const result = await query.refetch(); if (result.isError) throw result.error; setGeneration(n => n + 1) }} />
}

function PreferenceForm({ initial, reload }: { initial?: PreferenceOut; reload: () => Promise<void> }) {
  const { data: summary } = useQuery(summaryQuery()), refresh = useRefresh()
  const [base, setBase] = useState(initial), [key, setKey] = useState<PreferenceCreate['key']>(initial?.key ?? 'answer_length')
  const [scope, setScope] = useState(initial?.scope ?? '*'), [value, setValue] = useState(initial?.value ?? '')
  const [busy, setBusy] = useState(false), [error, setError] = useState<string>(), [conflict, setConflict] = useState(false)
  const [saved, setSaved] = useState(false), [deleting, setDeleting] = useState(false), [removed, setRemoved] = useState(false)
  const lock = useRef(false)
  const accounts = summary?.accounts ?? []
  const execute = async (action: 'save' | 'pause' | 'delete') => {
    if (lock.current) return
    lock.current = true; setBusy(true); setError(undefined); setSaved(false)
    try {
      if (action === 'delete' && base) {
        const result = await preferenceDelete({ path: { id: base.id }, query: { expected_version: base.version } })
        if (!result.response?.ok) throw result.error
        setRemoved(true); setDeleting(false)
      } else {
        const row = base ? await unwrap(preferenceUpdate({ path: { id: base.id }, body: action === 'pause' ? { expected_version: base.version, status: base.status === 'active' ? 'paused' : 'active' } : { expected_version: base.version, value, scope }, throwOnError: true }))
          : await unwrap(preferenceCreate({ body: { key, scope, value }, throwOnError: true }))
        setBase(row); setSaved(true)
      }
      refresh()
    } catch (cause) { const conflict = codeOf(cause) === 'preference_conflict'; setConflict(conflict); setError(conflict ? t.conflict : t.saveError); setDeleting(false) }
    finally { lock.current = false; setBusy(false) }
  }
  if (removed) return <section className="le-prompts"><p role="status">{t.removed}</p><Link to="/settings/preferences">{t.back}</Link><Link to="/">{t.restart}</Link></section>
  const selectedAccount = accounts.find(a => a.id === scope)
  return <form className="le-prompts" onSubmit={event => { event.preventDefault(); void execute('save') }}><h2 className="heading">{base ? t.edit : t.add}</h2>
    <Menu trigger={props => <Chip {...props} disabled={!!base || busy} aria-label={t.field}>{t.keys[key]}</Chip>} items={(['answer_length', 'salutation', 'signature'] as const).map(k => ({ label: t.keys[k], checked: k === key, onSelect: () => { setKey(k); if (k !== 'answer_length' && scope === '*') setScope('') } }))} />
    <Menu trigger={props => <Chip {...props} disabled={busy} aria-label={t.scope}>{scope === '*' ? t.global : selectedAccount?.display_name || selectedAccount?.email_address || t.chooseAccount}</Chip>} items={[...(key === 'answer_length' ? [{ label: t.global, checked: scope === '*', onSelect: () => setScope('*') }] : []), ...accounts.map(a => ({ label: a.display_name || a.email_address, checked: a.id === scope, onSelect: () => setScope(a.id) }))]} />
    <TextField multiline rows={5} label={t.value} value={value} onChange={e => setValue(e.target.value)} maxLength={500} required autoFocus hint={de.prompts.count(Array.from(value).length, 500)} />
    <p className="le-hint">{t.source}{base && <> · {t.statuses[base.status]}</>}</p><Notice tone="info">{t.safety}</Notice>
    {saved && <Personalization saved />}
    {error && <Notice tone="danger" action={conflict ? { label: t.reload, onClick: () => { void reload().catch(() => setError(t.error)) } } : undefined}>{error}</Notice>}
    <div className="le-prompt-actions"><Button type="submit" variant="primary" disabled={busy || conflict || !scope || !value.trim()}>{t.save}</Button><Link className="le-btn le-btn--secondary" to="/settings/preferences">{t.back}</Link>
      {base && <><Button variant="secondary" disabled={busy || conflict} onClick={() => { void execute('pause') }}>{base.status === 'active' ? t.pause : t.activate}</Button><Button variant="danger" disabled={busy || conflict} onClick={() => setDeleting(true)}>{t.remove}</Button></>}
    </div>
    {deleting && <PreferenceDialog title={t.removeTitle} close={() => { if (!busy) setDeleting(false) }}><p>{t.removeDescription}</p><Link to="/">{t.restart}</Link><div className="le-dialog-actions"><Button variant="secondary" disabled={busy} onClick={() => setDeleting(false)}>{de.controls.cancel}</Button><Button variant="danger" disabled={busy} onClick={() => { void execute('delete') }}>{t.remove}</Button></div></PreferenceDialog>}
  </form>
}

export function PreferenceDialog({ title, close, children }: { title: string; close: () => void; children: React.ReactNode }) {
  const ref = useFocusTrap(true, close), id = useId()
  return createPortal(<div className="le-scrim"><div className="le-dialog" role="dialog" aria-modal="true" aria-labelledby={id} ref={ref} tabIndex={-1}><h2 id={id} className="heading">{title}</h2>{children}</div></div>, document.body)
}

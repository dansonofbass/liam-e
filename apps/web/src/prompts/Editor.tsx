// i18n-exempt: route paths and CSS classes.
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useNavigate } from '@tanstack/react-router'
import { useId, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { promptCreate, promptDelete, promptUpdate } from '../api/generated/sdk.gen'
import type { PromptOut } from '../api/generated/types.gen'
import { promptQuery } from '../api/queries'
import { errorCode, unwrap } from '../api/unwrap'
import { Button, Notice, TextField } from '../ds'
import { useFocusTrap } from '../ds/useFocusTrap'
import { de } from '../i18n/de'

const codeOf = (cause: unknown) => errorCode(cause instanceof Error ? cause.cause : cause)
export function Editor({ id }: { id?: string }) {
  const query = useQuery({ ...promptQuery(id ?? ''), enabled: !!id })
  const [generation, setGeneration] = useState(0)
  if (id && !query.data) return <>{query.isPending ? <p role="status">{de.prompts.loading}</p> : <Notice tone="danger" action={{ label: de.chat.retry, onClick: () => { void query.refetch() } }}>{codeOf(query.error) === 'prompt_unavailable' ? de.prompts.unavailable : de.prompts.error}</Notice>}<Link to="/settings/prompts">{de.prompts.back}</Link></>
  return <EditorForm key={`${id ?? 'new'}-${generation}`} initial={query.data} reload={async () => { const result = await query.refetch(); if (result.isError) throw result.error; setGeneration(value => value + 1) }} />
}
function EditorForm({ initial, reload }: { initial?: PromptOut; reload: () => Promise<void> }) {
  const client = useQueryClient(), navigate = useNavigate()
  const [name, setName] = useState(initial?.name ?? ''), [text, setText] = useState(initial?.text ?? '')
  const [busy, setBusy] = useState(false), [error, setError] = useState<string>(), [conflict, setConflict] = useState(false), [deleting, setDeleting] = useState(false)
  const lock = useRef(false)
  const refresh = () => { void client.invalidateQueries({ queryKey: ['prompts'] }); void client.invalidateQueries({ queryKey: ['conversations'] }); void client.invalidateQueries({ queryKey: ['history'] }) }
  const fail = (cause: unknown) => { const code = codeOf(cause); setConflict(code === 'version_conflict'); setError(code === 'version_conflict' ? de.prompts.conflict : code === 'prompt_unavailable' ? de.prompts.unavailable : de.prompts.saveError) }
  const save = async () => {
    if (lock.current) return
    lock.current = true; setBusy(true); setError(undefined)
    try {
      if (initial) await unwrap(promptUpdate({ path: { id: initial.id }, body: { name, text, expected_version: initial.version }, throwOnError: true }))
      else await unwrap(promptCreate({ body: { name, text }, throwOnError: true }))
      refresh(); await navigate({ to: '/settings/prompts' })
    } catch (cause) { fail(cause) } finally { lock.current = false; setBusy(false) }
  }
  const remove = async () => {
    if (!initial || lock.current) return
    lock.current = true; setBusy(true)
    try {
      const result = await promptDelete({ path: { id: initial.id }, query: { expected_version: initial.version } })
      if (!result.response?.ok) throw result.error
      refresh(); await navigate({ to: '/settings/prompts' })
    } catch (cause) { setDeleting(false); fail(cause) } finally { lock.current = false; setBusy(false) }
  }
  return <form className="le-prompts" onSubmit={event => { event.preventDefault(); void save() }}><h2 className="heading">{initial ? de.prompts.edit : de.prompts.create}</h2>
    <TextField label={de.prompts.name} value={name} onChange={event => setName(event.target.value)} required maxLength={80} hint={de.prompts.count(Array.from(name).length, 80)} autoFocus />
    <TextField multiline rows={10} label={de.prompts.text} value={text} onChange={event => setText(event.target.value)} required maxLength={8000} hint={de.prompts.count(Array.from(text).length, 8000)} placeholder={de.prompts.example} />
    <Notice tone="info">{de.prompts.safety}</Notice>
    {error && <Notice tone="danger" action={conflict ? { label: de.prompts.loadCurrent, onClick: () => { void reload().catch(fail) } } : undefined}>{error}</Notice>}
    <div className="le-prompt-actions"><Button type="submit" variant="primary" disabled={busy || !name.trim() || !text.trim() || conflict}>{de.prompts.save}</Button><Link className="le-btn le-btn--secondary" to="/settings/prompts">{de.prompts.back}</Link>{initial && <Button type="button" variant="danger" disabled={busy || conflict} onClick={() => setDeleting(true)}>{de.prompts.remove}</Button>}</div>
    {deleting && <DeleteDialog busy={busy} close={() => setDeleting(false)} remove={() => { void remove() }} />}
  </form>
}
function DeleteDialog({ busy, close, remove }: { busy: boolean; close: () => void; remove: () => void }) {
  const ref = useFocusTrap(true, () => { if (!busy) close() }), id = useId()
  return createPortal(<div className="le-scrim"><div className="le-dialog" role="dialog" aria-modal="true" aria-labelledby={id} ref={ref} tabIndex={-1}><h2 id={id} className="heading">{de.prompts.removeTitle}</h2><p>{de.prompts.removeDescription}</p><div className="le-dialog-actions"><Button variant="secondary" disabled={busy} onClick={close}>{de.controls.cancel}</Button><Button variant="danger" disabled={busy} onClick={remove}>{de.prompts.remove}</Button></div></div></div>, document.body)
}

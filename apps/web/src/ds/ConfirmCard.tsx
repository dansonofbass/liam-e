import { useState } from 'react'
import type { ProposalItem, SendDraft } from '../api/generated/types.gen'
import { de } from '../i18n/de'
import { Button } from './Button'
import { TextField } from './TextField'
export function ConfirmCard({ title, reason, items, irreversibleNote, confirmLabel, draft, onConfirm, onCancel, busy, deselected: controlledDeselected, onDeselectedChange, body: controlledBody, onBodyChange }: { title: string; reason: string; items: ProposalItem[]; irreversibleNote?: string; confirmLabel: (n: number) => string; draft?: SendDraft; onConfirm: (selectedIds: string[], body?: string) => void; onCancel: () => void; busy?: boolean; deselected?: Set<string>; onDeselectedChange?: (value: Set<string>) => void; body?: string; onBodyChange?: (value: string) => void }) {
  const [localDeselected, setLocalDeselected] = useState<Set<string>>(() => new Set())
  const [localBody, setLocalBody] = useState(draft?.body ?? '')
  const deselected = controlledDeselected ?? localDeselected
  const body = controlledBody ?? localBody
  const setDeselected = (value: Set<string>) => { if (controlledDeselected === undefined) setLocalDeselected(value); onDeselectedChange?.(value) }
  const setBody = (value: string) => { if (controlledBody === undefined) setLocalBody(value); onBodyChange?.(value) }
  const selected = items.filter(item => !deselected.has(item.id)).map(item => item.id)
  return <section className="le-confirm le-rise"><div className="le-confirm-head"><h3 className="le-confirm-title">{title}</h3><span className="le-hint">{reason}</span></div><ul className="le-confirm-list">{items.map(item => <li key={item.id} className="le-confirm-item"><label><span><input className="le-check" type="checkbox" checked={!deselected.has(item.id)} onChange={event => { const next = new Set(deselected); if (event.target.checked) next.delete(item.id); else next.add(item.id); setDeselected(next) }} /> <strong>{item.title}</strong></span><span className="le-hint">{item.subtitle}</span></label></li>)}</ul>{draft && <div className="le-confirm-draft"><p>{de.controls.recipient}: {draft.to.join(', ')}</p><p>{de.controls.subject}: {draft.subject}</p><TextField label={de.controls.draftBody} multiline value={body} onChange={event => setBody(event.target.value)} /></div>}<div className="le-confirm-foot"><Button variant="primary" disabled={busy || selected.length === 0} onClick={() => onConfirm(selected, draft ? body : undefined)}>{confirmLabel(selected.length)}</Button><Button variant="ghost" disabled={busy} onClick={onCancel}>{de.controls.cancel}</Button>{irreversibleNote && <span className="le-hint">{irreversibleNote}</span>}</div></section>
}

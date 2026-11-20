import { useLayoutEffect, useRef, type ReactNode } from 'react'
import { useI18n } from '../i18n/I18n'
import { Icon } from './Icon'
import { Tooltip } from './Tooltip'
export function Composer({ value, onChange, onSubmit, onStop, busy, placeholder, autoFocus, controls, audioControls, locked = false }: { value: string; onChange: (value: string) => void; onSubmit: () => void; onStop: () => void; busy: boolean; placeholder: string; autoFocus?: boolean; controls?: ReactNode; audioControls?: ReactNode; locked?: boolean }) {
  const { texts } = useI18n()
  const textarea = useRef<HTMLTextAreaElement>(null)
  useLayoutEffect(() => { const el = textarea.current; if (el) { el.style.height = 'auto'; el.style.height = `${Math.min(el.scrollHeight, 200)}px` } }, [value])
  const send = () => { if (!busy && !locked && value.trim()) onSubmit() }
  return <div className="le-composer"><textarea ref={textarea} autoFocus={autoFocus} rows={1} aria-label={placeholder} placeholder={placeholder} value={value} onChange={event => onChange(event.target.value)} onKeyDown={event => { if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); send() } }} /><div className="le-composer-bar">{controls}<span className="le-composer-spacer" />{audioControls}{busy ? <Tooltip content={texts.controls.stop}><button type="button" className="le-send le-send--stop" aria-label={texts.controls.stop} onClick={onStop}><Icon name="square" /></button></Tooltip> : <Tooltip content={texts.controls.sendTip}><button type="button" className="le-send" aria-label={texts.controls.send} disabled={locked || !value.trim()} onClick={send}><Icon name="arrow-up" /></button></Tooltip>}</div></div>
}

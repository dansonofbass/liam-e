import { useId, type InputHTMLAttributes, type TextareaHTMLAttributes } from 'react'
import { Icon } from './Icon'
type Props = { label: string; hint?: string; error?: string } & (({ multiline?: false } & InputHTMLAttributes<HTMLInputElement>) | ({ multiline: true } & TextareaHTMLAttributes<HTMLTextAreaElement>))
export function TextField(props: Props) {
  const generated = useId()
  const { label, hint, error, multiline, id = generated, ...rest } = props
  const description = [hint && `${id}-hint`, error && `${id}-error`].filter(Boolean).join(' ') || undefined
  const shared = { id, className: 'le-input', 'aria-invalid': error ? true : undefined, 'aria-describedby': description }
  return <div className={`le-field${error ? ' is-invalid' : ''}`}><label className="le-label" htmlFor={id}>{label}</label>{multiline ? <textarea {...rest as TextareaHTMLAttributes<HTMLTextAreaElement>} {...shared} /> : <input {...rest as InputHTMLAttributes<HTMLInputElement>} {...shared} />}{hint && <span id={`${id}-hint`} className="le-hint">{hint}</span>}{error && <span id={`${id}-error`} className="le-error"><Icon name="circle-alert" size="sm" />{error}</span>}</div>
}

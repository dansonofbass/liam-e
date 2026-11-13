import { cloneElement, useEffect, useId, useRef, useState, type ReactElement, type HTMLAttributes } from 'react'

type TriggerProps = HTMLAttributes<HTMLElement> & { 'aria-describedby'?: string }
export function Tooltip({ content, children, pos = 'top' }: { content: string; children: ReactElement<TriggerProps>; pos?: 'top' | 'right' | 'bottom' | 'bottom-end' | 'top-end' }) {
  const [visible, setVisible] = useState(false)
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
  const id = useId()
  const clear = () => { clearTimeout(timer.current); timer.current = undefined }
  useEffect(() => () => clearTimeout(timer.current), [])
  return <span className="le-tooltip-anchor">{cloneElement(children, {
    'aria-describedby': [children.props['aria-describedby'], visible && id].filter(Boolean).join(' ') || undefined,
    onMouseEnter: (event) => { children.props.onMouseEnter?.(event); clear(); timer.current = setTimeout(() => setVisible(true), 350) },
    onMouseLeave: (event) => { children.props.onMouseLeave?.(event); clear(); setVisible(false) },
    onFocus: (event) => { children.props.onFocus?.(event); clear(); setVisible(true) },
    onBlur: (event) => { children.props.onBlur?.(event); clear(); setVisible(false) },
  })}{visible && <span role="tooltip" id={id} className={`le-tooltip le-tooltip--${pos}`}>{content}</span>}</span>
}

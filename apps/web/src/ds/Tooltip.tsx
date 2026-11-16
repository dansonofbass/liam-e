import { cloneElement, useEffect, useId, useRef, useState, type ReactElement, type HTMLAttributes } from 'react'
import { createPortal } from 'react-dom'
import { useFloating, type Align, type Side } from './floating'

// DESIGN.md §5: tooltips appear after 350 ms of hovering and at once on keyboard focus.
const HOVER_DELAY_MS = 350
type Pos = 'top' | 'right' | 'bottom' | 'bottom-end' | 'top-end'
type TriggerProps = HTMLAttributes<HTMLElement> & { 'aria-describedby'?: string }
// Focus shows the tip only for keyboard focus; a script moving focus (e.g. into an opened drawer) does not.
const keyboardFocus = (element: Element) => { try { return element.matches(':focus-visible') } catch { return true } }
const PLACEMENT: Record<Pos, [Side, Align]> = { top: ['top', 'center'], 'top-end': ['top', 'end'], bottom: ['bottom', 'center'], 'bottom-end': ['bottom', 'end'], right: ['right', 'center'] }

// The bubble hangs in <body> with fixed coordinates from floating.ts; `pos` is only the preferred side.
export function Tooltip({ content, children, pos = 'top' }: { content: string; children: ReactElement<TriggerProps>; pos?: Pos }) {
  const [visible, setVisible] = useState(false)
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
  const anchor = useRef<HTMLSpanElement>(null)
  const bubble = useRef<HTMLSpanElement>(null)
  const id = useId()
  const clear = () => { clearTimeout(timer.current); timer.current = undefined }
  useEffect(() => () => clearTimeout(timer.current), [])
  const [side, align] = PLACEMENT[pos]
  // A long text (a mail subject) that fits on neither side covers the trigger rather than leave the screen.
  const coords = useFloating(visible, anchor, bubble, side, align, () => setVisible(false), content, true)
  return <span ref={anchor} className="le-tooltip-anchor">{cloneElement(children, {
    'aria-describedby': [children.props['aria-describedby'], visible && id].filter(Boolean).join(' ') || undefined,
    onMouseEnter: (event) => { children.props.onMouseEnter?.(event); clear(); timer.current = setTimeout(() => setVisible(true), HOVER_DELAY_MS) },
    onMouseLeave: (event) => { children.props.onMouseLeave?.(event); clear(); setVisible(false) },
    onFocus: (event) => { children.props.onFocus?.(event); clear(); if (keyboardFocus(event.currentTarget)) setVisible(true) },
    onBlur: (event) => { children.props.onBlur?.(event); clear(); setVisible(false) },
  })}{visible && createPortal(
    <span ref={bubble} role="tooltip" id={id} className="le-tooltip" style={{ left: coords?.left ?? 0, top: coords?.top ?? 0, visibility: coords ? 'visible' : 'hidden' }}>{content}</span>,
    document.body,
  )}</span>
}

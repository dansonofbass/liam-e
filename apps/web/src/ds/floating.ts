import { useLayoutEffect, useRef, useState, type RefObject } from 'react'

// Placement of everything that floats next to a trigger (Tooltip, Menu). Floating elements use fixed
// coordinates from here and hang in <body>, so no scroll area, overflow clip or stacking context
// around the trigger can cut them off or cover them; CSS never positions or styles them per context
// (DESIGN.md §5). The side is a preference: without room they flip, and they are always shifted back
// into the viewport.

// Gap to the trigger and minimum distance to the viewport edge, in px (the --space-2 step).
export const GAP = 8
export const MARGIN = 8
export type Side = 'top' | 'bottom' | 'right'
export type Align = 'start' | 'center' | 'end'
type Box = Pick<DOMRect, 'left' | 'top' | 'right' | 'bottom' | 'width' | 'height'>
export type Spot = { left: number; top: number; maxHeight: number }

const clamp = (value: number, min: number, max: number) => Math.max(min, Math.min(value, max))

// `shift`: an element that fits on neither side moves fully into the viewport, over its trigger if
// need be (a tooltip, which cannot scroll). Without it the element keeps clear of the trigger and
// scrolls within `maxHeight` (a menu).
export function place(trigger: Box, size: { width: number; height: number }, side: Side, align: Align, view: { width: number; height: number }, shift = false): Spot {
  const { width, height } = size
  if (side === 'right' && trigger.right + GAP + width <= view.width - MARGIN) {
    return { left: trigger.right + GAP, top: clamp(trigger.top + trigger.height / 2 - height / 2, MARGIN, view.height - MARGIN - height), maxHeight: view.height - 2 * MARGIN }
  }
  const x = align === 'start' ? trigger.left : align === 'end' ? trigger.right - width : trigger.left + trigger.width / 2 - width / 2
  const left = clamp(x, MARGIN, view.width - MARGIN - width)
  const room = { top: trigger.top - GAP - MARGIN, bottom: view.height - trigger.bottom - GAP - MARGIN }
  // Preferred side first (`right` falls back to above); flip when it lacks room; with room on neither side take the roomier one.
  const preferred = side === 'bottom' ? 'bottom' : 'top'
  const other = preferred === 'top' ? 'bottom' : 'top'
  const chosen = room[preferred] >= height ? preferred : room[other] >= height ? other : room.top >= room.bottom ? 'top' : 'bottom'
  const maxHeight = Math.max(room[chosen], 0)
  const top = chosen === 'top' ? trigger.top - GAP - Math.min(height, maxHeight) : trigger.bottom + GAP
  return { left, top: shift ? clamp(top, MARGIN, view.height - MARGIN - height) : top, maxHeight }
}

// Measures before paint and follows the trigger on scroll, resize and size changes of either element
// (items or fonts that change while open). Until the first measurement the
// spot is null: render the element hidden so it never flashes in the wrong place. A trigger scrolled
// out of the viewport calls `onLost` (hide or close).
export function useFloating(open: boolean, anchor: RefObject<HTMLElement | null>, floating: RefObject<HTMLElement | null>, side: Side, align: Align, onLost: () => void, content?: unknown, shift = false): Spot | null {
  const [spot, setSpot] = useState<Spot | null>(null)
  const lost = useRef(onLost)
  lost.current = onLost
  useLayoutEffect(() => {
    if (!open) { setSpot(null); return }
    const measure = () => {
      if (!anchor.current || !floating.current) return
      const trigger = anchor.current.getBoundingClientRect()
      const view = { width: window.innerWidth, height: window.innerHeight }
      if (trigger.bottom < 0 || trigger.top > view.height || trigger.right < 0 || trigger.left > view.width) { lost.current(); return }
      // Layout size, not the bounding box: the entry animation scales the element. The full content
      // height, not the box a previous max-height cut down.
      const own = floating.current
      const next = place(trigger, { width: own.offsetWidth, height: Math.max(own.offsetHeight, own.scrollHeight) }, side, align, view, shift)
      setSpot(prev => prev && prev.left === next.left && prev.top === next.top && prev.maxHeight === next.maxHeight ? prev : next)
    }
    measure()
    window.addEventListener('scroll', measure, true)
    window.addEventListener('resize', measure)
    const observer = typeof ResizeObserver === 'undefined' ? undefined : new ResizeObserver(measure)
    for (const element of [anchor.current, floating.current]) if (element) observer?.observe(element)
    return () => { window.removeEventListener('scroll', measure, true); window.removeEventListener('resize', measure); observer?.disconnect() }
  }, [open, side, align, content, anchor, floating, shift])
  return spot
}

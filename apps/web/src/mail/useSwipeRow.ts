import { useLayoutEffect, useRef, useState, type MouseEvent, type PointerEvent } from 'react'
import { actionFor, beginSwipe, blocksScroll, endSwipe, moveSwipe, scrollSwipe, SWIPE_INTENT_PX, type SwipeBasis, type SwipeState } from './swipeGesture'

type Action = NonNullable<ReturnType<typeof actionFor>>
type Preview = { action: Action; armed: boolean; direction: 'left' | 'right' }
type ScrollSnapshot = Map<Element, { top: number; left: number }>
type Active = { pointer: number; state: SwipeState; dragged: boolean; scrollHeld: boolean; navigation: string; scrollOrigins: ScrollSnapshot; lockedScroll: ScrollSnapshot | null }
const SUPPRESS_CLICK_MS = 600
const SCROLL_LOCK_TOLERANCE_PX = 2

function captureScrollOrigins(node: Element): ScrollSnapshot {
  const origins: ScrollSnapshot = new Map()
  for (let current: Element | null = node.parentElement; current; current = current.parentElement) {
    origins.set(current, { top: current.scrollTop, left: current.scrollLeft })
  }
  const root = node.ownerDocument.scrollingElement
  if (root && !origins.has(root)) origins.set(root, { top: root.scrollTop, left: root.scrollLeft })
  return origins
}

function captureCurrentScroll(origins: ScrollSnapshot): ScrollSnapshot {
  const snapshot: ScrollSnapshot = new Map()
  for (const target of origins.keys()) snapshot.set(target, { top: target.scrollTop, left: target.scrollLeft })
  return snapshot
}

function exceeds(delta: number, limit: number, strict: boolean): boolean {
  return strict ? delta > limit : delta >= limit
}

function scrollDeltaExceeded(snapshot: ScrollSnapshot, target: Element, limit: number, strict = false): boolean {
  const origin = snapshot.get(target)
  return Boolean(origin && (exceeds(Math.abs(target.scrollTop - origin.top), limit, strict) || exceeds(Math.abs(target.scrollLeft - origin.left), limit, strict)))
}

function anyScrollExceeded(snapshot: ScrollSnapshot | null, limit: number, strict = false): boolean {
  if (!snapshot) return false
  for (const target of snapshot.keys()) {
    if (scrollDeltaExceeded(snapshot, target, limit, strict)) return true
  }
  return false
}

function markDragged(gesture: Active, x: number, y: number) {
  if (!gesture.dragged && Math.hypot(x - gesture.state.x, y - gesture.state.y) >= SWIPE_INTENT_PX) gesture.dragged = true
}

/** One row owns its pointer, animation and preview; movement never updates the list. */
export function useSwipeRow(basis: SwipeBasis | undefined, enabled: boolean, navigation: string, valid: (basis: SwipeBasis) => boolean, run: (action: Action) => void) {
  const row = useRef<HTMLDivElement>(null)
  const active = useRef<Active | null>(null)
  const frame = useRef<number | null>(null)
  const suppressClick = useRef(0)
  const unobserve = useRef<(() => void) | null>(null)
  const [preview, setPreview] = useState<Preview | null>(null)
  const current = useRef({ basis, enabled, navigation, valid, run })
  current.current = { basis, enabled, navigation, valid, run }
  const paint = (dx: number) => {
    if (frame.current !== null) cancelAnimationFrame(frame.current)
    frame.current = requestAnimationFrame(() => {
      frame.current = null
      if (row.current) row.current.style.transform = dx ? `translateX(${dx}px)` : ''
    })
  }
  const detachDocument = () => {
    unobserve.current?.()
    unobserve.current = null
  }
  const stop = (suppress = true) => {
    detachDocument()
    const gesture = active.current
    active.current = null
    // Only the click the browser synthesizes right after this drag is swallowed; a later tap, mouse click or keyboard activation is not.
    if (suppress && gesture?.dragged) suppressClick.current = performance.now() + SUPPRESS_CLICK_MS
    if (gesture && row.current?.hasPointerCapture(gesture.pointer)) row.current.releasePointerCapture(gesture.pointer)
    paint(0)
    setPreview(null)
  }
  const disarmToScroll = (gesture: Active, x: number, y: number) => {
    if (gesture.state.phase !== 'scrolling') {
      gesture.state = gesture.state.phase === 'undecided' ? scrollSwipe(gesture.state) : { ...gesture.state, phase: 'scrolling', dx: 0 }
      gesture.lockedScroll = null
      paint(0)
      setPreview(null)
    }
    markDragged(gesture, x, y)
  }
  const observeDocument = (doc: Document) => {
    detachDocument()
    const interrupt = (event: globalThis.PointerEvent) => {
      if (active.current && event.pointerType === 'touch' && (event.isPrimary || event.pointerId !== active.current.pointer)) {
        stop(!event.isPrimary)
      }
    }
    const onScroll = (event: Event) => {
      const gesture = active.current, node = row.current
      if (!gesture || !node) return
      const target = event.target === doc ? doc.scrollingElement : event.target instanceof Element ? event.target : null
      if (!target || !target.contains(node)) return
      if (blocksScroll(gesture.state)) {
        if (!gesture.lockedScroll || scrollDeltaExceeded(gesture.lockedScroll, target, SCROLL_LOCK_TOLERANCE_PX, true)) stop()
        return
      }
      if (gesture.state.phase === 'undecided' && scrollDeltaExceeded(gesture.scrollOrigins, target, SWIPE_INTENT_PX)) {
        gesture.state = scrollSwipe(gesture.state)
      }
    }
    doc.addEventListener('pointerdown', interrupt, true)
    doc.addEventListener('scroll', onScroll, { capture: true, passive: true })
    unobserve.current = () => {
      doc.removeEventListener('pointerdown', interrupt, true)
      doc.removeEventListener('scroll', onScroll, true)
    }
  }
  const updatePosition = (gesture: Active, x: number, y: number) => {
    const value = current.current
    if (!value.enabled || !value.basis || !value.valid(gesture.state.basis) || value.navigation !== gesture.navigation) { stop(); return }
    const wasBlocked = blocksScroll(gesture.state)
    if (wasBlocked && anyScrollExceeded(gesture.lockedScroll, SCROLL_LOCK_TOLERANCE_PX, true)) { stop(); return }
    if (gesture.state.phase === 'undecided' && anyScrollExceeded(gesture.scrollOrigins, SWIPE_INTENT_PX)) {
      gesture.state = scrollSwipe(gesture.state)
    }
    markDragged(gesture, x, y)
    // Browsers can deliver both events for the same physical movement.
    if (gesture.state.phase === 'scrolling' || (wasBlocked && x - gesture.state.x === gesture.state.dx)) return
    gesture.state = moveSwipe(gesture.state, x, y, value.basis)
    if (gesture.state.phase === 'cancelled') { stop(); return }
    if (gesture.state.phase !== 'preview' && gesture.state.phase !== 'armed') return
    if (!wasBlocked) gesture.lockedScroll = captureCurrentScroll(gesture.scrollOrigins)
    gesture.dragged = true
    const action = actionFor(gesture.state)
    paint(action ? gesture.state.dx : 0)
    const next = action ? { action, armed: gesture.state.phase === 'armed', direction: gesture.state.dx < 0 ? 'left' as const : 'right' as const } : null
    setPreview(old => old?.action === next?.action && old?.armed === next?.armed && old?.direction === next?.direction ? old : next)
  }
  useLayoutEffect(() => {
    const gesture = active.current
    if (!gesture) return
    const value = current.current
    if (!value.enabled || !value.basis || !value.valid(gesture.state.basis) || value.navigation !== gesture.navigation || moveSwipe(gesture.state, gesture.state.x + gesture.state.dx, gesture.state.y, value.basis).phase === 'cancelled') stop()
  })
  useLayoutEffect(() => {
    const cancel = () => { if (active.current) stop() }
    // touch-action: pan-y is not enough on iOS: without a prevented touchmove WebKit hands a decided swipe to scrolling and
    // cancels the pointer. React registers touchmove as passive, so the row listens natively. Two fingers stay free to pinch.
    const hold = (event: TouchEvent) => {
      const gesture = active.current
      if (!gesture) return
      if (event.touches.length !== 1) { stop(); return }
      const touch = event.touches[0]!
      // If scrolling already owns the touch before the row ever prevented it, disarm the swipe while tracking displacement until release.
      if (!event.cancelable && !gesture.scrollHeld) { disarmToScroll(gesture, touch.clientX, touch.clientY); return }
      // A native touchmove may precede the corresponding pointermove. Decide from
      // this sample while the browser can still yield the gesture to the row.
      updatePosition(gesture, touch.clientX, touch.clientY)
      if (active.current === gesture && blocksScroll(gesture.state)) {
        if (event.cancelable) { event.preventDefault(); gesture.scrollHeld = true }
        else if (!gesture.scrollHeld) disarmToScroll(gesture, touch.clientX, touch.clientY)
      }
    }
    const node = row.current
    node?.addEventListener('touchmove', hold, { passive: false })
    node?.addEventListener('touchcancel', cancel)
    return () => {
      detachDocument()
      node?.removeEventListener('touchmove', hold)
      node?.removeEventListener('touchcancel', cancel)
      active.current = null
      if (frame.current !== null) cancelAnimationFrame(frame.current)
    }
  }, [])
  const onPointerDown = (event: PointerEvent<HTMLDivElement>) => {
    if (event.isPrimary) suppressClick.current = 0
    if (active.current || event.pointerType !== 'touch' || !event.isPrimary || !current.current.enabled || !current.current.basis) return
    // A control keeps the gesture, except the row's own open link: it spans the subject line and is the row itself.
    const control = (event.target as Element).closest('button, a, input, select, textarea, [role="menu"], [role="menuitem"]')
    if (event.clientX < 24 || event.clientX > window.innerWidth - 24 || (control && !control.hasAttribute('data-swipe-start'))) return
    active.current = { pointer: event.pointerId, state: beginSwipe(current.current.basis, event.clientX, event.clientY, event.currentTarget.getBoundingClientRect().width), dragged: false, scrollHeld: false, navigation: current.current.navigation, scrollOrigins: captureScrollOrigins(event.currentTarget), lockedScroll: null }
    observeDocument(event.currentTarget.ownerDocument)
    event.currentTarget.setPointerCapture(event.pointerId)
  }
  const onPointerMove = (event: PointerEvent<HTMLDivElement>) => {
    const gesture = active.current
    if (gesture?.pointer === event.pointerId) updatePosition(gesture, event.clientX, event.clientY)
  }
  const onPointerUp = (event: PointerEvent<HTMLDivElement>) => {
    const gesture = active.current, value = current.current
    if (!gesture || gesture.pointer !== event.pointerId) return
    markDragged(gesture, event.clientX, event.clientY)
    const basis = value.basis
    const scrolled = blocksScroll(gesture.state)
      ? anyScrollExceeded(gesture.lockedScroll, SCROLL_LOCK_TOLERANCE_PX, true)
      : anyScrollExceeded(gesture.scrollOrigins, SWIPE_INTENT_PX)
    const armed = !scrolled && basis && endSwipe(gesture.state, basis)
    // A release can carry a newer position. Commit only the action already
    // previewed, with the finger still past its threshold on the same side.
    const release = basis && armed && endSwipe(moveSwipe(gesture.state, event.clientX, event.clientY, basis), basis)
    const sameSide = Math.sign(event.clientX - gesture.state.x) === Math.sign(gesture.state.dx)
    stop()
    if (release && sameSide && value.enabled && value.navigation === gesture.navigation && value.valid(gesture.state.basis)) value.run(release.action)
  }
  const onPointerCancel = (event: PointerEvent<HTMLDivElement>) => { if (active.current?.pointer === event.pointerId) stop() }
  const onClickCapture = (event: MouseEvent<HTMLDivElement>) => {
    if (performance.now() < suppressClick.current) { suppressClick.current = 0; event.preventDefault(); event.stopPropagation() }
  }
  return { row, preview, onPointerDown, onPointerMove, onPointerUp, onPointerCancel, onLostPointerCapture: onPointerCancel, onClickCapture }
}

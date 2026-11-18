import { describe, expect, test } from 'bun:test'
import { beginSwipe, blocksScroll, moveSwipe, endSwipe, cancelSwipe, type SwipeBasis } from './swipeGesture'

const basis: SwipeBasis = { id: 'mail-1', isRead: false, revision: 1, left: 'archive', right: 'toggle_read' }
const start = () => beginSwipe(basis, 200, 100, 300)

describe('swipe gesture', () => {
  test('requires horizontal intent and a distance threshold, not velocity', () => {
    expect(endSwipe(moveSwipe(start(), 250, 100, basis), basis)).toBeUndefined()
    expect(endSwipe(moveSwipe(start(), 289, 100, basis), basis)).toBeUndefined()
    expect(endSwipe(moveSwipe(start(), 290, 100, basis), basis)).toEqual({ id: 'mail-1', action: 'mark_read' })
  })
  test('disarms on return below threshold and vertical intent wins permanently', () => {
    const armed = moveSwipe(start(), 300, 100, basis)
    expect(armed.phase).toBe('armed')
    expect(endSwipe(moveSwipe(armed, 250, 100, basis), basis)).toBeUndefined()
    const scroll = moveSwipe(start(), 205, 115, basis)
    expect(endSwipe(moveSwipe(scroll, 310, 115, basis), basis)).toBeUndefined()
  })
  test('cancellation and changed identity, read state or settings never execute', () => {
    const armed = moveSwipe(start(), 300, 100, basis)
    expect(endSwipe(cancelSwipe(armed), basis)).toBeUndefined()
    for (const changed of [{ ...basis, id: 'mail-2' }, { ...basis, isRead: true }, { ...basis, revision: 2 }, { ...basis, right: 'trash' as const }]) {
      expect(endSwipe(armed, changed)).toBeUndefined()
      expect(endSwipe(moveSwipe(armed, 310, 100, changed), basis)).toBeUndefined()
    }
  })
  test('uses the concrete direction and clamps thresholds to 72–112 pixels', () => {
    expect(endSwipe(moveSwipe(beginSwipe(basis, 200, 0, 100), 128, 0, basis), basis)).toEqual({ id: 'mail-1', action: 'archive' })
    expect(endSwipe(moveSwipe(beginSwipe(basis, 200, 0, 1000), 89, 0, basis), basis)).toBeUndefined()
    expect(endSwipe(moveSwipe(beginSwipe(basis, 200, 0, 1000), 88, 0, basis), basis)).toEqual({ id: 'mail-1', action: 'archive' })
  })
  test('keeps a horizontal touch from native scrolling, but never a vertical one', () => {
    expect(blocksScroll(start(), 200, 100)).toBe(false)
    expect(blocksScroll(start(), 204, 101)).toBe(true)
    expect(blocksScroll(start(), 201, 105)).toBe(false)
    const preview = moveSwipe(start(), 230, 110, basis)
    expect(preview.phase).toBe('preview')
    // A thumb arc drifts far from the row's line once the swipe is decided; the row keeps the touch.
    expect(blocksScroll(preview, 120, 180)).toBe(true)
    expect(blocksScroll(moveSwipe(start(), 300, 140, basis), 300, 140)).toBe(true)
    const scroll = moveSwipe(start(), 203, 120, basis)
    expect(scroll.phase).toBe('scrolling')
    expect(blocksScroll(scroll, 320, 120)).toBe(false)
    expect(blocksScroll(cancelSwipe(preview), 230, 110)).toBe(false)
  })
})

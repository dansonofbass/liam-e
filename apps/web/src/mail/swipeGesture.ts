import type { SwipeAction } from '../settings/useSwipeSettings'

export const SWIPE_INTENT_PX = 12
export const SWIPE_INTENT_RATIO = 1.5
export const SWIPE_MIN_PX = 72
export const SWIPE_MAX_PX = 112
export const SWIPE_WIDTH_RATIO = 0.3

export type SwipeBasis = { id: string; isRead: boolean; revision: number; left: SwipeAction; right: SwipeAction }
type Phase = 'undecided' | 'scrolling' | 'preview' | 'armed' | 'cancelled'
export type SwipeState = { phase: Phase; basis: SwipeBasis; x: number; y: number; threshold: number; dx: number }
type Action = 'archive' | 'trash' | 'mark_read' | 'mark_unread'

const sameBasis = (a: SwipeBasis, b: SwipeBasis) => a.id === b.id && a.isRead === b.isRead && a.revision === b.revision && a.left === b.left && a.right === b.right
export const actionFor = (state: SwipeState): Action | undefined => {
  const assignment = state.dx < 0 ? state.basis.left : state.basis.right
  return assignment === 'none' ? undefined : assignment === 'toggle_read' ? (state.basis.isRead ? 'mark_unread' : 'mark_read') : assignment
}

export function beginSwipe(basis: SwipeBasis, x: number, y: number, width: number): SwipeState {
  return { phase: 'undecided', basis: { ...basis }, x, y, dx: 0, threshold: Math.min(SWIPE_MAX_PX, Math.max(SWIPE_MIN_PX, width * SWIPE_WIDTH_RATIO)) }
}
export function cancelSwipe(state: SwipeState): SwipeState { return { ...state, phase: 'cancelled' } }
export function moveSwipe(state: SwipeState, x: number, y: number, basis: SwipeBasis): SwipeState {
  if (!sameBasis(state.basis, basis)) return cancelSwipe(state)
  if (state.phase === 'cancelled' || state.phase === 'scrolling') return state
  const dx = x - state.x, dy = y - state.y
  if (state.phase === 'undecided') {
    if (Math.abs(dy) >= SWIPE_INTENT_PX && Math.abs(dy) >= Math.abs(dx)) return { ...state, phase: 'scrolling', dx }
    if (Math.abs(dx) < SWIPE_INTENT_PX || Math.abs(dx) <= SWIPE_INTENT_RATIO * Math.abs(dy)) return { ...state, dx }
  }
  const next = { ...state, dx }
  return { ...next, phase: Math.abs(dx) >= state.threshold && actionFor(next) ? 'armed' : 'preview' }
}
export function endSwipe(state: SwipeState, basis: SwipeBasis): { id: string; action: Action } | undefined {
  if (state.phase !== 'armed' || !sameBasis(state.basis, basis)) return undefined
  const action = actionFor(state)
  return action ? { id: state.basis.id, action } : undefined
}

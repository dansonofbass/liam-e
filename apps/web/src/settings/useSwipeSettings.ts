import { useQuery } from '@tanstack/react-query'
import type { UiSettingsOut } from '../api/generated/types.gen'
import { uiSettingsQuery } from '../api/queries'

export type SwipeAction = UiSettingsOut['swipe_left']
export type SwipeAssignment = { left: SwipeAction; right: SwipeAction }

/** The server-confirmed swipe assignment, for surfaces that gesture over a mail row. */
export interface SwipeSettings {
  /** ``ready`` once the server confirmed an assignment, ``error`` while none is confirmed. */
  status: 'loading' | 'error' | 'ready'
  /**
   * The confirmed assignment. It stays undefined until the server answered, so an unloaded or
   * failed state never falls back to defaults: gestures stay off rather than replace a
   * possibly different personal assignment with default actions.
   */
  assignment: SwipeAssignment | undefined
  /** The confirmed revision, for callers that change the assignment. */
  revision: number | undefined
  /** Asks for the assignment again after a failure. */
  retry: () => void
}

export function useSwipeSettings(): SwipeSettings {
  const query = useQuery(uiSettingsQuery())
  return {
    // A failed background refetch keeps the last confirmed assignment: it is still what the
    // server last accepted, and gestures may keep following it.
    status: query.data ? 'ready' : query.isPending ? 'loading' : 'error',
    assignment: query.data && { left: query.data.swipe_left, right: query.data.swipe_right },
    revision: query.data?.revision,
    retry: () => { void query.refetch() },
  }
}

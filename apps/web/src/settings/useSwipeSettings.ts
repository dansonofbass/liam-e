import { useQuery } from '@tanstack/react-query'
import type { UiSettingsOut } from '../api/generated/types.gen'
import { uiSettingsQuery } from '../api/queries'

export type SwipeAction = UiSettingsOut['swipe_left']
export type SwipeAssignment = { left: SwipeAction; right: SwipeAction }

/** The server-confirmed swipe assignment, for surfaces that gesture over a mail row. */
export interface SwipeSettings {
  /** ``ready`` once the server confirmed an assignment, ``error`` after any failed load or refetch. */
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
  // A failed refetch turns gestures off as well: the last answer may no longer be what another
  // device saved, and an error must never keep actions running the owner may have switched off.
  const data = query.isError ? undefined : query.data
  return {
    status: data ? 'ready' : query.isError ? 'error' : 'loading',
    assignment: data && { left: data.swipe_left, right: data.swipe_right },
    revision: data?.revision,
    retry: () => { void query.refetch() },
  }
}

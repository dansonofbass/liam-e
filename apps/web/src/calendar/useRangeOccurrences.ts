import { useQuery } from '@tanstack/react-query'
import { calendarOccurrencesList } from '../api/generated/sdk.gen'
import type { ApiRoutersApiV1CalendarSchemasOccurrenceOut as OccurrenceOut, SourceOut } from '../api/generated/types.gen'
import { CalendarAccessLost, calendarIndexCache, readCalendarIndex, sourceScope } from './cache'
import { browserZone, queryWindows, validWindow } from './state'

export function useRangeOccurrences(from: string, to: string, sources: SourceOut[]) {
  const zone = browserZone()
  const scope = sourceScope(sources)
  const ids = scope.map(([id]) => id)
  const result = useQuery({
    queryKey: ['calendar', 'range', from, to, zone, scope],
    ...calendarIndexCache,
    meta: { calendarSourceIds: ids },
    enabled: validWindow(from, to) && ids.length > 0,
    queryFn: async context => {
      const { signal } = context
      const unique = new Map<string, OccurrenceOut>()
      let capped = false
      for (const window of queryWindows(from, to, zone)) {
        let cursor: string | undefined
        for (let count = 0; count < 10; count++) {
          const page = await readCalendarIndex(context, calendarOccurrencesList({ signal, query: { ...window, source_ids: ids, cursor, limit: 100 } }))
          for (const row of page.items) unique.set(row.id, row)
          cursor = page.next_cursor ?? undefined
          if (!cursor) break
          if (count === 9) capped = true
        }
      }
      return { rows: [...unique.values()], capped }
    },
  })
  const active = new Set(ids)
  return {
    rows: result.error instanceof CalendarAccessLost ? [] : (result.data?.rows ?? []).filter(row => active.has(row.source_id)),
    complete: result.isSuccess && !result.data.capped,
    capped: result.data?.capped ?? false,
    isPending: result.isPending && ids.length > 0,
    isRefetching: result.isRefetching,
    isRefetchError: result.isRefetchError && !(result.error instanceof CalendarAccessLost),
    isError: result.isError,
    refetch: () => { void result.refetch() },
  }
}

import { useQuery } from '@tanstack/react-query'
import { calendarOccurrencesList } from '../api/generated/sdk.gen'
import type { ApiRoutersApiV1CalendarSchemasOccurrenceOut as OccurrenceOut } from '../api/generated/types.gen'
import { unwrap } from '../api/unwrap'
import { browserZone, queryWindows, validWindow } from './state'

export function useRangeOccurrences(from: string, to: string, sourceIds: string[]): { rows: OccurrenceOut[]; complete: boolean; capped: boolean; isPending: boolean; isError: boolean; refetch(): void } {
  const zone = browserZone()
  const ids = [...sourceIds].sort()
  const result = useQuery({
    queryKey: ['calendar', 'range', from, to, zone, ids],
    enabled: validWindow(from, to) && ids.length > 0,
    queryFn: async () => {
      const unique = new Map<string, OccurrenceOut>()
      let capped = false
      for (const window of queryWindows(from, to, zone)) {
        let cursor: string | undefined
        for (let count = 0; count < 10; count++) {
          const page = await unwrap(calendarOccurrencesList({ query: { ...window, source_ids: ids, cursor, limit: 100 }, throwOnError: true }))
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
  return { rows: (result.data?.rows ?? []).filter(row => active.has(row.source_id)), complete: result.isSuccess && !result.data.capped, capped: result.data?.capped ?? false, isPending: result.isPending && ids.length > 0, isError: result.isError, refetch: () => { void result.refetch() } }
}

import type { QueryClient, QueryFunctionContext } from '@tanstack/react-query'
import { ApiError } from '../api/unwrap'
import type { SourceOut } from '../api/generated/types.gen'

// Only the index is reusable. Provider reads used to edit an event have their own query.
export const calendarIndexCache = { staleTime: 5 * 60_000, gcTime: 10 * 60_000 }
export const calendarSourceInterval = 60_000

export function sourceScope(sources: SourceOut[]) {
  return sources.map(source => [source.id, source.revision ?? 1] as const)
    .sort(([a], [b]) => a.localeCompare(b))
}

export class CalendarAccessLost extends ApiError {}

export async function readCalendarIndex<T>(context: Pick<QueryFunctionContext, 'client' | 'queryKey' | 'signal'>, request: Promise<{ data?: T; error?: unknown; response?: Response }>) {
  const { data, error, response } = await request
  if (response && [401, 403, 404].includes(response.status)) {
    if (!context.signal.aborted) {
      // A later network error must not reveal rows whose access was already refused.
      const query = context.client.getQueryCache().find({ queryKey: context.queryKey, exact: true })
      query?.setState({ data: undefined, dataUpdatedAt: 0, status: 'pending' })
      if (context.queryKey[1] !== 'sources') void context.client.invalidateQueries({ queryKey: ['calendar', 'sources'] })
    }
    throw new CalendarAccessLost(error)
  }
  if (error || data === undefined) throw new ApiError(error)
  return data
}

/** A completed worker snapshot or local write can advance while the range is still fresh. */
export async function refreshChangedIndexes(client: QueryClient, previous: SourceOut[], next: SourceOut[]) {
  const old = new Map(previous.map(source => [source.id, source]))
  const changed = new Set(next.filter(source => {
    const before = old.get(source.id)
    return source.is_active && before?.is_active && before.revision === source.revision
      && before.data_revision !== source.data_revision
  }).map(source => source.id))
  if (!changed.size) return

  const affected = { queryKey: ['calendar'], predicate: (query: { meta?: Record<string, unknown> }) =>
    Array.isArray(query.meta?.calendarSourceIds) && query.meta.calendarSourceIds.some(id => changed.has(id)) }
  // Even a first page that has not returned yet may belong to the earlier snapshot.
  await client.cancelQueries(affected)
  void client.invalidateQueries(affected)
}

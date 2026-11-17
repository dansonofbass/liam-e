import { tasksReconcile } from '../api/generated/sdk.gen'
import type { ReconcileIn, ReconcileOut } from '../api/generated/types.gen'
import { unwrap } from '../api/unwrap'

// One invocation finishes at most one fixed server horizon. It never retries a write:
// after an interrupted request the caller can start again without a cursor and resume
// from the server's persisted position. A complete first response may be advanced once.
export async function reconcileTask(
  seriesId: string,
  options: { signal?: AbortSignal; maxPages?: number; request?: (body: ReconcileIn) => Promise<ReconcileOut> } = {},
): Promise<ReconcileOut | null> {
  const request = options.request ?? (body => unwrap(tasksReconcile({ body, throwOnError: true, signal: options.signal })))
  const maxPages = Math.max(1, Math.min(options.maxPages ?? 5, 20))
  let result: ReconcileOut | null = null
  let advanced = false
  for (let page = 0; page < maxPages; page++) {
    if (options.signal?.aborted) break
    const body: ReconcileIn = result
      ? { series_id: seriesId, revision_id: result.revision_id, cursor: result.cursor, advance: result.complete && !advanced, limit: 100 }
      : { series_id: seriesId, limit: 100 }
    if (body.advance) advanced = true
    result = await request(body)
    if (result.complete && (advanced || page > 0)) break
  }
  return result
}

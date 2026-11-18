import { useSyncExternalStore } from 'react'
import type { WriteOutcome } from '../api/generated/types.gen'
import { errorCode } from '../api/unwrap'
import { de } from '../i18n/de'

export function writeError(code?: string | null): string {
  return de.calendar.writeErrors[code as keyof typeof de.calendar.writeErrors] ?? de.calendar.writeErrors.calendar_write_unknown
}
// HTTP conflicts carry the outcome under detail, unlike successful and pending responses.
export function writeOutcome(result: { data?: WriteOutcome; error?: unknown; response?: { status: number } }): WriteOutcome {
  if (result.data && (!result.response || result.response.status < 400)) return result.data
  const detail = (result.error as { detail?: WriteOutcome } | undefined)?.detail
  if (detail && typeof detail.status === 'string' && ['done', 'failed', 'unknown', 'running', 'not_applied'].includes(detail.status)) return detail
  const code = errorCode(result.error)
  return { write_id: '', status: code ? 'failed' : 'unknown', error_code: code ?? 'calendar_write_unknown' }
}
export function safeCalendarLink(value?: string | null): string | undefined {
  try { const url = new URL(value ?? ''); return url.protocol === 'https:' ? url.href : undefined } catch { return undefined }
}

// An unknown or running write must be resolved with its own write ID: a new ID could apply the
// same change twice (a duplicate appointment for a create). Writes stay registered after their
// dialog closes, so the calendar can ask for a check first. A page reload forgets them; the server
// record remains and a later check by write ID still resolves it.
export type UnresolvedWrite = { writeId: string; kind: 'create' | 'update' | 'delete'; occurrenceId?: string }
let unresolved: UnresolvedWrite[] = []
const listeners = new Set<() => void>()
export function trackWrite(entry: UnresolvedWrite, status: WriteOutcome['status']): void {
  const rest = unresolved.filter(item => item.writeId !== entry.writeId)
  const next = status === 'unknown' || status === 'running' ? [...rest, entry] : rest
  if (next.length === unresolved.length && next.every((item, i) => item === unresolved[i])) return
  unresolved = next
  for (const listener of listeners) listener()
}
export function unresolvedWrites(): UnresolvedWrite[] { return unresolved }
export function resetUnresolvedWrites(): void { unresolved = []; for (const listener of listeners) listener() }
export function useUnresolvedWrites(): UnresolvedWrite[] {
  return useSyncExternalStore(listener => { listeners.add(listener); return () => { listeners.delete(listener) } }, unresolvedWrites, unresolvedWrites)
}

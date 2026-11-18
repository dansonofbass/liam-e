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

import { de } from '../i18n/de'
import { formatDeadline } from '../i18n/format'

export function formatTaskDue(value: string): string {
  const [date, time] = value.split('T')
  return `${formatDeadline(date!)}${time ? ` · ${time.slice(0, 5)}` : ''}`
}
// IANA names only: Intl also accepts offsets such as "+01:00", which the server rejects. The
// browser itself decides the rest, so aliases it reports (e.g. Asia/Calcutta) stay valid and an
// engine without Intl.supportedValuesOf does not break the form.
export function isTimeZone(zone: string): boolean {
  if (!/^[A-Za-z][A-Za-z0-9_+\-]*(\/[A-Za-z0-9_+\-]+)*$/.test(zone)) return false
  try { new Intl.DateTimeFormat('de-DE', { timeZone: zone }); return true } catch { return false }
}
export function formatTaskRule(rule: string | null | undefined): string {
  if (!rule) return de.tasks.none
  const parts = Object.fromEntries(rule.split(';').map(part => part.split('=')))
  if (Object.keys(parts).some(key => !['FREQ', 'INTERVAL'].includes(key)) || (parts.INTERVAL && parts.INTERVAL !== '1')) return de.tasks.custom
  return parts.FREQ === 'DAILY' ? de.tasks.daily : parts.FREQ === 'WEEKLY' ? de.tasks.weekly : parts.FREQ === 'MONTHLY' ? de.tasks.monthly : de.tasks.custom
}

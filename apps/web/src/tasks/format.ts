import { catalogue } from '../i18n/catalogue'
import { formatDeadline, formatMinuteOfDay } from '../i18n/format'
import { REFERENCE_LOCALE, type Locale } from '../i18n/locales'

export function formatTaskDue(value: string, locale: Locale = REFERENCE_LOCALE): string {
  const [date, time] = value.split('T')
  const due = formatDeadline(date!, undefined, locale)
  if (!time) return due
  const [hour = 0, minute = 0] = time.slice(0, 5).split(':').map(Number)
  return `${due} · ${formatMinuteOfDay(hour * 60 + minute, locale)}`
}
// IANA names only: Intl also accepts offsets such as "+01:00", which the server rejects. The
// browser itself decides the rest, so aliases it reports (e.g. Asia/Calcutta) stay valid and an
// engine without Intl.supportedValuesOf does not break the form.
export function isTimeZone(zone: string): boolean {
  if (!/^[A-Za-z][A-Za-z0-9_+\-]*(\/[A-Za-z0-9_+\-]+)*$/.test(zone)) return false
  try { new Intl.DateTimeFormat(undefined, { timeZone: zone }); return true } catch { return false }
}
export function formatTaskRule(rule: string | null | undefined, locale: Locale = REFERENCE_LOCALE): string {
  const labels = catalogue(locale).tasks
  if (!rule) return labels.none
  const parts = Object.fromEntries(rule.split(';').map(part => part.split('=')))
  if (Object.keys(parts).some(key => !['FREQ', 'INTERVAL'].includes(key)) || (parts.INTERVAL && parts.INTERVAL !== '1')) return labels.custom
  return parts.FREQ === 'DAILY' ? labels.daily : parts.FREQ === 'WEEKLY' ? labels.weekly : parts.FREQ === 'MONTHLY' ? labels.monthly : labels.custom
}

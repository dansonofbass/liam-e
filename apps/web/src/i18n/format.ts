import { catalogue } from './catalogue'
import { REFERENCE_LOCALE, intlLocale, type Locale } from './locales'

export { plural } from './numbers'

export function formatTime(d: Date, timeZone?: string, locale: Locale = REFERENCE_LOCALE): string {
  return new Intl.DateTimeFormat(intlLocale[locale], { timeZone, hour: '2-digit', minute: '2-digit' }).format(d)
}

export function formatDayShort(d: Date, timeZone?: string, locale: Locale = REFERENCE_LOCALE): string {
  return new Intl.DateTimeFormat(intlLocale[locale], { timeZone, weekday: 'short', day: 'numeric', month: 'numeric' }).format(d)
}

export function formatDeadline(value: string, now = new Date(), locale: Locale = REFERENCE_LOCALE): string {
  const [year, month, day] = value.split('-').map(Number) as [number, number, number]
  return new Intl.DateTimeFormat(intlLocale[locale], { timeZone: 'UTC', weekday: 'short', day: 'numeric', month: 'numeric', year: year === now.getFullYear() ? undefined : 'numeric' }).format(new Date(Date.UTC(year, month - 1, day)))
}

function calendarDay(d: Date, timeZone?: string, locale: Locale = REFERENCE_LOCALE): number {
  const parts = new Intl.DateTimeFormat(intlLocale[locale], { timeZone, year: 'numeric', month: 'numeric', day: 'numeric' }).formatToParts(d)
  const get = (type: Intl.DateTimeFormatPartTypes) => Number(parts.find((part) => part.type === type)?.value)
  return Date.UTC(get('year'), get('month') - 1, get('day')) / 86400000
}

export function formatRelativeDay(d: Date, now: Date, timeZone?: string, locale: Locale = REFERENCE_LOCALE): string {
  const day = calendarDay(d, timeZone, locale), today = calendarDay(now, timeZone, locale)
  if (day === today) return catalogue(locale).date.today
  if (day === today - 1) return catalogue(locale).date.yesterday
  const monday = today - ((new Date(today * 86400000).getUTCDay() + 6) % 7)
  if (day >= monday && day < today) return formatShortWeekday(d, timeZone, locale)
  const year = new Date(day * 86400000).getUTCFullYear() !== new Date(today * 86400000).getUTCFullYear() ? 'numeric' : undefined
  return new Intl.DateTimeFormat(intlLocale[locale], { timeZone, day: 'numeric', month: 'numeric', year }).format(d)
}

export function formatMailTime(d: Date, now: Date, timeZone?: string, locale: Locale = REFERENCE_LOCALE): string {
  return `${formatRelativeDay(d, now, timeZone, locale)}, ${formatTime(d, timeZone, locale)}`
}

export function formatListDate(d: Date, now: Date, timeZone?: string, locale: Locale = REFERENCE_LOCALE): string {
  return calendarDay(d, timeZone, locale) === calendarDay(now, timeZone, locale) ? formatTime(d, timeZone, locale) : formatRelativeDay(d, now, timeZone, locale)
}

export function formatBytes(n: number, locale: Locale = REFERENCE_LOCALE): string {
  const units = ['B', 'KB', 'MB', 'GB', 'TB'] // i18n-exempt
  let value = n, unit = 0
  while (value >= 1024 && unit < units.length - 1) { value /= 1024; unit++ }
  return `${new Intl.NumberFormat(intlLocale[locale], { maximumFractionDigits: 1 }).format(value)}\u00a0${units[unit]}`
}

export function formatStand(accounts: number, at: Date, timeZone?: string, locale: Locale = REFERENCE_LOCALE): string {
  return catalogue(locale).date.stand(accounts, formatTime(at, timeZone, locale))
}

export function formatShortWeekday(d: Date, timeZone: string | undefined, locale: Locale): string {
  const weekday = new Intl.DateTimeFormat(intlLocale[locale], { timeZone, weekday: 'short' }).format(d)
  return locale === 'de' && !weekday.endsWith('.') ? weekday + '.' : weekday
}

export function formatMinuteOfDay(minutes: number, locale: Locale): string {
  return formatTime(new Date(minutes * 60_000), 'UTC', locale)
}

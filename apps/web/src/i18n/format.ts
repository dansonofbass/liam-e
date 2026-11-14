const locale = 'de-DE' // i18n-exempt

export function plural(n: number, forms: { zero?: string; one: string; other: string }): string {
  const form = n === 0 && forms.zero !== undefined ? forms.zero : new Intl.PluralRules(locale).select(n) === 'one' ? forms.one : forms.other
  return form.replaceAll('#', new Intl.NumberFormat(locale).format(n))
}

export function formatTime(d: Date, timeZone?: string): string {
  return new Intl.DateTimeFormat(locale, { timeZone, hour: '2-digit', minute: '2-digit' }).format(d)
}

export function formatDayShort(d: Date, timeZone?: string): string {
  return new Intl.DateTimeFormat(locale, { timeZone, weekday: 'short', day: 'numeric', month: 'numeric' }).format(d)
}

export function formatDeadline(value: string, now = new Date()): string {
  const [year, month, day] = value.split('-').map(Number) as [number, number, number]
  return new Intl.DateTimeFormat(locale, { timeZone: 'UTC', weekday: 'short', day: 'numeric', month: 'numeric', year: year === now.getFullYear() ? undefined : 'numeric' }).format(new Date(Date.UTC(year, month - 1, day)))
}

function calendarDay(d: Date, timeZone?: string): number {
  const parts = new Intl.DateTimeFormat(locale, { timeZone, year: 'numeric', month: 'numeric', day: 'numeric' }).formatToParts(d)
  const get = (type: Intl.DateTimeFormatPartTypes) => Number(parts.find((part) => part.type === type)?.value)
  return Date.UTC(get('year'), get('month') - 1, get('day')) / 86400000
}

export function formatRelativeDay(d: Date, now: Date, timeZone?: string): string {
  const day = calendarDay(d, timeZone), today = calendarDay(now, timeZone)
  if (day === today) return 'Heute'
  if (day === today - 1) return 'Gestern'
  const monday = today - ((new Date(today * 86400000).getUTCDay() + 6) % 7)
  if (day >= monday && day < today) {
    const weekday = new Intl.DateTimeFormat(locale, { timeZone, weekday: 'short' }).format(d)
    return weekday.endsWith('.') ? weekday : `${weekday}.`
  }
  const year = new Date(day * 86400000).getUTCFullYear() !== new Date(today * 86400000).getUTCFullYear() ? 'numeric' : undefined
  return new Intl.DateTimeFormat(locale, { timeZone, day: 'numeric', month: 'numeric', year }).format(d)
}

export function formatMailTime(d: Date, now: Date, timeZone?: string): string {
  return `${formatRelativeDay(d, now, timeZone)}, ${formatTime(d, timeZone)}`
}

export function formatListDate(d: Date, now: Date, timeZone?: string): string {
  return calendarDay(d, timeZone) === calendarDay(now, timeZone) ? formatTime(d, timeZone) : formatRelativeDay(d, now, timeZone)
}

export function formatBytes(n: number): string {
  const units = ['B', 'KB', 'MB', 'GB', 'TB'] // i18n-exempt
  let value = n, unit = 0
  while (value >= 1024 && unit < units.length - 1) { value /= 1024; unit++ }
  return `${new Intl.NumberFormat(locale, { maximumFractionDigits: 1 }).format(value)}\u00a0${units[unit]}`
}

export function formatStand(accounts: number, at: Date, timeZone?: string): string {
  return `${plural(accounts, { one: '# Konto', other: '# Konten' })} · Stand ${formatTime(at, timeZone)}`
}

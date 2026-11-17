// Serialize structured choices only; the server remains responsible for recurrence expansion.

/** Convert the final second of a local calendar day to an RFC 5545 UTC UNTIL. */
export function timedUntil(day: string, zone: string): string {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(day)) throw new Error('invalid day')
  const formatter = new Intl.DateTimeFormat('en-GB', { timeZone: zone, year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23' })
  const desired = `${day}T23:59:59`
  const naive = Date.parse(`${desired}Z`)
  if (!Number.isFinite(naive) || new Date(naive).toISOString().slice(0, 10) !== day) throw new Error('invalid day')
  const local = (instant: number) => {
    const parts = Object.fromEntries(formatter.formatToParts(new Date(instant)).map(p => [p.type, p.value]))
    return `${parts.year}-${parts.month}-${parts.day}T${parts.hour}:${parts.minute}:${parts.second}`
  }
  // Sample offsets around the boundary, including either side of a DST transition.
  const matches = new Set<number>()
  for (let h = -36; h <= 36; h += 6) {
    const sample = naive + h * 3600000
    const offset = Date.parse(`${local(sample)}Z`) - sample
    const candidate = naive - offset
    if (local(candidate) === desired) matches.add(candidate)
  }
  if (!matches.size) throw new Error('nonexistent end of day')
  return new Date(Math.max(...matches)).toISOString().replace(/[-:]/g, '').replace('.000Z', 'Z')
}
export type Weekday = 'MO' | 'TU' | 'WE' | 'TH' | 'FR' | 'SA' | 'SU'
export type Recurrence = {
  frequency: 'DAILY' | 'WEEKLY' | 'MONTHLY'
  interval: number
  weekdays?: Weekday[]
  monthday?: number | 'last'
  end?: { kind: 'count'; count: number } | { kind: 'until'; value: string }
}

export function recurrenceRule(value: Recurrence | null): string | null {
  if (!value) return null
  if (!Number.isInteger(value.interval) || value.interval < 1 || value.interval > 366) throw new Error('invalid interval')
  const parts = [`FREQ=${value.frequency}`, `INTERVAL=${value.interval}`]
  if (value.frequency === 'WEEKLY' && value.weekdays?.length) parts.push(`BYDAY=${value.weekdays.join(',')}`)
  if (value.frequency === 'MONTHLY' && value.monthday !== undefined) {
    const day = value.monthday === 'last' ? -1 : value.monthday
    if (!Number.isInteger(day) || (day !== -1 && (day < 1 || day > 31))) throw new Error('invalid monthday')
    parts.push(`BYMONTHDAY=${day}`)
  }
  if (value.end?.kind === 'count') {
    if (!Number.isInteger(value.end.count) || value.end.count < 1 || value.end.count > 10000) throw new Error('invalid count')
    parts.push(`COUNT=${value.end.count}`)
  } else if (value.end?.kind === 'until') {
    // A timed UNTIL must be resolved with the selected zone by the caller.
    if (!/^\d{8}(T\d{6}Z)?$/.test(value.end.value)) throw new Error('invalid until')
    parts.push(`UNTIL=${value.end.value}`)
  }
  return parts.join(';')
}

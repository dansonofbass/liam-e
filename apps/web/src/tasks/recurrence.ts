// Serialize structured choices only; the server remains responsible for recurrence expansion.
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

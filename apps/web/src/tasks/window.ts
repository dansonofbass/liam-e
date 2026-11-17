// A bounded server window leaves room for overdue tasks and the next 30 days.
export function taskWindow(now = new Date(), page = 0) {
  now = new Date(now.getFullYear(), now.getMonth(), now.getDate() + page * 300)
  const shift = (days: number) => {
    const date = new Date(Date.UTC(now.getFullYear(), now.getMonth(), now.getDate() + days))
    return date.toISOString().slice(0, 10)
  }
  return { due_from: shift(-335), due_to: shift(30) }
}

export function localToday(zone: string | null, now = new Date()): string {
  try { return new Intl.DateTimeFormat('en-CA', { timeZone: zone || 'UTC', year: 'numeric', month: '2-digit', day: '2-digit' }).format(now) }
  catch { return new Intl.DateTimeFormat('en-CA', { timeZone: 'UTC', year: 'numeric', month: '2-digit', day: '2-digit' }).format(now) }
}

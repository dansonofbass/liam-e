import { de } from '../i18n/de'
import { formatDeadline } from '../i18n/format'

export function formatTaskDue(value: string): string {
  const [date, time] = value.split('T')
  return `${formatDeadline(date!)}${time ? ` · ${time.slice(0, 5)}` : ''}`
}
export function formatTaskRule(rule: string | null | undefined): string {
  if (!rule) return de.tasks.none
  const parts = Object.fromEntries(rule.split(';').map(part => part.split('=')))
  if (Object.keys(parts).some(key => !['FREQ', 'INTERVAL'].includes(key)) || (parts.INTERVAL && parts.INTERVAL !== '1')) return de.tasks.custom
  return parts.FREQ === 'DAILY' ? de.tasks.daily : parts.FREQ === 'WEEKLY' ? de.tasks.weekly : parts.FREQ === 'MONTHLY' ? de.tasks.monthly : de.tasks.custom
}

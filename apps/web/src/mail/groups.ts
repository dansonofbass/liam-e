import type { MessageListItemOut } from '../api/generated/types.gen'
import { de } from '../i18n/de'

export function groupByDay(items: MessageListItemOut[], now: Date, timeZone = Intl.DateTimeFormat().resolvedOptions().timeZone) {
  const formatter = new Intl.DateTimeFormat('en-CA', { timeZone, year: 'numeric', month: '2-digit', day: '2-digit' })
  const day = (date: Date) => {
    const parts = formatter.formatToParts(date)
    const value = (type: string) => Number(parts.find(part => part.type === type)?.value)
    return Math.floor(Date.UTC(value('year'), value('month') - 1, value('day')) / 86400000)
  }
  const today = day(now)
  const monday = today - ((new Date(today * 86400000).getUTCDay() + 6) % 7)
  const groups = [
    { label: de.inbox.groups.today, items: [] as MessageListItemOut[] },
    { label: de.inbox.groups.yesterday, items: [] as MessageListItemOut[] },
    { label: de.inbox.groups.week, items: [] as MessageListItemOut[] },
    { label: de.inbox.groups.older, items: [] as MessageListItemOut[] },
  ] as const
  for (const item of items) {
    const date = item.internal_date ? day(new Date(item.internal_date)) : null
    const index = date === today ? 0 : date === today - 1 ? 1 : date !== null && date >= monday ? 2 : 3
    groups[index].items.push(item)
  }
  return groups.filter(group => group.items.length > 0)
}

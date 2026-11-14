import { expect, test } from 'bun:test'
import type { MessageListItemOut } from '../api/generated/types.gen'
import { groupByDay } from './groups'

const item = (id: string, internal_date: string | null) => ({ id, internal_date }) as MessageListItemOut

test('groups calendar days in Berlin and preserves order', () => {
  const items = [item('today', '2026-11-13T00:05:00+01:00'), item('yesterday', '2026-11-12T23:50:00+01:00'), item('week', '2026-11-10T12:00:00+01:00'), item('old', '2026-11-08T12:00:00+01:00'), item('null', null)] as const
  expect(groupByDay([...items], new Date('2026-11-13T00:10:00+01:00'), 'Europe/Berlin')).toEqual([
    { label: 'Heute', items: [items[0]] }, { label: 'Gestern', items: [items[1]] },
    { label: 'Diese Woche', items: [items[2]] }, { label: 'Älter', items: [items[3], items[4]] },
  ])
})

test('Sunday is yesterday on Monday, not an older week', () => {
  const sunday = item('sunday', '2026-11-08T23:50:00+01:00')
  expect(groupByDay([sunday], new Date('2026-11-09T00:10:00+01:00'), 'Europe/Berlin')).toEqual([{ label: 'Gestern', items: [sunday] }])
})

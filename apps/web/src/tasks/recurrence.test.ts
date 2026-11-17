import { describe, expect, test } from 'bun:test'
import { recurrenceRule } from './recurrence'

describe('recurrenceRule', () => {
  test('distinguishes the 31st from the last day', () => {
    expect(recurrenceRule({ frequency: 'MONTHLY', interval: 1, monthday: 31 })).toBe('FREQ=MONTHLY;INTERVAL=1;BYMONTHDAY=31')
    expect(recurrenceRule({ frequency: 'MONTHLY', interval: 1, monthday: 'last' })).toBe('FREQ=MONTHLY;INTERVAL=1;BYMONTHDAY=-1')
  })
  test('serializes structured weekdays and a count', () => {
    expect(recurrenceRule({ frequency: 'WEEKLY', interval: 2, weekdays: ['MO', 'FR'], end: { kind: 'count', count: 5 } })).toBe('FREQ=WEEKLY;INTERVAL=2;BYDAY=MO,FR;COUNT=5')
  })
  test('rejects values outside server limits', () => {
    expect(() => recurrenceRule({ frequency: 'DAILY', interval: 0 })).toThrow()
    expect(() => recurrenceRule({ frequency: 'DAILY', interval: 1, end: { kind: 'count', count: 10001 } })).toThrow()
  })
})

import { expect, test } from 'bun:test'
import { todayLocal } from './state'
import { parseSearch } from './url'

test('invalid search values use responsive defaults and today', () => {
  expect(parseSearch({ view: 'x', date: '2026-02-30' }, true)).toEqual({ view: 'day', date: todayLocal() })
  expect(parseSearch({}, false)).toEqual({ view: 'week', date: todayLocal() })
  expect(parseSearch({ view: 'month', date: '2026-11-18' }, false)).toEqual({ view: 'month', date: '2026-11-18' })
})

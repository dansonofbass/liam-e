import { expect, test } from 'bun:test'
import type { Query } from '@tanstack/react-query'
import type { MailSummaryOut } from './generated/types.gen'
import { SUMMARY_IDLE_POLL_MS, SUMMARY_SYNCING_POLL_MS, summaryQuery } from './queries'

const interval = summaryQuery().refetchInterval as unknown as (query: Query<MailSummaryOut>) => number | false
const withAccounts = (states: string[] | null) => ({ state: { data: states === null ? undefined : { accounts: states.map((state, i) => ({ id: String(i), state })), unread_total: 0, last_sync_at: null } } }) as unknown as Query<MailSummaryOut>

test('summary polls fast while an account syncs', () => {
  expect(interval(withAccounts(['ok', 'syncing']))).toBe(SUMMARY_SYNCING_POLL_MS)
})

test('summary keeps a slow poll while every account is idle', () => {
  expect(interval(withAccounts(['ok', 'ok']))).toBe(SUMMARY_IDLE_POLL_MS)
  expect(interval(withAccounts([]))).toBe(SUMMARY_IDLE_POLL_MS)
  expect(SUMMARY_IDLE_POLL_MS).toBeGreaterThan(SUMMARY_SYNCING_POLL_MS)
})

test('summary does not poll before the first answer', () => {
  expect(interval(withAccounts(null))).toBe(false)
})

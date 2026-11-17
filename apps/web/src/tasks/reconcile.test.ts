import { describe, expect, test } from 'bun:test'
import type { ReconcileIn, ReconcileOut } from '../api/generated/types.gen'
import { reconcileTask } from './reconcile'

const result = (cursor: string, complete: boolean): ReconcileOut => ({ revision_id: 'revision', cursor, complete, target: '2027-01-01T00:00:00Z' })

describe('bounded task reconciliation', () => {
  test('continues pages with the server cursor without starting a new horizon', async () => {
    const calls: ReconcileIn[] = []
    const values = [result('a', false), result('b', false), result('c', true)]
    const final = await reconcileTask('series', { request: async body => { calls.push(body); return values[calls.length - 1]! } })
    expect(final?.cursor).toBe('c')
    expect(calls.map(c => c.cursor)).toEqual([undefined, 'a', 'b'])
    expect(calls.some(c => c.advance)).toBe(false)
  })
  test('advances a previously completed horizon only once', async () => {
    const calls: ReconcileIn[] = []
    const values = [result('a', true), result('b', false), result('c', true)]
    await reconcileTask('series', { request: async body => { calls.push(body); return values[calls.length - 1]! } })
    expect(calls.map(c => !!c.advance)).toEqual([false, true, false])
  })
  test('bounds work and resumes without a client cursor after interruption', async () => {
    const calls: ReconcileIn[] = []
    const request = async (body: ReconcileIn) => { calls.push(body); return result(String(calls.length), false) }
    expect((await reconcileTask('series', { maxPages: 2, request }))?.complete).toBe(false)
    await reconcileTask('series', { maxPages: 1, request })
    expect(calls).toHaveLength(3)
    expect(calls[2]!.cursor).toBeUndefined()
  })
  test('does not replay failed writes', async () => {
    let calls = 0
    await expect(reconcileTask('series', { request: async () => { calls++; throw new Error('offline') } })).rejects.toThrow()
    expect(calls).toBe(1)
  })
})

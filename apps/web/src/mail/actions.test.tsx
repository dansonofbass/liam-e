import { afterEach, expect, mock, spyOn, test } from 'bun:test'
import { QueryClient, QueryClientProvider, useQuery, type InfiniteData } from '@tanstack/react-query'
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import * as sdk from '../api/generated/sdk.gen'
import type { MessageListItemOut, MessagePageOut } from '../api/generated/types.gen'
import { useMailActions, type Clock } from './useMailActions'

const originalMatchMedia = window.matchMedia
const rows = ['Erste', 'Zweite'].map((subject, i) => ({ id: String(i + 1), subject, is_read: false }) as MessageListItemOut)
const key = ['messages', {}]
function makeClock() {
  let now = 0, next = 0
  const timers = new Map<number, { fn: () => void; at: number }>()
  const clock: Clock = { now: () => now, setTimeout: (fn, ms) => { const id = ++next; timers.set(id, { fn, at: now + ms }); return id as unknown as ReturnType<typeof setTimeout> }, clearTimeout: id => { timers.delete(id as unknown as number) } }
  return { clock, advance(ms: number) { now += ms; for (const [id, timer] of timers) if (timer.at <= now) { timers.delete(id); timer.fn() } } }
}
function setup(mobile = false) {
  window.matchMedia = ((query: string) => ({ matches: !mobile && query.includes('1024px'), addEventListener() {}, removeEventListener() {} })) as unknown as typeof window.matchMedia
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  client.setQueryData<InfiniteData<MessagePageOut>>(key, { pages: [{ items: rows, next_cursor: null }], pageParams: [undefined] })
  const time = makeClock()
  function Harness() {
    const { data } = useQuery<InfiniteData<MessagePageOut>>({ queryKey: key, queryFn: async () => client.getQueryData<InfiniteData<MessagePageOut>>(key)!, enabled: false })
    const { run, undo, toast } = useMailActions({ clock: time.clock })
    return <><div>{data?.pages.flatMap(page => page.items).map(row => <div key={row.id}>{row.subject}:{String(row.is_read)}</div>)}</div>
      <button onClick={() => { void run('1', 'archive') }}>archive 1</button><button onClick={() => { void run('2', 'archive') }}>archive 2</button><button onClick={() => { void run('2', 'trash') }}>trash 2</button><button onClick={() => { void run('1', 'mark_read') }}>read 1</button>
      {toast && <div role="status" data-tone={toast.tone}>{toast.text}{toast.undoable && <button onClick={() => { void undo() }}>Rückgängig</button>}</div>}</>
  }
  render(<QueryClientProvider client={client}><Harness /></QueryClientProvider>)
  return { client, ...time }
}
function success() {
  return spyOn(sdk, 'mailMessageAction').mockImplementation((async (options: { path: { message_id: string } }) => ({ data: { action_id: `action-${options?.path?.message_id}`, message: rows.find(row => row.id === options?.path?.message_id) }, response: { status: 200 } })) as never)
}
afterEach(() => { cleanup(); mock.restore(); window.matchMedia = originalMatchMedia })

test('archive removes immediately and toast expires after ten seconds', async () => {
  success(); const time = setup()
  fireEvent.click(screen.getByText('archive 1'))
  await waitFor(() => expect(screen.queryByText('Erste:false')).toBeNull())
  expect(await screen.findByText('„Erste“ archiviert.')).toBeTruthy()
  act(() => time.advance(9999)); expect(screen.getByRole('status')).toBeTruthy()
  act(() => time.advance(1)); expect(screen.queryByRole('status')).toBeNull()
})

test('second action replaces toast and its timer', async () => {
  success(); const time = setup()
  fireEvent.click(screen.getByText('archive 1')); await screen.findByText('„Erste“ archiviert.')
  act(() => time.advance(5000))
  fireEvent.click(screen.getByText('trash 2')); await screen.findByText('„Zweite“ in den Papierkorb gelegt.')
  act(() => time.advance(5000)); expect(screen.getByRole('status')).toBeTruthy()
  act(() => time.advance(5000)); expect(screen.queryByRole('status')).toBeNull()
})

test('undo sends the action id and restores the row', async () => {
  success(); const undo = spyOn(sdk, 'mailActionsUndo').mockImplementation((async () => ({ data: { restored: ['action-1'], expired: [], failed: [], skipped: [] }, response: { status: 200 } })) as never)
  setup(); fireEvent.click(screen.getByText('archive 1')); fireEvent.click(await screen.findByText('Rückgängig'))
  await waitFor(() => expect(screen.getByText('Erste:false')).toBeTruthy())
  expect(undo).toHaveBeenCalledWith({ body: { action_ids: ['action-1'] } })
  expect(screen.queryByRole('status')).toBeNull()
})

for (const replacement of ['new action', 'timeout']) {
  test(`successful pending undo restores its row after ${replacement}`, async () => {
    success()
    let finishUndo!: (value: unknown) => void
    spyOn(sdk, 'mailActionsUndo').mockImplementation((() => new Promise(resolve => { finishUndo = resolve })) as never)
    const { client, advance } = setup()
    fireEvent.click(screen.getByText('archive 1'))
    fireEvent.click(await screen.findByText('Rückgängig'))
    if (replacement === 'new action') {
      fireEvent.click(screen.getByText('archive 2'))
      await screen.findByText('„Zweite“ archiviert.')
    } else {
      act(() => advance(10_000))
      expect(screen.queryByRole('status')).toBeNull()
    }
    const invalidate = spyOn(client, 'invalidateQueries')
    await act(async () => { finishUndo({ data: { restored: ['action-1'] }, response: { status: 200 } }) })
    await waitFor(() => expect(screen.getByText('Erste:false')).toBeTruthy())
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ['messages'] })
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ['summary'] })
    if (replacement === 'new action') {
      expect(screen.queryByText('Zweite:false')).toBeNull()
      expect(screen.getByText('„Zweite“ archiviert.')).toBeTruthy()
      expect(screen.getByText('Rückgängig')).toBeTruthy()
    } else expect(screen.queryByRole('status')).toBeNull()
  })
}

for (const [status, text, removed] of [[502, 'Das hat beim Anbieter nicht geklappt. Die Mail ist unverändert.', false], [409, 'Das geht bei diesem Konto nicht.', false], [404, 'Die Mail ist nicht mehr da.', true]] as const) {
  test(`${status} shows a danger notice and ${removed ? 'keeps removal' : 'restores the row'}`, async () => {
    spyOn(sdk, 'mailMessageAction').mockImplementation((async () => ({ error: { detail: { code: status === 409 ? 'action_unsupported' : status === 404 ? 'message_not_found' : 'provider_failed' } }, response: { status } })) as never)
    setup(); fireEvent.click(screen.getByText('archive 1'))
    expect((await screen.findByRole('status')).getAttribute('data-tone')).toBe('danger')
    expect(screen.getByText(text)).toBeTruthy()
    expect(Boolean(screen.queryByText('Erste:false'))).toBe(!removed)
  })
}

for (const first of ['archive 1', 'read 1']) {
  test(`failed ${first} rolls back without reverting a later archive`, async () => {
    let failFirst!: (value: unknown) => void
    spyOn(sdk, 'mailMessageAction').mockImplementation(((options: { path: { message_id: string } }) => options.path.message_id === '1'
      ? new Promise(resolve => { failFirst = resolve })
      : Promise.resolve({ data: { action_id: 'action-2', message: rows[1] }, response: { status: 200 } })) as never)
    const { client } = setup()
    fireEvent.click(screen.getByText(first))
    await waitFor(() => expect(failFirst).toBeDefined())
    fireEvent.click(screen.getByText('archive 2'))
    await screen.findByText('„Zweite“ archiviert.')
    await act(async () => { failFirst({ response: { status: 502 } }) })
    await waitFor(() => expect(screen.getByText('Erste:false')).toBeTruthy())
    expect(screen.queryByText('Zweite:false')).toBeNull()
    expect(screen.getByText('„Zweite“ archiviert.')).toBeTruthy()
    expect(client.getQueryState(key)?.isInvalidated).toBe(true)
  })
}

test('mobile uses the short success text', async () => {
  success(); setup(true); fireEvent.click(screen.getByText('archive 1'))
  expect(await screen.findByText('Mail archiviert.')).toBeTruthy()
})

test('failed undo shows a danger notice without restoring the row', async () => {
  success()
  spyOn(sdk, 'mailActionsUndo').mockImplementation((async () => ({ data: { restored: [], expired: ['action-1'], failed: [], skipped: [] }, response: { status: 200 } })) as never)
  setup(); fireEvent.click(screen.getByText('archive 1')); fireEvent.click(await screen.findByText('Rückgängig'))
  expect(await screen.findByText('Das hat nicht geklappt. Versuch es gleich noch mal.')).toBeTruthy()
  expect(screen.getByRole('status').getAttribute('data-tone')).toBe('danger')
  expect(screen.queryByText('Erste:false')).toBeNull()
})

test('mark_read updates the row in place without a toast', async () => {
  success(); setup(); fireEvent.click(screen.getByText('read 1'))
  await waitFor(() => expect(screen.getByText('Erste:true')).toBeTruthy())
  expect(screen.queryByRole('status')).toBeNull()
})

import { afterEach, expect, mock, spyOn, test } from 'bun:test'
import { QueryClient, QueryClientProvider, useQuery } from '@tanstack/react-query'
import { createMemoryHistory, createRootRoute, createRouter, RouterProvider } from '@tanstack/react-router'
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import * as sdk from '../api/generated/sdk.gen'
import type { ChatMessageOut, ProposalResult } from '../api/generated/types.gen'
import { ProposalCard } from './ProposalCard'

function message(status = 'pending', result?: ProposalResult): ChatMessageOut {
  return { id: 'p', conversation_id: 'c', role: 'proposal', content: '', tool_name: '', created_at: '', extras: {}, stopped: false, proposal_status: status, proposal: { kind: 'unsubscribe', reason: 'Nicht mehr gelesen.', items: [{ id: 'a', kind: 'sender', title: 'Alpha', subtitle: '12 Mails', method: 'post' }, { id: 'b', kind: 'sender', title: 'Beta', subtitle: '2 Mails', method: 'manual' }], result } }
}
function setup(initial: ChatMessageOut, clock?: { now: () => number; setTimeout: (fn: () => void, ms: number) => ReturnType<typeof setTimeout>; clearTimeout: (id: ReturnType<typeof setTimeout>) => void }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } })
  client.setQueryData(['history', 'c'], [initial])
  function Page() {
    const { data } = useQuery({ queryKey: ['history', 'c'], queryFn: async () => client.getQueryData<ChatMessageOut[]>(['history', 'c']) ?? [], staleTime: Infinity })
    return <ProposalCard message={data![0]!} clock={clock} />
  }
  const root = createRootRoute({ component: Page })
  const router = createRouter({ routeTree: root, history: createMemoryHistory({ initialEntries: ['/'] }) })
  render(<QueryClientProvider client={client}><RouterProvider router={router} /></QueryClientProvider>)
  return client
}
afterEach(() => { cleanup(); mock.restore() })

test('confirmation submits selected ids and replaces the card in history', async () => {
  const done = message('done', { done: 1, undo_action_ids: ['u'] })
  const confirm = spyOn(sdk, 'chatProposalConfirm').mockImplementation((async () => ({ data: done })) as never)
  const client = setup(message())
  expect(await screen.findByText('2 Newsletter abbestellen?')).toBeTruthy()
  expect(screen.getByText('2 Mails · nur über den Link im Newsletter')).toBeTruthy()
  fireEvent.click(screen.getByRole('checkbox', { name: /Beta/ }))
  fireEvent.click(screen.getByRole('button', { name: '1 abbestellen und archivieren' }))
  await waitFor(() => expect(confirm).toHaveBeenCalledWith({ path: { proposal_id: 'p' }, body: { selected_ids: ['a'], body: undefined }, throwOnError: true }))
  expect(await screen.findByText('1 Newsletter abbestellt, 1 Mail archiviert.')).toBeTruthy()
  expect(screen.queryByRole('checkbox')).toBeNull()
  expect(client.getQueryData<ChatMessageOut[]>(['history', 'c'])?.[0]?.proposal_status).toBe('done')
})

test('cancelled proposal is quiet', async () => {
  setup(message('cancelled'))
  expect(await screen.findByText('Abgebrochen, es wurde nichts geändert.')).toBeTruthy()
})

test('cancelling uses the SDK and invalidates history and summary', async () => {
  const cancel = spyOn(sdk, 'chatProposalCancel').mockImplementation((async () => ({ data: message('cancelled') })) as never)
  const client = setup(message())
  const invalidate = spyOn(client, 'invalidateQueries')
  fireEvent.click(await screen.findByRole('button', { name: 'Abbrechen' }))
  expect(await screen.findByText('Abgebrochen, es wurde nichts geändert.')).toBeTruthy()
  expect(cancel).toHaveBeenCalledWith({ path: { proposal_id: 'p' }, throwOnError: true })
  expect(invalidate).toHaveBeenCalledWith({ queryKey: ['history', 'c'] })
  expect(invalidate).toHaveBeenCalledWith({ queryKey: ['summary'] })
})

test('undo sends all action ids and the notice changes', async () => {
  const undo = spyOn(sdk, 'mailActionsUndo').mockImplementation((async () => ({ data: { restored: ['u', 'v'], skipped: [], expired: [], failed: [] } })) as never)
  setup(message('done', { done: 2, undo_action_ids: ['u', 'v'] }))
  fireEvent.click(await screen.findByRole('button', { name: 'Rückgängig' }))
  await waitFor(() => expect(undo).toHaveBeenCalledWith({ body: { action_ids: ['u', 'v'] }, throwOnError: true }))
  expect(await screen.findByText('Rückgängig gemacht.')).toBeTruthy()
  expect(screen.queryByRole('button', { name: 'Rückgängig' })).toBeNull()
})

test('undo expires after ten seconds without waiting in real time', async () => {
  let callback = () => {}, delay = 0, now = 0
  const clock = { now: () => now, setTimeout: (fn: () => void, ms: number) => { callback = fn; delay = ms; return 1 as unknown as ReturnType<typeof setTimeout> }, clearTimeout: () => {} }
  setup(message('done', { done: 1, undo_action_ids: ['u'] }), clock)
  expect(await screen.findByRole('button', { name: 'Rückgängig' })).toBeTruthy()
  expect(delay).toBe(10000)
  act(() => { now = 10000; callback() })
  expect(screen.queryByRole('button', { name: 'Rückgängig' })).toBeNull()
})

test('a delayed timer cannot permit undo after the deadline', async () => {
  let now = 0
  const clock = { now: () => now, setTimeout: () => 1 as unknown as ReturnType<typeof setTimeout>, clearTimeout: () => {} }
  const undo = spyOn(sdk, 'mailActionsUndo').mockImplementation((async () => ({ data: {} })) as never)
  setup(message('done', { done: 1, undo_action_ids: ['u'] }), clock)
  const button = await screen.findByRole('button', { name: 'Rückgängig' })
  now = 10001
  fireEvent.click(button)
  expect(undo).not.toHaveBeenCalled()
})

test('remounting a result does not extend the undo deadline', async () => {
  let now = 0, delay = 0
  const clock = { now: () => now, setTimeout: (_fn: () => void, ms: number) => { delay = ms; return 1 as unknown as ReturnType<typeof setTimeout> }, clearTimeout: () => {} }
  const done = message('done', { done: 1, undo_action_ids: ['u'] })
  const client = setup(done, clock)
  await screen.findByRole('button', { name: 'Rückgängig' })
  expect(delay).toBe(10000)
  act(() => { client.setQueryData(['history', 'c'], [message('pending')]) })
  await screen.findByText('2 Newsletter abbestellen?')
  now = 5000
  act(() => { client.setQueryData(['history', 'c'], [done]) })
  await screen.findByRole('button', { name: 'Rückgängig' })
  expect(delay).toBe(5000)
})

test.each([
  ['item_gone', 'Die Mail ist nicht mehr da.'],
  ['action_unsupported', 'Das geht bei diesem Konto nicht.'],
  ['credentials_invalid', 'Die Anmeldung ist abgelaufen. Melde dich erneut beim Anbieter an.'],
  ['host_not_allowed', 'Der Server ist nicht erreichbar. Prüfe die Serveradresse.'],
  ['unknown', 'Das hat nicht geklappt. Versuch es gleich noch mal.'],
])('failure %s shows its mapped cause', async (code, text) => {
  setup(message('failed', { failed: [{ id: 'a', code }] }))
  expect(await screen.findByText(text)).toBeTruthy()
})

test('a send draft is editable and the edited body is confirmed', async () => {
  const initial = message()
  initial.proposal = { kind: 'send', reason: 'Antwort.', irreversible: true, items: [{ id: 'a', kind: 'mail', title: 'Antwort', subtitle: 'An Anna' }], draft: { account_id: 'a', body: 'Erster Text', cc: [], mode: 'new', quote: '', reply_to_message_id: null, subject: 'Hallo', to: ['anna@example.org'] } }
  const confirm = spyOn(sdk, 'chatProposalConfirm').mockImplementation((async () => ({ data: { ...initial, proposal_status: 'done', proposal: { ...initial.proposal!, result: { done: 1 } } } })) as never)
  setup(initial)
  expect(await screen.findByText('Gesendete Mails lassen sich nicht zurückholen.')).toBeTruthy()
  fireEvent.change(screen.getByLabelText('Entwurf'), { target: { value: 'Neuer Text' } })
  fireEvent.click(screen.getByRole('button', { name: 'Senden' }))
  await waitFor(() => expect(confirm).toHaveBeenCalledWith({ path: { proposal_id: 'p' }, body: { selected_ids: ['a'], body: 'Neuer Text' }, throwOnError: true }))
  expect(await screen.findByText('Mail gesendet.')).toBeTruthy()
})

test.each([1, 2])('partial result uses the correct form for %i failures', async (count) => {
  setup(message('partial', { done: 1, failed: Array.from({ length: count }, (_, i) => ({ id: String(i), code: 'item_gone' })) }))
  const ending = count === 1 ? '1 ließ sich nicht ändern.' : '2 ließen sich nicht ändern.'
  expect(await screen.findByText(`1 Newsletter abbestellt. ${ending}`)).toBeTruthy()
})

test('unsubscribe without archived mail and unsafe manual link', async () => {
  setup(message('partial', { done: 1, failed: [], manual: [{ id: 'a', link: 'javascript:alert(1)' }, { id: 'b', link: 'https://example.org/unsubscribe' }], undo_action_ids: [] }))
  expect(await screen.findByText('1 Newsletter abbestellt. 0 ließen sich nicht ändern.')).toBeTruthy()
  const links = screen.getAllByRole('link', { name: 'Abmeldeseite öffnen' })
  expect(links).toHaveLength(1)
  expect(links[0]?.getAttribute('href')).toBe('https://example.org/unsubscribe')
  expect(links[0]?.getAttribute('rel')).toBe('noopener noreferrer')
})

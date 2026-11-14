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
function setup(initial: ChatMessageOut, clock?: { now: () => number; setTimeout: (fn: () => void, ms: number) => ReturnType<typeof setTimeout>; clearTimeout: (id: ReturnType<typeof setTimeout>) => void }, loadHistory?: () => Promise<ChatMessageOut[]>) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } })
  client.setQueryData(['history', 'c'], [initial])
  function Page() {
    const { data } = useQuery({ queryKey: ['history', 'c'], queryFn: loadHistory ?? (async () => client.getQueryData<ChatMessageOut[]>(['history', 'c']) ?? []), staleTime: Infinity })
    return <ProposalCard message={data![0]!} clock={clock} />
  }
  const root = createRootRoute({ component: Page })
  const router = createRouter({ routeTree: root, history: createMemoryHistory({ initialEntries: ['/'] }) })
  render(<QueryClientProvider client={client}><RouterProvider router={router} /></QueryClientProvider>)
  return client
}
afterEach(() => { cleanup(); mock.restore() })

async function setupConfirmed(done: ChatMessageOut, clock?: Parameters<typeof setup>[1]) {
  spyOn(sdk, 'chatProposalConfirm').mockImplementation((async () => ({ data: done })) as never)
  const client = setup(message(), clock)
  fireEvent.click(await screen.findByRole('button', { name: '2 abbestellen und archivieren' }))
  await screen.findByRole('button', { name: 'Rückgängig' })
  return client
}

test('confirmation submits selected ids and replaces the card in history', async () => {
  const done = message('done', { done: 1, undo_action_ids: ['u'] })
  const confirm = spyOn(sdk, 'chatProposalConfirm').mockImplementation((async () => ({ data: done })) as never)
  const client = setup(message())
  const invalidate = spyOn(client, 'invalidateQueries')
  expect(await screen.findByText('2 Newsletter abbestellen?')).toBeTruthy()
  expect(screen.getByText('2 Mails · nur über den Link im Newsletter')).toBeTruthy()
  fireEvent.click(screen.getByRole('checkbox', { name: /Beta/ }))
  fireEvent.click(screen.getByRole('button', { name: '1 abbestellen und archivieren' }))
  await waitFor(() => expect(confirm).toHaveBeenCalledWith({ path: { proposal_id: 'p' }, body: { selected_ids: ['a'], body: undefined }, throwOnError: true }))
  expect(await screen.findByText('1 Newsletter abbestellt, 1 Mail archiviert.')).toBeTruthy()
  expect(screen.queryByRole('checkbox')).toBeNull()
  expect(client.getQueryData<ChatMessageOut[]>(['history', 'c'])?.[0]?.proposal_status).toBe('done')
  expect(invalidate).toHaveBeenCalledWith({ queryKey: ['messages'] })
  expect(invalidate).toHaveBeenCalledWith({ queryKey: ['message'] })
})

test('selection survives a card remount and confirmation', async () => {
  const initial = message()
  const confirm = spyOn(sdk, 'chatProposalConfirm').mockImplementation((async () => ({ data: message('done', { done: 1 }) })) as never)
  const client = new QueryClient()
  const card = () => <QueryClientProvider client={client}><ProposalCard message={initial} /></QueryClientProvider>
  const view = render(card())
  fireEvent.click(screen.getByRole('checkbox', { name: /Beta/ }))
  view.unmount()
  render(card())
  expect((screen.getByRole('checkbox', { name: /Beta/ }) as HTMLInputElement).checked).toBe(false)
  fireEvent.click(screen.getByRole('button', { name: '1 abbestellen und archivieren' }))
  await waitFor(() => expect(confirm).toHaveBeenCalledWith({ path: { proposal_id: 'p' }, body: { selected_ids: ['a'], body: undefined }, throwOnError: true }))
})

test('edited draft survives a card remount and confirmation', async () => {
  const initial = message()
  initial.proposal = { kind: 'send', reason: 'Antwort.', items: [], draft: { account_id: 'a', body: 'Erster Text', cc: [], mode: 'new', quote: '', reply_to_message_id: null, subject: 'Hallo', to: ['anna@example.org'] } }
  const confirm = spyOn(sdk, 'chatProposalConfirm').mockImplementation((async () => ({ data: { ...initial, proposal_status: 'done' } })) as never)
  const client = new QueryClient()
  const card = () => <QueryClientProvider client={client}><ProposalCard message={initial} /></QueryClientProvider>
  const view = render(card())
  fireEvent.change(screen.getByLabelText('Entwurf'), { target: { value: 'Neuer Text' } })
  view.unmount()
  render(card())
  expect((screen.getByLabelText('Entwurf') as HTMLTextAreaElement).value).toBe('Neuer Text')
  fireEvent.click(screen.getByRole('button', { name: 'Senden' }))
  await waitFor(() => expect(confirm).toHaveBeenCalledWith({ path: { proposal_id: 'p' }, body: { selected_ids: [], body: 'Neuer Text' }, throwOnError: true }))
})

test('running proposal refreshes history at most twenty times and clears its timer', () => {
  let next = 0
  const timers = new Map<number, () => void>()
  const clock = { now: () => 0, setTimeout: (fn: () => void, ms: number) => { expect(ms).toBe(3000); const id = ++next; timers.set(id, fn); return id as unknown as ReturnType<typeof setTimeout> }, clearTimeout: (id: ReturnType<typeof setTimeout>) => { timers.delete(id as unknown as number) } }
  const client = new QueryClient()
  const invalidate = spyOn(client, 'invalidateQueries')
  const card = (row: ChatMessageOut) => <QueryClientProvider client={client}><ProposalCard message={row} clock={clock} /></QueryClientProvider>
  const view = render(card(message('running')))
  expect(screen.getByText('Wird ausgeführt …').className).toBe('le-hint')
  for (let i = 0; i < 20; i++) {
    expect(timers.size).toBe(1)
    const [id, callback] = [...timers.entries()][0]!
    timers.delete(id)
    act(callback)
  }
  expect(invalidate).toHaveBeenCalledTimes(20)
  expect(invalidate).toHaveBeenCalledWith({ queryKey: ['history', 'c'] })
  expect(timers.size).toBe(0)
  view.unmount()
  const second = render(card(message('running')))
  expect(timers.size).toBe(1)
  second.unmount()
  expect(timers.size).toBe(0)
})

test('running confirmation yields to the completed history row and stops polling', async () => {
  let next = 0
  const timers = new Map<number, number>()
  const clock = { now: () => 0, setTimeout: (_fn: () => void, ms: number) => { const id = ++next; timers.set(id, ms); return id as unknown as ReturnType<typeof setTimeout> }, clearTimeout: (id: ReturnType<typeof setTimeout>) => { timers.delete(id as unknown as number) } }
  spyOn(sdk, 'chatProposalConfirm').mockImplementation((async () => ({ data: message('running') })) as never)
  const client = new QueryClient()
  const card = (row: ChatMessageOut) => <QueryClientProvider client={client}><ProposalCard message={row} clock={clock} /></QueryClientProvider>
  const view = render(card(message()))
  fireEvent.click(screen.getByRole('button', { name: '2 abbestellen und archivieren' }))
  expect(await screen.findByText('Wird ausgeführt …')).toBeTruthy()
  expect([...timers.values()]).toContain(3000)
  view.rerender(card(message('done', { done: 1 })))
  expect(screen.getByText('1 Newsletter abbestellt.')).toBeTruthy()
  expect([...timers.values()]).not.toContain(3000)
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
  const client = await setupConfirmed(message('done', { done: 2, undo_action_ids: ['u', 'v'] }))
  const invalidate = spyOn(client, 'invalidateQueries')
  fireEvent.click(await screen.findByRole('button', { name: 'Rückgängig' }))
  await waitFor(() => expect(undo).toHaveBeenCalledWith({ body: { action_ids: ['u', 'v'] }, throwOnError: true }))
  expect(await screen.findByText('Rückgängig gemacht.')).toBeTruthy()
  expect(screen.queryByRole('button', { name: 'Rückgängig' })).toBeNull()
  expect(invalidate).toHaveBeenCalledWith({ queryKey: ['messages'] })
  expect(invalidate).toHaveBeenCalledWith({ queryKey: ['message'] })
})

test('failed undo also invalidates inbox queries', async () => {
  spyOn(sdk, 'mailActionsUndo').mockImplementation((async () => { throw new Error('network') }) as never)
  const client = await setupConfirmed(message('done', { done: 1, undo_action_ids: ['u'] }))
  const invalidate = spyOn(client, 'invalidateQueries')
  fireEvent.click(await screen.findByRole('button', { name: 'Rückgängig' }))
  await screen.findByText('Das hat nicht geklappt. Versuch es gleich noch mal.')
  expect(invalidate).toHaveBeenCalledWith({ queryKey: ['messages'] })
  expect(invalidate).toHaveBeenCalledWith({ queryKey: ['message'] })
})

test('undo expires after ten seconds without waiting in real time', async () => {
  let callback = () => {}, delay = 0, now = 0
  const clock = { now: () => now, setTimeout: (fn: () => void, ms: number) => { callback = fn; delay = ms; return 1 as unknown as ReturnType<typeof setTimeout> }, clearTimeout: () => {} }
  await setupConfirmed(message('done', { done: 1, undo_action_ids: ['u'] }), clock)
  expect(await screen.findByRole('button', { name: 'Rückgängig' })).toBeTruthy()
  expect(delay).toBe(10000)
  act(() => { now = 10000; callback() })
  expect(screen.queryByRole('button', { name: 'Rückgängig' })).toBeNull()
})

test('a delayed timer cannot permit undo after the deadline', async () => {
  let now = 0
  const clock = { now: () => now, setTimeout: () => 1 as unknown as ReturnType<typeof setTimeout>, clearTimeout: () => {} }
  const undo = spyOn(sdk, 'mailActionsUndo').mockImplementation((async () => ({ data: {} })) as never)
  await setupConfirmed(message('done', { done: 1, undo_action_ids: ['u'] }), clock)
  const button = await screen.findByRole('button', { name: 'Rückgängig' })
  now = 10001
  fireEvent.click(button)
  expect(undo).not.toHaveBeenCalled()
})

test.each(['done', 'partial'])('a %s history card has no undo without a local confirmation', async status => {
  setup(message(status, { done: 1, undo_action_ids: ['u'] }))
  expect(await screen.findByText('1 Newsletter abbestellt, 1 Mail archiviert.')).toBeTruthy()
  expect(screen.queryByRole('button', { name: 'Rückgängig' })).toBeNull()
})

test('remounting a confirmed result does not extend the undo deadline', async () => {
  let now = 0, delay = 0
  const clock = { now: () => now, setTimeout: (_fn: () => void, ms: number) => { delay = ms; return 1 as unknown as ReturnType<typeof setTimeout> }, clearTimeout: () => {} }
  const done = message('done', { done: 1, undo_action_ids: ['u'] })
  spyOn(sdk, 'chatProposalConfirm').mockImplementation((async () => ({ data: done })) as never)
  const client = new QueryClient()
  const card = (row: ChatMessageOut) => <QueryClientProvider client={client}><ProposalCard message={row} clock={clock} /></QueryClientProvider>
  const view = render(card(message()))
  fireEvent.click(screen.getByRole('button', { name: '2 abbestellen und archivieren' }))
  await screen.findByRole('button', { name: 'Rückgängig' })
  expect(delay).toBe(10000)
  view.unmount()
  now = 5000
  render(card(done))
  await screen.findByRole('button', { name: 'Rückgängig' })
  expect(delay).toBe(5000)
})

test.each([
  ['item_gone', 'Diesen Absender gibt es in deinen Mails nicht mehr.'],
  ['item_changed', 'Der Absender hat seinen Abmeldeweg geändert. Lass dir einen neuen Vorschlag machen.'],
  ['action_unsupported', 'Das geht bei dieser Mail nicht.'],
  ['credentials_invalid', 'Die Mail wurde nicht gesendet, weil die Anmeldung für dieses Konto nicht mehr gilt. Melde dich unter Konten erneut an.'],
  ['send_failed', 'Die Mail wurde nicht gesendet. Der Anbieter hat sie nicht angenommen. Versuch es gleich noch mal.'],
  ['account_gone', 'Die Mail wurde nicht gesendet, weil das Konto nicht mehr verbunden ist.'],
  ...['unsubscribe_rejected', 'unsubscribe_blocked', 'unsubscribe_unreachable', 'unsubscribe_invalid', 'unsubscribe_send_failed'].map(code => [code, 'Der Newsletter ließ sich nicht abbestellen. Öffne die Abmeldeseite im Newsletter.']),
  ['proposal_not_pending', 'Dieser Vorschlag ist schon erledigt oder abgebrochen.'],
  ['selection_empty', 'Wähle mindestens einen Eintrag aus.'],
  ['action_failed', 'Das hat nicht geklappt. Versuch es gleich noch mal.'],
  ['host_not_allowed', 'liam-e darf diesen Server nicht ansprechen. Prüfe die Serveradresse oder trag den Server in Mistral Studio unter MAIL_IMAP_ALLOWED_HOSTS ein.'],
  ['unknown', 'Das hat nicht geklappt. Versuch es gleich noch mal.'],
])('failure %s shows its mapped cause', async (code, text) => {
  setup(message('failed', { failed: [{ id: 'a', code }] }))
  expect(await screen.findByText(text)).toBeTruthy()
})

test('a failed mail item names a missing mail', async () => {
  const initial = message('failed', { failed: [{ id: 'a', code: 'item_gone' }] })
  initial.proposal = { ...initial.proposal!, kind: 'archive' }
  setup(initial)
  expect(await screen.findByText('Die Mail ist nicht mehr da.')).toBeTruthy()
})

test.each(['proposal_not_pending', 'selection_empty'])('confirmation refusal %s shows its cause', async code => {
  spyOn(sdk, 'chatProposalConfirm').mockImplementation((async () => { throw { detail: { code } } }) as never)
  setup(message())
  fireEvent.click(await screen.findByRole('button', { name: '2 abbestellen und archivieren' }))
  expect(await screen.findByText(code === 'selection_empty' ? 'Wähle mindestens einen Eintrag aus.' : 'Dieser Vorschlag ist schon erledigt oder abgebrochen.')).toBeTruthy()
})

test.each(['confirm', 'cancel'] as const)('%s conflict reloads the actual proposal state', async operation => {
  const request = operation === 'confirm' ? 'chatProposalConfirm' : 'chatProposalCancel'
  spyOn(sdk, request).mockImplementation((async () => { throw { detail: { code: 'proposal_not_pending' } } }) as never)
  let resolveHistory!: (rows: ChatMessageOut[]) => void
  const loadHistory = mock(() => new Promise<ChatMessageOut[]>(resolve => { resolveHistory = resolve }))
  const client = setup(message(), undefined, loadHistory)
  const invalidate = spyOn(client, 'invalidateQueries')
  fireEvent.click(await screen.findByRole('button', { name: operation === 'confirm' ? '2 abbestellen und archivieren' : 'Abbrechen' }))
  expect(await screen.findByText('Dieser Vorschlag ist schon erledigt oder abgebrochen.')).toBeTruthy()
  expect(invalidate).toHaveBeenCalledWith({ queryKey: ['history', 'c'] })
  expect(loadHistory).toHaveBeenCalledTimes(1)
  await act(async () => { resolveHistory([message('done', { done: 1 })]) })
  expect(await screen.findByText('1 Newsletter abbestellt.')).toBeTruthy()
  expect(screen.queryByRole('checkbox')).toBeNull()
})

test.each([
  ['archive', '1 Mail archiviert. 1 ließ sich nicht archivieren.'],
  ['trash', '1 Mail in den Papierkorb gelegt. 1 ließ sich nicht in den Papierkorb legen.'],
  ['mark_read', '1 Mail als gelesen markiert. 1 ließ sich nicht als gelesen markieren.'],
  ['send', 'Mail gesendet. 1 ließ sich nicht ändern.'],
] as const)('partial %s names the action', async (kind, text) => {
  const initial = message('partial', { done: 1, failed: [{ id: 'a', code: 'action_failed' }] })
  initial.proposal = { ...initial.proposal!, kind }
  setup(initial)
  expect(await screen.findByText(text)).toBeTruthy()
})

test('partial archive names a missing mail', async () => {
  const initial = message('partial', { done: 2, failed: [{ id: 'a', code: 'item_gone' }] })
  initial.proposal = { ...initial.proposal!, kind: 'archive' }
  setup(initial)
  expect(await screen.findByText('2 Mails archiviert. 1 Mail ist nicht mehr da.')).toBeTruthy()
})

test('partial unsubscribe separates gone, changed and other failures', async () => {
  setup(message('partial', { done: 1, failed: [{ id: 'a', code: 'item_gone' }, { id: 'b', code: 'item_changed' }, { id: 'c', code: 'action_failed' }] }))
  expect(await screen.findByText('1 Newsletter abbestellt. 1 Absender ist nicht mehr da. 1 Absender hat seinen Abmeldeweg geändert. 1 ließ sich nicht abbestellen.')).toBeTruthy()
})

test('a send draft is editable and the edited body is confirmed', async () => {
  const initial = message()
  initial.proposal = { kind: 'send', reason: 'Antwort.', irreversible: true, items: [], draft: { account_id: 'a', body: 'Erster Text', cc: [], mode: 'new', quote: '', reply_to_message_id: null, subject: 'Hallo', to: ['anna@example.org'] } }
  const confirm = spyOn(sdk, 'chatProposalConfirm').mockImplementation((async () => ({ data: { ...initial, proposal_status: 'done', proposal: { ...initial.proposal!, result: { done: 1 } } } })) as never)
  setup(initial)
  expect(await screen.findByText('Gesendete Mails lassen sich nicht zurückholen.')).toBeTruthy()
  fireEvent.change(screen.getByLabelText('Entwurf'), { target: { value: 'Neuer Text' } })
  fireEvent.click(screen.getByRole('button', { name: 'Senden' }))
  await waitFor(() => expect(confirm).toHaveBeenCalledWith({ path: { proposal_id: 'p' }, body: { selected_ids: [], body: 'Neuer Text' }, throwOnError: true }))
  expect(await screen.findByText('Mail gesendet.')).toBeTruthy()
})

test('a reply-all draft shows every recipient and the quoted mail before sending', async () => {
  const initial = message()
  initial.proposal = { kind: 'send', reason: 'Antwort an alle: anna@example.org.', irreversible: true, items: [], draft: { account_id: 'a', body: 'Danke', cc: ['ben@example.org', 'cara@example.org'], mode: 'reply_all', quote: 'Am 3.11. um 09:00 schrieb Anna:\n> Termin am Montag?', reply_to_message_id: 'm', subject: 'Re: Termin', to: ['anna@example.org'] } }
  setup(initial)
  expect(await screen.findByText('An: anna@example.org')).toBeTruthy()
  expect(screen.getByText('Kopie: ben@example.org, cara@example.org')).toBeTruthy()
  const quote = screen.getByRole('blockquote', { name: 'Zitierte Mail – wird mitgesendet' })
  expect(quote.textContent).toBe('Am 3.11. um 09:00 schrieb Anna:\n> Termin am Montag?')
  expect((screen.getByRole('button', { name: 'Senden' }) as HTMLButtonElement).disabled).toBe(false)
})

test('a new draft without copy or quote shows neither', async () => {
  const initial = message()
  initial.proposal = { kind: 'send', reason: 'Neue Mail an anna@example.org.', irreversible: true, items: [], draft: { account_id: 'a', body: 'Hallo', cc: [], mode: 'new', quote: '', reply_to_message_id: null, subject: 'Hallo', to: ['anna@example.org'] } }
  setup(initial)
  expect(await screen.findByText('An: anna@example.org')).toBeTruthy()
  expect(screen.queryByText(/^Kopie:/u)).toBeNull()
  expect(screen.queryByRole('blockquote')).toBeNull()
  expect(screen.queryByRole('list')).toBeNull()
})

test.each([1, 2])('partial result uses the correct form for %i failures', async (count) => {
  setup(message('partial', { done: 1, failed: Array.from({ length: count }, (_, i) => ({ id: String(i), code: 'action_failed' })) }))
  const ending = count === 1 ? '1 ließ sich nicht abbestellen.' : '2 ließen sich nicht abbestellen.'
  expect(await screen.findByText(`1 Newsletter abbestellt. ${ending}`)).toBeTruthy()
})

test('manual unsubscribe links have a large touch target', async () => {
  const css = await Bun.file(new URL('../styles/ds-app.css', import.meta.url)).text()
  const rule = css.match(/@media \(pointer: coarse\) \{ \.le-proposal-manual a \{ ([^{}]+) \} \}/u)
  expect(rule).toBeTruthy()
  for (const property of ['display: inline-flex', 'align-items: center', 'min-height: var(--control-height-lg)']) expect(rule?.[1]).toContain(property)
})

test('unsubscribe without archived mail and unsafe manual link', async () => {
  setup(message('partial', { done: 1, failed: [], manual: [{ id: 'a', link: 'javascript:alert(1)' }, { id: 'b', link: 'https://example.org/unsubscribe' }], undo_action_ids: [] }))
  expect(await screen.findByText('1 Newsletter abbestellt.')).toBeTruthy()
  const links = screen.getAllByRole('link', { name: 'Abmeldeseite öffnen' })
  expect(links).toHaveLength(1)
  expect(links[0]?.getAttribute('href')).toBe('https://example.org/unsubscribe')
  expect(links[0]?.getAttribute('rel')).toBe('noopener noreferrer')
  expect(links[0]?.parentElement?.classList.contains('le-proposal-manual')).toBe(true)
  expect(screen.getByText('Alpha: Kein Abmeldelink bekannt. Öffne eine Mail dieses Newsletters und bestell ihn dort ab.').classList.contains('le-proposal-manual')).toBe(true)
})

test('a manual unsubscribe without a link names the next step', async () => {
  setup(message('done', { done: 0, failed: [], manual: [{ id: 'b', link: null }], undo_action_ids: ['u1', 'u2'] }))
  expect(await screen.findByText('Kein Newsletter abbestellt, 2 Mails archiviert.')).toBeTruthy()
  expect(screen.getByText('Beta: Kein Abmeldelink bekannt. Öffne eine Mail dieses Newsletters und bestell ihn dort ab.')).toBeTruthy()
  expect(screen.queryByRole('link')).toBeNull()
})

test('after confirming, the focus moves from the gone button to the result', async () => {
  spyOn(sdk, 'chatProposalConfirm').mockImplementation((async () => ({ data: message('done', { done: 2, undo_action_ids: ['u'] }) })) as never)
  setup(message())
  const button = await screen.findByRole('button', { name: '2 abbestellen und archivieren' })
  button.focus(); fireEvent.click(button)
  await screen.findByRole('button', { name: 'Rückgängig' })
  await waitFor(() => expect(document.activeElement?.classList.contains('le-proposal-outcome')).toBe(true))
  expect(document.activeElement?.textContent).toContain('2 Newsletter abbestellt')
})

test('after cancelling, the focus moves to the cancelled hint', async () => {
  spyOn(sdk, 'chatProposalCancel').mockImplementation((async () => ({ data: message('cancelled') })) as never)
  setup(message())
  const button = await screen.findByRole('button', { name: 'Abbrechen' })
  button.focus(); fireEvent.click(button)
  await screen.findByText('Abgebrochen, es wurde nichts geändert.')
  await waitFor(() => expect(document.activeElement?.classList.contains('le-proposal-outcome')).toBe(true))
  expect(document.activeElement?.textContent).toBe('Abgebrochen, es wurde nichts geändert.')
})

test('after undoing, the focus stays on the result', async () => {
  spyOn(sdk, 'mailActionsUndo').mockImplementation((async () => ({ data: { restored: ['u'], expired: [], failed: [], skipped: [] } })) as never)
  await setupConfirmed(message('done', { done: 1, undo_action_ids: ['u'] }))
  const undo = screen.getByRole('button', { name: 'Rückgängig' })
  undo.focus(); fireEvent.click(undo)
  await screen.findByText('Rückgängig gemacht.')
  expect(document.activeElement?.classList.contains('le-proposal-outcome')).toBe(true)
})

function liveThenHistory() {
  const done = message('done', { done: 2, undo_action_ids: ['u'] })
  spyOn(sdk, 'chatProposalConfirm').mockImplementation((async () => ({ data: done })) as never)
  const client = new QueryClient()
  // The live card and the history row sit in different places, so React mounts a new card.
  const view = (inHistory: boolean) => <QueryClientProvider client={client}>{inHistory ? <section key="history"><ProposalCard message={done} /></section> : <div key="live"><ProposalCard message={message()} /><input aria-label="Frage" /></div>}</QueryClientProvider>
  return { view, ...render(view(false)) }
}

test('the focus follows a settled card when its history row replaces the live card', async () => {
  const { view, rerender } = liveThenHistory()
  const button = screen.getByRole('button', { name: '2 abbestellen und archivieren' })
  button.focus(); fireEvent.click(button)
  await screen.findByRole('button', { name: 'Rückgängig' })
  await waitFor(() => expect(document.activeElement?.classList.contains('le-proposal-outcome')).toBe(true))
  rerender(view(true))
  await waitFor(() => expect(document.querySelector('section .le-proposal-outcome')).toBe(document.activeElement))
})

test('a replaced card hands the focus on only when it holds it', async () => {
  const { view, rerender } = liveThenHistory()
  fireEvent.click(screen.getByRole('button', { name: '2 abbestellen und archivieren' }))
  await screen.findByRole('button', { name: 'Rückgängig' })
  const question = screen.getByLabelText('Frage')
  act(() => { question.focus() })
  rerender(view(true))
  await act(async () => { await new Promise(resolve => setTimeout(resolve, 0)) })
  expect(document.activeElement).toBe(document.body)
  cleanup()
  render(<QueryClientProvider client={new QueryClient()}><ProposalCard message={message('done', { done: 2 })} /></QueryClientProvider>)
  expect(document.activeElement).toBe(document.body)
})

test('a confirmation that finishes after the card is gone does not take the focus later', async () => {
  let resolve: (value: { data: ChatMessageOut }) => void = () => {}
  spyOn(sdk, 'chatProposalConfirm').mockImplementation((() => new Promise(done => { resolve = done })) as never)
  const client = new QueryClient()
  const view = render(<QueryClientProvider client={client}><ProposalCard message={message()} /></QueryClientProvider>)
  const button = screen.getByRole('button', { name: '2 abbestellen und archivieren' })
  button.focus(); fireEvent.click(button)
  view.unmount()
  await act(async () => { resolve({ data: message('done', { done: 2 }) }); await new Promise(done => setTimeout(done, 0)) })
  render(<QueryClientProvider client={client}><ProposalCard message={message('done', { done: 2 })} /></QueryClientProvider>)
  await screen.findByText(/2 Newsletter abbestellt/)
  expect(document.activeElement).toBe(document.body)
})

test('a settled card loaded from the history does not take the focus', async () => {
  setup(message('done', { done: 1 }))
  await screen.findByText('1 Newsletter abbestellt.')
  expect(document.activeElement).toBe(document.body)
})

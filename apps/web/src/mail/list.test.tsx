import { afterEach, expect, mock, spyOn, test } from 'bun:test'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createMemoryHistory, createRootRoute, createRoute, createRouter, Outlet, RouterProvider } from '@tanstack/react-router'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import * as sdk from '../api/generated/sdk.gen'
import { Route } from '../routes/_app/mail'
import { inboxSearchSchema } from './filters'

const originalMatchMedia = window.matchMedia
const row = { id: 'm1', account_id: 'a', color_index: 0, sender_name: 'Anna', sender_address: 'anna@example.com', subject: 'Termin', snippet: '', internal_date: null, deadline: null, has_attachments: false, is_flagged: false, is_read: false, needs_reply: false }
function setup(mode: 'empty' | 'error' | 'loading' | 'row' | 'rows' = 'empty', path = '/mail') {
  window.matchMedia = ((query: string) => ({ matches: query.includes('1024px'), addEventListener() {}, removeEventListener() {} })) as unknown as typeof window.matchMedia
  spyOn(sdk, 'mailSummary').mockImplementation((async () => ({ data: { accounts: [{ id: 'a', display_name: 'Privat', color_index: 0, state: 'ok' }], unread_total: 1, last_sync_at: null } })) as never)
  const list = spyOn(sdk, 'mailMessagesList').mockImplementation((async () => {
    if (mode === 'loading') return await new Promise(() => {})
    if (mode === 'error') throw new Error('unavailable')
    return { data: { items: mode === 'row' ? [row] : mode === 'rows' ? [row, { ...row, id: 'm2', subject: 'Zweite' }, { ...row, id: 'm3', subject: 'Dritte' }] : [], next_cursor: null } }
  }) as never)
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const root = createRootRoute({ component: () => <QueryClientProvider client={client}><Outlet /></QueryClientProvider> })
  const mail = createRoute({ getParentRoute: () => root, path: '/mail', validateSearch: inboxSearchSchema, component: Route.options.component })
  const index = createRoute({ getParentRoute: () => mail, path: '/', component: () => <div /> })
  const router = createRouter({ routeTree: root.addChildren([mail.addChildren([index])]), history: createMemoryHistory({ initialEntries: [path] }) })
  const view = render(<RouterProvider router={router} />)
  return { router, list, view }
}
afterEach(() => { cleanup(); mock.restore(); window.matchMedia = originalMatchMedia })

test('unread filter updates URL and query', async () => {
  const { router, list } = setup()
  fireEvent.click(await screen.findByRole('button', { name: 'Ungelesen' }))
  await waitFor(() => expect(router.state.location.searchStr).toContain('unread=true'))
  await waitFor(() => expect(list.mock.calls.some(([options]) => options?.query?.unread === true)).toBe(true))
})

test('shows the unfiltered empty state', async () => {
  setup(); expect(await screen.findByText('Keine Mails in diesem Konto. Neue erscheinen nach dem nächsten Abruf.')).toBeTruthy()
})
test('shows the filtered empty state', async () => {
  setup('empty', '/mail?unread=true'); expect(await screen.findByText('Keine Mails für diese Filter.')).toBeTruthy()
})
test('error notice retries the query', async () => {
  const { list } = setup('error')
  expect(await screen.findByText('Die Mails konnten nicht geladen werden. Versuch es gleich noch mal.')).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: 'Noch mal versuchen' }))
  await waitFor(() => expect(list.mock.calls.length).toBe(2))
})
test('shows six placeholder rows while loading', async () => {
  const { view } = setup('loading')
  await screen.findByText('Mails werden geladen …')
  expect(view.container.querySelectorAll('.le-mailrow--placeholder').length).toBe(6)
})
test('failed archive restores the highlight and the next archive targets the restored row', async () => {
  let fail!: (value: unknown) => void
  const action = spyOn(sdk, 'mailMessageAction').mockImplementation((() => new Promise(resolve => { fail = resolve })) as never)
  setup('rows'); await screen.findByText('Termin')
  fireEvent.keyDown(document.body, { key: 'j' })
  expect(screen.getByText('Termin').closest('.le-mailrow')?.getAttribute('aria-selected')).toBe('true')
  fireEvent.keyDown(document.body, { key: 'e' })
  await waitFor(() => expect(action).toHaveBeenCalledTimes(1))
  await waitFor(() => expect(screen.getByText('Zweite').closest('.le-mailrow')?.getAttribute('aria-selected')).toBe('true'))
  fail({ response: { status: 502 } })
  await screen.findByText('Das hat beim Anbieter nicht geklappt. Die Mail ist unverändert.')
  await waitFor(() => expect(screen.getByText('Termin').closest('.le-mailrow')?.getAttribute('aria-selected')).toBe('true'))
  fireEvent.keyDown(document.body, { key: 'e' })
  await waitFor(() => expect(action).toHaveBeenCalledTimes(2))
  expect(action.mock.calls[1]?.[0]?.path).toEqual({ message_id: 'm1' })
})

test('failed removal does not replace a highlight moved by the user', async () => {
  let fail!: (value: unknown) => void
  spyOn(sdk, 'mailMessageAction').mockImplementation((() => new Promise(resolve => { fail = resolve })) as never)
  setup('rows'); await screen.findByText('Termin')
  fireEvent.keyDown(document.body, { key: 'j' })
  fireEvent.keyDown(document.body, { key: 'e' })
  await waitFor(() => expect(screen.getByText('Zweite').closest('.le-mailrow')?.getAttribute('aria-selected')).toBe('true'))
  fireEvent.keyDown(document.body, { key: 'j' })
  expect(screen.getByText('Dritte').closest('.le-mailrow')?.getAttribute('aria-selected')).toBe('true')
  fail({ response: { status: 502 } })
  await screen.findByText('Das hat beim Anbieter nicht geklappt. Die Mail ist unverändert.')
  expect(screen.getByText('Dritte').closest('.le-mailrow')?.getAttribute('aria-selected')).toBe('true')
})

test('keyboard archives the selected row but not while typing search', async () => {
  const action = spyOn(sdk, 'mailMessageAction').mockImplementation((async () => ({ data: { action_id: 'act', message: row }, response: { status: 200 } })) as never)
  setup('row'); await screen.findByText('Termin')
  fireEvent.click(screen.getByRole('button', { name: 'Suchen' }))
  const input = screen.getByPlaceholderText('In allen Konten suchen …')
  fireEvent.keyDown(input, { key: 'e' }); expect(action).toHaveBeenCalledTimes(0)
  fireEvent.keyDown(document.body, { key: 'j' }); fireEvent.keyDown(document.body, { key: 'e' })
  await waitFor(() => expect(action).toHaveBeenCalledTimes(1))
  expect(action.mock.calls[0]?.[0]?.body).toEqual({ kind: 'archive' })
})

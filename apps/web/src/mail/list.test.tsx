import { afterEach, expect, mock, spyOn, test } from 'bun:test'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createMemoryHistory, createRootRoute, createRoute, createRouter, Outlet, RouterProvider } from '@tanstack/react-router'
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import * as sdk from '../api/generated/sdk.gen'
import { Route } from '../routes/_app/mail'
import { inboxSearchSchema } from './filters'

const originalMatchMedia = window.matchMedia
const row = { id: 'm1', account_id: 'a', color_index: 0, sender_name: 'Anna', sender_address: 'anna@example.com', subject: 'Termin', snippet: '', internal_date: null, deadline: null, has_attachments: false, is_flagged: false, is_read: false, needs_reply: false }
function setup(mode: 'empty' | 'error' | 'loading' | 'row' | 'rows' = 'empty', path = '/mail', coarse = false) {
  window.matchMedia = ((query: string) => ({ matches: query.includes('1024px') || (coarse && query.includes('pointer: coarse')), addEventListener() {}, removeEventListener() {} })) as unknown as typeof window.matchMedia
  spyOn(sdk, 'mailSummary').mockImplementation((async () => ({ data: { accounts: [{ id: 'a', display_name: '', email_address: 'ich@example.com', provider: 'gmail', color_index: 0, state: 'ok' }], unread_total: 1, last_sync_at: null } })) as never)
  const list = spyOn(sdk, 'mailMessagesList').mockImplementation((async () => {
    if (mode === 'loading') return await new Promise(() => {})
    if (mode === 'error') throw new Error('unavailable')
    return { data: { items: mode === 'row' ? [row] : mode === 'rows' ? [row, { ...row, id: 'm2', subject: 'Zweite' }, { ...row, id: 'm3', subject: 'Dritte' }] : [], next_cursor: null } }
  }) as never)
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const root = createRootRoute({ component: () => <QueryClientProvider client={client}><Outlet /></QueryClientProvider> })
  const mail = createRoute({ getParentRoute: () => root, path: '/mail', validateSearch: inboxSearchSchema, component: Route.options.component })
  const index = createRoute({ getParentRoute: () => mail, path: '/', component: () => <div /> })
  const message = createRoute({ getParentRoute: () => mail, path: '$messageId', component: () => <div /> })
  const router = createRouter({ routeTree: root.addChildren([mail.addChildren([index, message])]), history: createMemoryHistory({ initialEntries: [path] }) })
  const view = render(<RouterProvider router={router} />)
  return { router, list, view, client }
}
afterEach(() => { cleanup(); mock.restore(); window.matchMedia = originalMatchMedia })
// Lets queries a view starts on mount settle inside act() before the test moves on or ends.
const settle = () => act(async () => { await new Promise(resolve => setTimeout(resolve, 0)) })
// Waits until a removal's follow-up refetches are done, then lets their renders settle.
const settleFetches = async (client: QueryClient) => { await waitFor(() => expect(client.isFetching()).toBe(0)); await settle() }

test('coarse pointer inbox controls use the large touch target token', async () => {
  const css = await Bun.file(new URL('../styles/ds-app.css', import.meta.url)).text()
  const rule = css.match(/@media \(pointer: coarse\) \{ (\.le-inbox-filters[^{}]+)\{ ([^{}]+) \} \.le-inbox-toast \.le-link \{ ([^{}]+) \} \}/u)
  expect(rule).toBeTruthy()
  for (const selector of ['.le-inbox-filters .le-chip', '.le-inbox-control', '.le-inbox-toast .le-link']) expect(rule?.[1]).toContain(selector)
  expect(rule?.[2]).toContain('min-width: var(--control-height-lg)')
  expect(rule?.[2]).toContain('min-height: var(--control-height-lg)')
  for (const property of ['display: inline-flex', 'align-items: center', 'justify-content: center']) expect(rule?.[3]).toContain(property)
  expect(css).toMatch(/\.le-inbox-scroll \{[^}]*padding-bottom: calc\(var\(--control-height-lg\) \+ 2 \* var\(--space-4\)\)/u)
  setup('row', '/mail', true)
  await screen.findByText('Termin')
  for (const name of ['Suchen', 'Jetzt abrufen']) expect(screen.getByRole('button', { name }).classList.contains('le-icon-btn--lg')).toBe(true)
})

test('rows show provider tags and account filters fall back to the address', async () => {
  setup('row')
  const subject = await screen.findByText('Termin')
  expect(subject.closest('.le-mailrow')?.querySelector('.le-mailrow-top .le-tag')?.textContent).toBe('Gmail')
  const filter = screen.getByRole('button', { name: 'Alle Konten' })
  const chevron = filter.querySelector('.lucide-chevron-down')
  expect(chevron?.getAttribute('aria-hidden')).toBe('true')
  expect(filter.lastElementChild).toBe(chevron)
  fireEvent.click(filter)
  fireEvent.click(screen.getByRole('menuitem', { name: 'ich@example.com' }))
  expect(await screen.findByRole('button', { name: 'ich@example.com' })).toBeTruthy()
  await settle()
})

test('unread filter updates URL and query', async () => {
  const { router, list } = setup()
  fireEvent.click(await screen.findByRole('button', { name: 'Ungelesen' }))
  await waitFor(() => expect(router.state.location.searchStr).toContain('unread=true'))
  await waitFor(() => expect(list.mock.calls.some(([options]) => options?.query?.unread === true)).toBe(true))
})

test('shows the unfiltered empty state', async () => {
  setup(); expect(await screen.findByText('Keine Mails im Posteingang. Neue erscheinen nach dem nächsten Abruf.')).toBeTruthy()
})
test('shows the filtered empty state', async () => {
  setup('empty', '/mail?unread=true'); expect(await screen.findByText('Keine Mails passen zu diesen Filtern. Nimm einen Filter heraus, um mehr zu sehen.')).toBeTruthy()
})
test('error notice retries the query', async () => {
  const { list } = setup('error')
  expect(await screen.findByText('Die Mails konnten nicht geladen werden. Versuch es gleich noch mal.')).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: 'Noch mal versuchen' }))
  await waitFor(() => expect(list.mock.calls.length).toBe(2))
})
test('archive toast replaces a failed refresh notice', async () => {
  spyOn(sdk, 'mailSyncAll').mockImplementation((async () => ({ error: {}, response: { ok: false } })) as never)
  spyOn(sdk, 'mailMessageAction').mockImplementation((async () => ({ data: { action_id: 'act', message: row }, response: { status: 200 } })) as never)
  setup('row'); await screen.findByText('Termin')
  fireEvent.click(screen.getByRole('button', { name: 'Jetzt abrufen' }))
  expect(await screen.findByText('Die Mails konnten nicht abgerufen werden. Versuch es gleich noch mal.')).toBeTruthy()
  fireEvent.keyDown(document.body, { key: 'j' }); fireEvent.keyDown(document.body, { key: 'e' })
  expect(await screen.findByText('„Termin“ archiviert.')).toBeTruthy()
  expect(screen.getByText('Rückgängig')).toBeTruthy()
  expect(screen.queryByText('Die Mails konnten nicht abgerufen werden. Versuch es gleich noch mal.')).toBeNull()
})

test('shows six placeholder rows while loading', async () => {
  const { view, client } = setup('loading')
  await screen.findByText('Mails werden geladen …')
  expect(view.container.querySelectorAll('.le-mailrow--placeholder').length).toBe(6)
  // The list stays pending on purpose; only the summary settles.
  await waitFor(() => expect(client.getQueryState(['summary'])?.status).toBe('success'))
  await settle()
})
test('archiving an open mail selects and opens the next mail with filters', async () => {
  const action = spyOn(sdk, 'mailMessageAction').mockImplementation((async () => ({ data: { action_id: 'act', message: row }, response: { status: 200 } })) as never)
  const { router } = setup('rows', '/mail/m1?unread=true')
  await screen.findByText('Termin')
  expect(screen.getByText('Termin').closest('.le-mailrow')?.getAttribute('aria-current')).toBe('true')
  fireEvent.keyDown(document.body, { key: 'e' })
  await waitFor(() => expect(router.state.location.pathname).toBe('/mail/m2'))
  expect(router.state.location.searchStr).toContain('unread=true')
  await waitFor(() => expect(action.mock.calls[0]?.[0]?.path).toEqual({ message_id: 'm1' }))
  expect(screen.getByText('Zweite').closest('.le-mailrow')?.getAttribute('aria-current')).toBe('true')
})

test('failed removal of an open mail returns to it if navigation has not changed', async () => {
  let fail!: (value: unknown) => void
  spyOn(sdk, 'mailMessageAction').mockImplementation((() => new Promise(resolve => { fail = resolve })) as never)
  const { router } = setup('rows', '/mail/m1?unread=true')
  await screen.findByText('Termin')
  fireEvent.keyDown(document.body, { key: 'e' })
  await waitFor(() => expect(router.state.location.pathname).toBe('/mail/m2'))
  await waitFor(() => expect(fail).toBeDefined())
  fail({ response: { status: 502 } })
  await waitFor(() => expect(router.state.location.pathname).toBe('/mail/m1'))
  expect(router.state.location.searchStr).toContain('unread=true')
})

test('archiving the only open mail returns to the filtered list', async () => {
  spyOn(sdk, 'mailMessageAction').mockImplementation((async () => ({ data: { action_id: 'act', message: row }, response: { status: 200 } })) as never)
  const { router } = setup('row', '/mail/m1?unread=true')
  await screen.findByText('Termin')
  fireEvent.keyDown(document.body, { key: 'e' })
  await waitFor(() => expect(router.state.location.pathname).toBe('/mail'))
  expect(router.state.location.searchStr).toContain('unread=true')
})

test('j and k open adjacent mails while preserving filters', async () => {
  const { router } = setup('rows', '/mail/m1?unread=true')
  await screen.findByText('Termin')
  fireEvent.keyDown(document.body, { key: 'j' })
  await waitFor(() => expect(router.state.location.pathname).toBe('/mail/m2'))
  expect(router.state.location.searchStr).toContain('unread=true')
  fireEvent.keyDown(document.body, { key: 'k' })
  await waitFor(() => expect(router.state.location.pathname).toBe('/mail/m1'))
})

test('trashing the last open mail by its row button opens the previous mail', async () => {
  const action = spyOn(sdk, 'mailMessageAction').mockImplementation((async () => ({ data: { action_id: 'act', message: row }, response: { status: 200 } })) as never)
  const { router } = setup('rows', '/mail/m3')
  const rowElement = (await screen.findByText('Dritte')).closest('.le-mailrow')!
  fireEvent.click(rowElement.querySelector('button[aria-label="In den Papierkorb"]')!)
  await waitFor(() => expect(router.state.location.pathname).toBe('/mail/m2'))
  await waitFor(() => expect(action.mock.calls[0]?.[0]?.path).toEqual({ message_id: 'm3' }))
})

test('failed archive restores the highlight and the next archive targets the restored row', async () => {
  let fail!: (value: unknown) => void
  const action = spyOn(sdk, 'mailMessageAction').mockImplementation((() => new Promise(resolve => { fail = resolve })) as never)
  setup('rows'); await screen.findByText('Termin')
  fireEvent.keyDown(document.body, { key: 'j' })
  expect(screen.getByText('Termin').closest('.le-mailrow')?.getAttribute('aria-current')).toBe('true')
  fireEvent.keyDown(document.body, { key: 'e' })
  await waitFor(() => expect(action).toHaveBeenCalledTimes(1))
  await waitFor(() => expect(screen.getByText('Zweite').closest('.le-mailrow')?.getAttribute('aria-current')).toBe('true'))
  fail({ response: { status: 502 } })
  await screen.findByText('Das hat nicht geklappt. Lade den Posteingang neu, um zu sehen, wo die Mail jetzt liegt.')
  await waitFor(() => expect(screen.getByText('Termin').closest('.le-mailrow')?.getAttribute('aria-current')).toBe('true'))
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
  await waitFor(() => expect(screen.getByText('Zweite').closest('.le-mailrow')?.getAttribute('aria-current')).toBe('true'))
  fireEvent.keyDown(document.body, { key: 'j' })
  expect(screen.getByText('Dritte').closest('.le-mailrow')?.getAttribute('aria-current')).toBe('true')
  fail({ response: { status: 502 } })
  await screen.findByText('Das hat nicht geklappt. Lade den Posteingang neu, um zu sehen, wo die Mail jetzt liegt.')
  expect(screen.getByText('Dritte').closest('.le-mailrow')?.getAttribute('aria-current')).toBe('true')
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

const rowOf = async (subject: string) => (await screen.findByText(subject)).closest('.le-mailrow') as HTMLElement
const linkOf = (subject: string) => (screen.getByText(subject).closest('.le-mailrow') as HTMLElement).querySelector('.le-mailrow-link')
const archiveFrom = (element: HTMLElement) => { const button = element.querySelector<HTMLButtonElement>('button[aria-label="Archivieren"]')!; act(() => { button.focus() }); fireEvent.click(button) }
// Like the server: an archived mail no longer comes back from the list.
function archivingServer(list: ReturnType<typeof setup>['list'], mode: 'row' | 'rows') {
  const removed = new Set<string>()
  const all = mode === 'row' ? [row] : [row, { ...row, id: 'm2', subject: 'Zweite' }, { ...row, id: 'm3', subject: 'Dritte' }]
  list.mockImplementation((async () => ({ data: { items: all.filter(item => !removed.has(item.id)), next_cursor: null } })) as never)
  return spyOn(sdk, 'mailMessageAction').mockImplementation((async (options: { path: { message_id: string } }) => { removed.add(options.path.message_id); return { data: { action_id: 'act', message: row }, response: { status: 200 } } }) as never)
}

test('removing a focused row moves the focus to the next row', async () => {
  const { list, client } = setup('rows'); archivingServer(list, 'rows')
  archiveFrom(await rowOf('Zweite'))
  await waitFor(() => expect(screen.queryByText('Zweite')).toBeNull())
  await waitFor(() => expect(document.activeElement).toBe(linkOf('Dritte')))
  await settleFetches(client)
})

test('removing the focused last row moves the focus to the previous row', async () => {
  const { list, client } = setup('rows'); archivingServer(list, 'rows')
  archiveFrom(await rowOf('Dritte'))
  await waitFor(() => expect(screen.queryByText('Dritte')).toBeNull())
  await waitFor(() => expect(document.activeElement).toBe(linkOf('Zweite')))
  await settleFetches(client)
})

test('removing the only focused row moves the focus to the list', async () => {
  const { list, client } = setup('row'); archivingServer(list, 'row')
  archiveFrom(await rowOf('Termin'))
  await waitFor(() => expect(screen.queryByText('Termin')).toBeNull())
  await waitFor(() => expect(document.activeElement?.classList.contains('le-inbox-scroll')).toBe(true))
  await settleFetches(client)
})

test('a keyboard removal without focus in the row leaves the focus alone', async () => {
  const { list } = setup('rows'); const action = archivingServer(list, 'rows')
  await rowOf('Termin')
  ;(document.activeElement as HTMLElement | null)?.blur()
  fireEvent.keyDown(document.body, { key: 'j' }); fireEvent.keyDown(document.body, { key: 'e' })
  await waitFor(() => expect(action).toHaveBeenCalledTimes(1))
  await waitFor(() => expect(screen.queryByText('Termin')).toBeNull())
  expect(document.activeElement).toBe(document.body)
})

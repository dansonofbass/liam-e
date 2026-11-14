import { afterEach, expect, mock, spyOn, test } from 'bun:test'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createMemoryHistory, createRootRoute, createRoute, createRouter, Outlet, RouterProvider } from '@tanstack/react-router'
import { act, render, screen, cleanup, fireEvent, waitFor, within } from '@testing-library/react'
import * as sdk from '../api/generated/sdk.gen'
import type { AccountOut } from '../api/generated/types.gen'
import { AccountCard } from '../ds/AccountCard'
import { AccountsPage } from './AccountsPage'
import { redirect } from './redirect'

const account: AccountOut = { id: 'a1', email_address: 'x@yahoo.com', display_name: 'Privat', provider: 'imap', auth_type: 'imap_password', connection: 'imap', state: 'never', error_code: '', last_sync_at: null, message_count: 0, unread: 0, color_index: 0, is_active: true, created_at: '', updated_at: '' }
const originalMatchMedia = window.matchMedia
afterEach(() => { cleanup(); mock.restore(); window.matchMedia = originalMatchMedia })
const props = { onSync: () => {}, onReconnect: () => {}, onRename: () => {}, onRemove: () => {} }
function setup(mode: 'row' | 'empty' | 'error' | 'loading' = 'row', path = '/accounts', item = account, extra: AccountOut[] = []) {
  window.matchMedia = (() => ({ matches: true, addEventListener() {}, removeEventListener() {} })) as unknown as typeof window.matchMedia
  const list = spyOn(sdk, 'mailAccountsList').mockImplementation((async () => { if (mode === 'loading') return await new Promise(() => {}); if (mode === 'error') throw new Error('offline'); return { data: mode === 'empty' ? [] : [item, ...extra] } }) as never)
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const root = createRootRoute({ component: () => <QueryClientProvider client={client}><Outlet /></QueryClientProvider> })
  const page = createRoute({ getParentRoute: () => root, path: '/accounts', validateSearch: (search: Record<string, unknown>) => search, component: AccountsPage })
  const router = createRouter({ routeTree: root.addChildren([page]), history: createMemoryHistory({ initialEntries: [path] }) })
  const view = render(<RouterProvider router={router} />)
  return { router, list, view, client }
}

test('card shows each state and connection', () => {
  const { rerender } = render(<AccountCard account={account} {...props} />)
  expect(screen.getByText('Yahoo')).toBeTruthy(); expect(screen.getByText('IMAP')).toBeTruthy(); expect(screen.getByText('Noch nicht abgerufen')).toBeTruthy()
  rerender(<AccountCard account={{ ...account, state: 'syncing', connection: 'connector' }} {...props} />)
  expect(screen.getByText('Wird abgerufen …')).toBeTruthy(); expect(screen.getByText('über Connector')).toBeTruthy(); expect((screen.getByRole('button', { name: 'Wird gerade abgerufen' }) as HTMLButtonElement).disabled).toBe(true)
  rerender(<AccountCard account={{ ...account, state: 'auth_expired', connection: 'oauth', provider: 'microsoft' }} {...props} />)
  expect(screen.getByText('Anmeldung abgelaufen')).toBeTruthy(); expect(screen.getByText('Outlook')).toBeTruthy(); expect(screen.getByText('mit Anmeldung')).toBeTruthy()
  rerender(<AccountCard account={{ ...account, state: 'error', error_code: 'login_failed', provider: 'gmail' }} {...props} />)
  expect(screen.getByText('Gmail')).toBeTruthy(); expect(screen.getByText('Die Anmeldung beim Mailserver hat nicht geklappt. Prüf die Serveradresse und das App-Passwort.')).toBeTruthy()
  rerender(<AccountCard account={{ ...account, state: 'error', error_code: 'unknown', email_address: 'a@icloud.com' }} {...props} />)
  expect(screen.getByText('iCloud')).toBeTruthy(); expect(screen.getByText('Das Konto ist gerade nicht erreichbar. Versuch es gleich noch mal.')).toBeTruthy()
  rerender(<AccountCard account={{ ...account, state: 'ok', last_sync_at: '2026-01-01T12:00:00Z', email_address: 'a@example.com' }} {...props} />)
  expect(screen.getByText('example.com')).toBeTruthy(); expect(screen.getByText(/^Stand /)).toBeTruthy()
})
test('return error is shown and removed from URL', async () => {
  const { router } = setup('empty', '/accounts?error=oauth_denied')
  expect(await screen.findByText('Die Anmeldung wurde abgebrochen. Versuch es bei Bedarf noch mal.')).toBeTruthy()
  await waitFor(() => expect(router.state.location.searchStr).toBe(''))
})
test('connected return syncs once and clears URL', async () => {
  const sync = spyOn(sdk, 'mailAccountSync').mockImplementation((async () => ({ response: { ok: true } })) as never)
  const { router } = setup('empty', '/accounts?connected=a1')
  expect(await screen.findByText('Konto verbunden.')).toBeTruthy()
  await waitFor(() => expect(router.state.location.searchStr).toBe(''))
  expect(sync).toHaveBeenCalledTimes(1); expect(sync.mock.calls[0]?.[0]?.path).toEqual({ account_id: 'a1' })
})
test('sync one and all', async () => {
  const sync = spyOn(sdk, 'mailAccountSync').mockImplementation((async () => ({ response: { ok: true } })) as never)
  const all = spyOn(sdk, 'mailSyncAll').mockImplementation((async () => ({ response: { ok: true } })) as never)
  setup(); fireEvent.click(await screen.findByRole('button', { name: 'x@yahoo.com jetzt abrufen' })); await waitFor(() => expect(sync).toHaveBeenCalledTimes(1))
  expect(sync.mock.calls[0]?.[0]?.path).toEqual({ account_id: 'a1' }); fireEvent.click(screen.getByRole('button', { name: 'Alle abrufen' })); await waitFor(() => expect(all).toHaveBeenCalledTimes(1))
})
test('oauth reconnect redirects and connector reconnect shows Studio notice', async () => {
  const authorize = spyOn(sdk, 'mailAccountOauthAuthorize').mockImplementation((async () => ({ data: { authorization_url: 'https://example.com' } })) as never)
  const go = spyOn(redirect, 'to').mockImplementation(() => {})
  setup('row', '/accounts', { ...account, provider: 'google', connection: 'oauth', state: 'auth_expired' })
  fireEvent.click(await screen.findByRole('button', { name: 'Erneut anmelden' })); await waitFor(() => expect(go).toHaveBeenCalledWith('https://example.com'))
  expect(authorize.mock.calls[0]?.[0]?.query).toEqual({ account_id: 'a1' }); cleanup(); mock.restore()
  const noAuthorize = spyOn(sdk, 'mailAccountOauthAuthorize')
  setup('row', '/accounts', { ...account, provider: 'gmail', connection: 'connector', state: 'auth_expired' })
  fireEvent.click(await screen.findByRole('button', { name: 'Erneut anmelden' })); expect(screen.getByText(/Die Anmeldung für diesen Connector liegt/)).toBeTruthy(); expect(noAuthorize).not.toHaveBeenCalled()
})
async function openAction(action: 'Umbenennen' | 'Entfernen') {
  const trigger = await screen.findByRole('button', { name: 'Weitere Aktionen zu Privat' })
  act(() => { trigger.focus() }); fireEvent.click(trigger); fireEvent.click(screen.getByRole('menuitem', { name: action }))
  return trigger
}

test('rename selects the current name and saves trimmed input on Enter', async () => {
  const update = spyOn(sdk, 'mailAccountUpdate').mockImplementation((async () => ({ data: { ...account, display_name: 'Arbeit' }, response: { ok: true } })) as never)
  const { client } = setup(); const invalidate = spyOn(client, 'invalidateQueries'); await openAction('Umbenennen')
  const field = screen.getByRole('textbox', { name: 'Name des Kontos' }) as HTMLInputElement
  expect(document.activeElement).toBe(field); expect(field.selectionStart).toBe(0); expect(field.selectionEnd).toBe(6)
  fireEvent.change(field, { target: { value: '  Arbeit  ' } }); fireEvent.submit(field.closest('form')!)
  await waitFor(() => expect(update).toHaveBeenCalledTimes(1))
  expect(update.mock.calls[0]?.[0]).toMatchObject({ path: { account_id: 'a1' }, body: { display_name: 'Arbeit' } })
  await waitFor(() => expect(screen.getByText('Arbeit')).toBeTruthy())
  expect(client.getQueryData<AccountOut[]>(['accounts'])?.[0]?.display_name).toBe('Arbeit'); expect(invalidate.mock.calls.map(call => call[0]?.queryKey)).toContainEqual(['summary'])
  expect(document.activeElement).toBe(screen.getByRole('button', { name: 'Weitere Aktionen zu Arbeit' }))
})

test('rename Escape cancels and returns focus without a request', async () => {
  const update = spyOn(sdk, 'mailAccountUpdate')
  setup(); const trigger = await openAction('Umbenennen')
  fireEvent.keyDown(screen.getByRole('textbox', { name: 'Name des Kontos' }), { key: 'Escape' })
  expect(screen.queryByRole('textbox', { name: 'Name des Kontos' })).toBeNull(); expect(update).not.toHaveBeenCalled(); expect(document.activeElement).toBe(trigger)
})

test('rename rejects empty and overly long names', async () => {
  const update = spyOn(sdk, 'mailAccountUpdate')
  setup(); await openAction('Umbenennen')
  const field = screen.getByRole('textbox', { name: 'Name des Kontos' }) as HTMLInputElement
  for (const value of ['  ', 'x'.repeat(81)]) {
    fireEvent.change(field, { target: { value } }); fireEvent.submit(field.closest('form')!)
    expect(screen.getByText('Gib einen Namen mit bis zu 80 Zeichen ein.')).toBeTruthy()
  }
  expect(update).not.toHaveBeenCalled()
})

test('rename keeps the form and shows an API refusal', async () => {
  spyOn(sdk, 'mailAccountUpdate').mockImplementation((async () => ({ error: { detail: { code: 'account_not_found' } } })) as never)
  setup(); await openAction('Umbenennen'); fireEvent.submit(screen.getByRole('textbox', { name: 'Name des Kontos' }).closest('form')!)
  expect(await screen.findByText('Das Konto gibt es nicht mehr.')).toBeTruthy(); expect(screen.getByRole('textbox', { name: 'Name des Kontos' })).toBeTruthy()
})

test('remove traps focus and Escape returns it without deleting', async () => {
  const remove = spyOn(sdk, 'mailAccountDelete')
  setup(); const trigger = await openAction('Entfernen')
  const dialog = screen.getByRole('dialog', { name: 'Privat entfernen?' })
  expect(screen.getByText('Entfernst du ein Konto, löscht liam-e nur seine Kopie der Mails. Beim Anbieter bleibt alles, wie es ist.')).toBeTruthy()
  expect(within(dialog).getByText(/löscht liam-e nur seine Kopie der Mails/)).toBeTruthy()
  const cancel = within(dialog).getByRole('button', { name: 'Abbrechen' }), confirm = within(dialog).getByRole('button', { name: 'Konto entfernen' })
  expect(document.activeElement).toBe(cancel)
  fireEvent.keyDown(document, { key: 'Tab', shiftKey: true }); expect(document.activeElement).toBe(confirm)
  fireEvent.keyDown(document, { key: 'Tab' }); expect(document.activeElement).toBe(cancel)
  fireEvent.keyDown(document, { key: 'Escape' }); expect(screen.queryByRole('dialog')).toBeNull(); expect(document.activeElement).toBe(trigger); expect(remove).not.toHaveBeenCalled()
})

test('remove confirms once, removes the card and focuses the connect heading', async () => {
  const remove = spyOn(sdk, 'mailAccountDelete').mockImplementation((async () => ({ response: { ok: true, status: 204 } })) as never)
  setup(); await openAction('Entfernen'); fireEvent.click(screen.getByRole('button', { name: 'Konto entfernen' }))
  await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull()); expect(remove).toHaveBeenCalledTimes(1)
  expect(remove.mock.calls[0]?.[0]?.path).toEqual({ account_id: 'a1' }); expect(screen.queryByText('Privat')).toBeNull(); expect(screen.getByText('Privat ist entfernt.')).toBeTruthy()
  expect(document.activeElement).toBe(screen.getByRole('heading', { name: 'Konto verbinden' }))
})

test('remove waits for confirmation and prevents duplicate requests while pending', async () => {
  let resolve!: (result: unknown) => void
  const remove = spyOn(sdk, 'mailAccountDelete').mockImplementation((() => new Promise(done => { resolve = done })) as never)
  setup(); await openAction('Entfernen'); expect(remove).not.toHaveBeenCalled()
  const button = screen.getByRole('button', { name: 'Konto entfernen' }) as HTMLButtonElement
  fireEvent.click(button); expect(button.disabled).toBe(true); fireEvent.click(button); expect(remove).toHaveBeenCalledTimes(1)
  resolve({ response: { ok: true, status: 204 } }); await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
})

test('remove focuses the remaining accounts heading and invalidates related queries', async () => {
  spyOn(sdk, 'mailAccountDelete').mockImplementation((async () => ({ response: { ok: true, status: 204 } })) as never)
  const { client } = setup('row', '/accounts', account, [{ ...account, id: 'a2', display_name: 'Arbeit' }])
  const invalidate = spyOn(client, 'invalidateQueries')
  await openAction('Entfernen'); fireEvent.click(screen.getByRole('button', { name: 'Konto entfernen' }))
  await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
  expect(document.activeElement).toBe(screen.getByRole('heading', { name: 'Verbundene Konten' }))
  expect(screen.getByText('Arbeit')).toBeTruthy(); expect(invalidate.mock.calls.map(call => call[0]?.queryKey)).toContainEqual(['summary']); expect(invalidate.mock.calls.map(call => call[0]?.queryKey)).toContainEqual(['messages'])
})

test('remove failure keeps the dialog open with a notice', async () => {
  spyOn(sdk, 'mailAccountDelete').mockImplementation((async () => ({ error: { detail: { code: 'account_not_found' } } })) as never)
  setup(); await openAction('Entfernen'); fireEvent.click(screen.getByRole('button', { name: 'Konto entfernen' }))
  const dialog = screen.getByRole('dialog'); expect(await within(dialog).findByText('Das Konto gibt es nicht mehr.')).toBeTruthy()
})

test('loading, retry and empty states', async () => {
  const loading = setup('loading'); await screen.findByText('Konten werden geladen …'); expect(loading.view.container.querySelectorAll('.le-account--placeholder')).toHaveLength(3); cleanup(); mock.restore()
  const failed = setup('error'); await screen.findByText('Die Konten konnten nicht geladen werden. Versuch es gleich noch mal.'); fireEvent.click(screen.getByRole('button', { name: 'Noch mal versuchen' })); await waitFor(() => expect(failed.list).toHaveBeenCalledTimes(2)); cleanup(); mock.restore()
  setup('empty'); await screen.findByText('Noch kein Konto verbunden. Wähl einen Anbieter, dann holt liam-e deine Mails.'); expect(screen.queryByRole('list', { name: 'Verbundene Konten' })).toBeNull()
})

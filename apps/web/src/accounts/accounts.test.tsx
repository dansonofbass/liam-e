import { afterEach, expect, mock, spyOn, test } from 'bun:test'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createMemoryHistory, createRootRoute, createRoute, createRouter, Outlet, RouterProvider } from '@tanstack/react-router'
import { render, screen, cleanup, fireEvent, waitFor } from '@testing-library/react'
import * as sdk from '../api/generated/sdk.gen'
import type { AccountOut } from '../api/generated/types.gen'
import { AccountCard } from '../ds/AccountCard'
import { AccountsPage } from './AccountsPage'
import { redirect } from './redirect'

const account: AccountOut = { id: 'a1', email_address: 'x@yahoo.com', display_name: 'Privat', provider: 'imap', auth_type: 'imap_password', connection: 'imap', state: 'never', error_code: '', last_sync_at: null, message_count: 0, unread: 0, color_index: 0, is_active: true, created_at: '', updated_at: '' }
const originalMatchMedia = window.matchMedia
afterEach(() => { cleanup(); mock.restore(); window.matchMedia = originalMatchMedia })
const props = { onSync: () => {}, onReconnect: () => {}, onRename: () => {}, onRemove: () => {} }
function setup(mode: 'row' | 'empty' | 'error' | 'loading' = 'row', path = '/accounts', item = account) {
  window.matchMedia = (() => ({ matches: true, addEventListener() {}, removeEventListener() {} })) as unknown as typeof window.matchMedia
  const list = spyOn(sdk, 'mailAccountsList').mockImplementation((async () => { if (mode === 'loading') return await new Promise(() => {}); if (mode === 'error') throw new Error('offline'); return { data: mode === 'empty' ? [] : [item] } }) as never)
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const root = createRootRoute({ component: () => <QueryClientProvider client={client}><Outlet /></QueryClientProvider> })
  const page = createRoute({ getParentRoute: () => root, path: '/accounts', validateSearch: (search: Record<string, unknown>) => search, component: AccountsPage })
  const router = createRouter({ routeTree: root.addChildren([page]), history: createMemoryHistory({ initialEntries: [path] }) })
  const view = render(<RouterProvider router={router} />)
  return { router, list, view }
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
test('loading, retry and empty states', async () => {
  const loading = setup('loading'); await screen.findByText('Konten werden geladen …'); expect(loading.view.container.querySelectorAll('.le-account--placeholder')).toHaveLength(3); cleanup(); mock.restore()
  const failed = setup('error'); await screen.findByText('Die Konten konnten nicht geladen werden. Versuch es gleich noch mal.'); fireEvent.click(screen.getByRole('button', { name: 'Noch mal versuchen' })); await waitFor(() => expect(failed.list).toHaveBeenCalledTimes(2)); cleanup(); mock.restore()
  setup('empty'); await screen.findByText('Noch kein Konto verbunden. Wähl einen Anbieter, dann holt liam-e deine Mails.'); expect(screen.queryByRole('list', { name: 'Verbundene Konten' })).toBeNull()
})

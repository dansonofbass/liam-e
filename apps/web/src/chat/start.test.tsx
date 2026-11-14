import { afterEach, expect, mock, spyOn, test } from 'bun:test'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createMemoryHistory, createRootRoute, createRoute, createRouter, Outlet, RouterProvider } from '@tanstack/react-router'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import * as sdk from '../api/generated/sdk.gen'
import { de } from '../i18n/de'
import { formatTime } from '../i18n/format'
import { Route } from '../routes/_app/index'
import { ChatSessionProvider } from './session'

const originalFetch = globalThis.fetch, originalMatchMedia = window.matchMedia
let request: Record<string, unknown>
function setup(accounts = true, path = '/', unread = 3, lastSync: string | null = null) {
  window.matchMedia = (() => ({ matches: true })) as unknown as typeof window.matchMedia
  globalThis.fetch = ((_url: unknown, init: RequestInit) => { request = JSON.parse(String(init.body)) as Record<string, unknown>; return Promise.resolve(new Response(new ReadableStream({ start() {} }))) }) as typeof fetch
  spyOn(sdk, 'mailSummary').mockImplementation((async () => ({ data: { accounts: accounts ? [{ id: 'a', display_name: 'Privat', color_index: 0, state: 'ok' }] : [], unread_total: unread, newsletter_senders: 2, last_sync_at: lastSync } })) as never)
  spyOn(sdk, 'chatModelsList').mockImplementation((async () => ({ data: [{ id: 'm', label: 'Standardmodell', description: '', is_default: true }] })) as never)
  spyOn(sdk, 'mailMessageGet').mockImplementation((async () => ({ data: { id: 'mail1', account_id: 'a', color_index: 0, sender_name: 'Anna', subject: 'Termin', internal_date: null, deadline: null } })) as never)
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const root = createRootRoute({ component: () => <QueryClientProvider client={client}><ChatSessionProvider><Outlet /></ChatSessionProvider></QueryClientProvider> })
  const index = createRoute({ getParentRoute: () => root, path: '/', validateSearch: (search: Record<string, unknown>) => ({ about: typeof search.about === 'string' ? search.about : undefined }), component: Route.options.component })
  const accountsRoute = createRoute({ getParentRoute: () => root, path: '/accounts', component: () => <p>Konten</p> })
  const mailRoute = createRoute({ getParentRoute: () => root, path: '/mail/$messageId', component: () => <p>Mail</p> })
  const router = createRouter({ routeTree: root.addChildren([index, accountsRoute, mailRoute]), history: createMemoryHistory({ initialEntries: [path] }) })
  render(<RouterProvider router={router} />)
  return router
}
afterEach(() => { cleanup(); mock.restore(); globalThis.fetch = originalFetch; window.matchMedia = originalMatchMedia })

test('greeting, status and four quick actions show summary counts', async () => {
  setup()
  expect(await screen.findByText('Hallo,')).toBeTruthy()
  expect(await screen.findByText('3 ungelesene Mails in 1 Konto')).toBeTruthy()
  for (const text of ['Ungelesenes zusammenfassen', '3 Mails', 'Priorisieren', 'Was wartet auf dich?', 'Newsletter aufräumen', '2 Absender', 'Heute fällig', 'Fristen und Termine']) expect(screen.getByText(text)).toBeTruthy()
  expect(screen.getByText('Standardmodell')).toBeTruthy()
})

test('status uses singular and includes the sync time when available', async () => {
  const date = '2026-01-01T08:57:00Z'
  setup(true, '/', 1, date)
  expect(await screen.findByText(`1 ungelesene Mail in 1 Konto · Stand ${formatTime(new Date(date))}`)).toBeTruthy()
  expect(screen.getByText('1 Mail')).toBeTruthy()
})

test('without accounts offers connection instead of actions and composer', async () => {
  const router = setup(false)
  expect(await screen.findByText('Verbinde ein Konto, dann kann ich deine Mails lesen.')).toBeTruthy()
  expect(screen.queryByText('Priorisieren')).toBeNull()
  expect(screen.queryByPlaceholderText(de.chat.placeholder)).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: 'Konto verbinden' }))
  await waitFor(() => expect(router.state.location.pathname).toBe('/accounts'))
})

test('priority sends its fixed prompt and selected account', async () => {
  setup()
  fireEvent.click(await screen.findByRole('button', { name: 'Alle Konten' }))
  fireEvent.click(screen.getByRole('menuitem', { name: 'Privat' }))
  fireEvent.click(screen.getByRole('button', { name: /Priorisieren/ }))
  expect(request.text).toBe(de.quickActions.priority.prompt)
  expect(request.account_id).toBe('a')
})

test('a failed start shows a retry that sends the same text', async () => {
  setup()
  const requests: Record<string, unknown>[] = []
  globalThis.fetch = ((_url: unknown, init: RequestInit) => {
    requests.push(JSON.parse(String(init.body)) as Record<string, unknown>)
    return Promise.resolve(new Response(null, { status: 503 }))
  }) as typeof fetch
  const composer = await screen.findByPlaceholderText(de.chat.placeholder)
  fireEvent.change(composer, { target: { value: 'Was steht drin?' } })
  fireEvent.click(screen.getByRole('button', { name: 'Senden' }))
  expect((await screen.findByRole('alert')).textContent).toContain(de.errors.internal)
  fireEvent.click(screen.getByRole('button', { name: 'Noch mal versuchen' }))
  await waitFor(() => expect(requests).toHaveLength(2))
  expect(requests.map(item => item.text)).toEqual(['Was steht drin?', 'Was steht drin?'])
})

test('about displays a mail and sends its context, which can be removed', async () => {
  const router = setup(true, '/?about=mail1')
  expect(await screen.findByText('Termin')).toBeTruthy()
  expect(screen.getByText('Anna')).toBeTruthy()
  expect(screen.getByText('Privat')).toBeTruthy()
  fireEvent.change(screen.getByPlaceholderText(de.chat.placeholder), { target: { value: 'Was steht drin?' } })
  fireEvent.click(screen.getByRole('button', { name: 'Senden' }))
  expect(request.context_message_id).toBe('mail1')
  fireEvent.click(screen.getByRole('button', { name: 'Bezug entfernen' }))
  await waitFor(() => expect(router.state.location.searchStr).toBe(''))
})


test('mail reference opens its detail route', async () => {
  const router = setup(true, '/?about=mail1')
  await screen.findByText('Termin')
  fireEvent.click(screen.getByRole('button', { name: 'Mail öffnen' }))
  await waitFor(() => expect(router.state.location.pathname).toBe('/mail/mail1'))
})

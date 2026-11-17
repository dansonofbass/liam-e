import { afterEach, expect, mock, spyOn, test } from 'bun:test'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createMemoryHistory, createRootRoute, createRoute, createRouter, Outlet, RouterProvider } from '@tanstack/react-router'
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import * as sdk from '../api/generated/sdk.gen'
import { de } from '../i18n/de'
import { formatTime } from '../i18n/format'
import { Route } from '../routes/_app/index'
import { ChatSessionProvider } from './session'

const originalFetch = globalThis.fetch, originalMatchMedia = window.matchMedia
let request: Record<string, unknown>
const oneModel = [{ id: 'm', label: 'Standardmodell', description: '', is_default: true }]
function setup(accounts = true, path = '/', unread = 3, lastSync: string | null = null, displayName = 'Privat', models = oneModel) {
  window.matchMedia = (() => ({ matches: true, addEventListener() {}, removeEventListener() {} })) as unknown as typeof window.matchMedia
  globalThis.fetch = ((_url: unknown, init: RequestInit) => { request = JSON.parse(String(init.body)) as Record<string, unknown>; return Promise.resolve(new Response(new ReadableStream({ start() {} }))) }) as typeof fetch
  spyOn(sdk, 'calendarSourcesList').mockResolvedValue({ data: [] } as never)
  spyOn(sdk, 'mailSummary').mockImplementation((async () => ({ data: { accounts: accounts ? [{ id: 'a', display_name: displayName, provider: 'gmail', email_address: 'a@example.com', color_index: 0, state: 'ok' }] : [], unread_total: unread, newsletter_senders: 2, last_sync_at: lastSync } })) as never)
  spyOn(sdk, 'promptsList').mockImplementation((async () => ({ data: [] })) as never)
  spyOn(sdk, 'chatModelsList').mockImplementation((async () => ({ data: models })) as never)
  spyOn(sdk, 'mailMessageGet').mockImplementation((async () => ({ data: { id: 'mail1', account_id: 'a', color_index: 0, sender_name: 'Anna', subject: 'Termin', internal_date: null, deadline: null } })) as never)
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const root = createRootRoute({ component: () => <QueryClientProvider client={client}><ChatSessionProvider><Outlet /></ChatSessionProvider></QueryClientProvider> })
  const index = createRoute({ getParentRoute: () => root, path: '/', validateSearch: Route.options.validateSearch, component: Route.options.component })
  const accountsRoute = createRoute({ getParentRoute: () => root, path: '/accounts', component: () => <p>Konten</p> })
  const mailRoute = createRoute({ getParentRoute: () => root, path: '/mail/$messageId', component: () => <p>Mail</p> })
  const router = createRouter({ routeTree: root.addChildren([index, accountsRoute, mailRoute]), history: createMemoryHistory({ initialEntries: [path] }) })
  render(<RouterProvider router={router} />)
  return Object.assign(router, { testClient: client })
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

test('a calendar reference and composer remain available when the mail summary fails', async () => {
  setup(true, '/?calendarAbout=occurrence-test')
  spyOn(sdk, 'mailSummary').mockRejectedValue(new Error('test-only'))
  spyOn(sdk, 'calendarSourcesList').mockResolvedValue({ data: [{ id: 'work', name: 'Arbeit', is_active: true }] } as never)
  spyOn(sdk, 'calendarOccurrenceGet').mockResolvedValue({ data: { id: 'occurrence-test', source_id: 'work', title: 'Planung', start_date: '2026-11-13', end_date: '2026-11-14' } } as never)
  expect(await screen.findByText(de.chat.summaryError)).toBeTruthy()
  expect(await screen.findByRole('link', { name: 'Planung' })).toBeTruthy()
  expect(screen.getByRole('button', { name: 'Senden' })).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: 'Arbeit' }))
  fireEvent.change(screen.getByPlaceholderText(de.chat.placeholder), { target: { value: 'Was steht an?' } })
  fireEvent.click(screen.getByRole('button', { name: 'Senden' }))
  expect(request.context_occurrence_id).toBe('occurrence-test')
  expect(request.calendar_source_ids).toEqual(['work'])
})

test('a calendar reference keeps the composer visible while sources are still loading', async () => {
  setup(true, '/?calendarAbout=occurrence-test')
  spyOn(sdk, 'mailSummary').mockRejectedValue(new Error('test-only'))
  spyOn(sdk, 'calendarSourcesList').mockImplementation(() => new Promise<never>(() => {}))
  expect(await screen.findByText(de.chat.summaryError)).toBeTruthy()
  expect(screen.getByText(de.calendar.referenceLoading)).toBeTruthy()
  expect(screen.getByRole('button', { name: 'Senden' })).toBeTruthy()
})

test('active calendars keep the composer available without a mail summary or reference', async () => {
  setup()
  spyOn(sdk, 'mailSummary').mockRejectedValue(new Error('test-only'))
  spyOn(sdk, 'calendarSourcesList').mockResolvedValue({ data: [{ id: 'work', name: 'Arbeit', is_active: true }] } as never)
  expect(await screen.findByText(de.chat.summaryError)).toBeTruthy()
  expect(await screen.findByRole('button', { name: 'Senden' })).toBeTruthy()
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

const twoModels = [{ id: 'm', label: 'Standardmodell', description: 'Alltag', is_default: true }, { id: 'big', label: 'Großmodell', description: 'Gründlich', is_default: false }]

test('the model on the start page is a chip with a menu and a tooltip, like in a conversation', async () => {
  setup(true, '/', 3, null, 'Privat', twoModels)
  const chip = await screen.findByRole('button', { name: 'Standardmodell' })
  expect(chip.classList.contains('le-chip--quiet')).toBe(true)
  expect(chip.getAttribute('aria-haspopup')).toBe('menu')
  expect(chip.querySelector('.lucide-chevron-down')).toBeTruthy()
  expect(document.querySelector('.le-hint')?.textContent).not.toBe('Standardmodell')
  fireEvent.mouseEnter(chip)
  expect((await screen.findByRole('tooltip', {}, { timeout: 2000 })).textContent).toBe('Modell für diese Unterhaltung wählen')
  fireEvent.click(chip)
  expect(screen.getAllByRole('menuitem').map(item => item.textContent)).toEqual(['Standardmodell · Alltag', 'Großmodell · Gründlich'])
})

test('the model chosen on the start page travels with the first message, typed or from a quick action', async () => {
  setup(true, '/', 3, null, 'Privat', twoModels)
  fireEvent.click(await screen.findByRole('button', { name: 'Standardmodell' }))
  fireEvent.click(screen.getByRole('menuitem', { name: /Großmodell/ }))
  expect(await screen.findByRole('button', { name: 'Großmodell' })).toBeTruthy()
  expect(screen.queryByRole('menuitem')).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: /Priorisieren/ }))
  expect(request.model).toBe('big')
  expect(request.conversation_id).toBeUndefined()
  cleanup(); mock.restore()
  setup(true, '/', 3, null, 'Privat', twoModels)
  fireEvent.change(await screen.findByPlaceholderText(de.chat.placeholder), { target: { value: 'Was steht drin?' } })
  fireEvent.click(screen.getByRole('button', { name: 'Senden' }))
  expect(request.text).toBe('Was steht drin?')
  expect(request.model).toBeUndefined()
})

test('a model that is gone is named, the chip falls back to the default and there is nothing to retry', async () => {
  setup(true, '/', 3, null, 'Privat', twoModels)
  globalThis.fetch = ((_url: unknown, _init: RequestInit) => Promise.resolve(new Response(JSON.stringify({ detail: { code: 'model_unknown' } }), { status: 422 }))) as typeof fetch
  fireEvent.click(await screen.findByRole('button', { name: 'Standardmodell' }))
  fireEvent.click(screen.getByRole('menuitem', { name: /Großmodell/ }))
  fireEvent.change(await screen.findByPlaceholderText(de.chat.placeholder), { target: { value: 'Was steht drin?' } })
  fireEvent.click(screen.getByRole('button', { name: 'Senden' }))
  expect((await screen.findByRole('alert')).textContent).toBe('Dieses Modell gibt es nicht mehr. Wähle ein anderes.')
  expect(screen.queryByRole('button', { name: 'Noch mal versuchen' })).toBeNull()
  expect(await screen.findByRole('button', { name: 'Standardmodell' })).toBeTruthy()
})

test('a removed start template can be cleared before sending', async () => {
  const router = setup()
  const template = { id: 't', name: 'Testvorlage', revision_id: 'r', text: 'Test', version: 1 }
  spyOn(sdk, 'promptGet').mockImplementation((async () => ({ data: { ...template, revisions: [{ id: 'r', number: 1, content: 'Test' }] } })) as never)
  await screen.findByRole('button', { name: 'Vorlage: Standard' })
  await waitFor(() => expect(router.testClient.getQueryData(['prompts'])).toEqual([]))
  act(() => { router.testClient.setQueryData(['prompts'], [template]) })
  await waitFor(() => expect(router.testClient.getQueryData(['prompts', 't'])).toBeTruthy())
  fireEvent.click(screen.getByRole('button', { name: 'Vorlage: Standard' }))
  fireEvent.click(await screen.findByRole('menuitemradio', { name: /Testvorlage/ }))
  expect(await screen.findByRole('button', { name: 'Vorlage: Testvorlage' })).toBeTruthy()
  act(() => { router.testClient.setQueryData(['prompts'], []) })
  fireEvent.click(await screen.findByRole('button', { name: 'Standard verwenden' }))
  expect(await screen.findByRole('button', { name: 'Vorlage: Standard' })).toBeTruthy()
  fireEvent.change(screen.getByPlaceholderText(de.chat.placeholder), { target: { value: 'Was steht drin?' } })
  fireEvent.click(screen.getByRole('button', { name: 'Senden' }))
  expect(request.prompt_revision_id).toBeNull()
})

test('about displays a mail and sends its context, which can be removed', async () => {
  const router = setup(true, '/?about=mail1')
  expect(await screen.findByText('Termin')).toBeTruthy()
  expect(screen.getByText('Anna')).toBeTruthy()
  expect(screen.getByText('Gmail')).toBeTruthy()
  fireEvent.change(screen.getByPlaceholderText(de.chat.placeholder), { target: { value: 'Was steht drin?' } })
  fireEvent.click(screen.getByRole('button', { name: 'Senden' }))
  expect(request.context_message_id).toBe('mail1')
  fireEvent.click(screen.getByRole('button', { name: 'Bezug entfernen' }))
  await waitFor(() => expect(router.state.location.searchStr).toBe(''))
})


test('mail reference shows the provider when the account name is empty', async () => {
  setup(true, '/?about=mail1', 3, null, '')
  await screen.findByText('Termin')
  expect(screen.getByText('Gmail').closest('.le-chat-reference')).toBeTruthy()
})

test('mail reference opens its detail route', async () => {
  const router = setup(true, '/?about=mail1')
  await screen.findByText('Termin')
  fireEvent.click(screen.getByRole('button', { name: 'Mail öffnen' }))
  await waitFor(() => expect(router.state.location.pathname).toBe('/mail/mail1'))
})

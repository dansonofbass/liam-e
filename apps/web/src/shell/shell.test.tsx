import { afterEach, expect, mock, spyOn, test } from 'bun:test'
import { QueryClient, QueryClientProvider, QueryObserver } from '@tanstack/react-query'
import { createMemoryHistory, createRootRoute, createRoute, createRouter, RouterProvider } from '@tanstack/react-router'
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import * as sdk from '../api/generated/sdk.gen'
import { Shell, resetShellSyncForTest } from '../routes/_app'

let width = 1200
window.matchMedia = ((query: string) => ({ matches: query.includes('640') ? width >= 640 : query.includes('1024') ? width >= 1024 : query.includes('1440') ? width >= 1440 : false, media: query, addEventListener() {}, removeEventListener() {} })) as unknown as typeof window.matchMedia
const summary = { accounts: Array.from({ length: 4 }, () => ({ state: 'ok' })), unread_total: 47, last_sync_at: '2026-01-01T08:57:00' }
const conversations = [{ id: 'one', title: 'Erste Unterhaltung', updated_at: new Date().toISOString() }, { id: 'two', title: 'Zweite Unterhaltung', updated_at: new Date().toISOString() }]
function setup(path = '/', client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } })) {
  client.setQueryData(['summary'], summary)
  client.setQueryData(['conversations'], conversations)
  const root = createRootRoute({ component: Shell })
  const index = createRoute({ getParentRoute: () => root, path: '/', component: () => null })
  const chat = createRoute({ getParentRoute: () => root, path: '/chat/$conversationId', component: () => null })
  const mail = createRoute({ getParentRoute: () => root, path: '/mail', component: () => null })
  const router = createRouter({ routeTree: root.addChildren([index, chat, mail]), history: createMemoryHistory({ initialEntries: [path] }) })
  return render(<QueryClientProvider client={client}><RouterProvider router={router} /></QueryClientProvider>)
}
afterEach(() => { cleanup(); mock.restore(); resetShellSyncForTest() })
test('desktop navigation shows summary and conversations and syncs once across mounts', async () => {
  width = 1200
  const sync = spyOn(sdk, 'mailSyncAll').mockImplementation((async () => ({ data: {} })) as never)
  spyOn(sdk, 'mailSummary').mockImplementation((async () => ({ data: summary })) as never)
  const first = setup()
  expect(await screen.findByText('47')).toBeTruthy()
  expect(screen.getByRole('link', { name: /Erste Unterhaltung/ }).getAttribute('href')).toBe('/chat/one')
  expect(screen.getByRole('link', { name: /Zweite Unterhaltung/ })).toBeTruthy()
  const status = screen.getByText('4 Konten · Stand 08:57')
  const dot = status.querySelector('.le-dot.le-dot--accent')
  expect(dot?.getAttribute('aria-hidden')).toBe('true')
  expect(status.firstElementChild).toBe(dot)
  first.unmount()
  setup()
  await screen.findByText('47')
  expect(sync).toHaveBeenCalledTimes(1)
  expect(sync).toHaveBeenCalledWith({ body: { only_if_older_than_minutes: 10 } })
})
test('refreshes active messages after sync finishes or the last sync advances', async () => {
  width = 1200
  spyOn(sdk, 'mailSyncAll').mockImplementation((async () => ({ error: {} })) as never)
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } })
  const fetchMessages = mock(async () => [])
  const observer = new QueryObserver(client, { queryKey: ['messages', {}], queryFn: fetchMessages, staleTime: Infinity })
  const unsubscribe = observer.subscribe(() => {})
  setup('/', client)
  await screen.findByText('47')
  await waitFor(() => expect(fetchMessages).toHaveBeenCalledTimes(1))
  act(() => { client.setQueryData(['summary'], { ...summary, accounts: [{ state: 'syncing' }] }) })
  await screen.findByText('1 Konto · Stand 08:57')
  act(() => { client.setQueryData(['summary'], { ...summary, last_sync_at: '2026-01-01T09:00:00' }) })
  await waitFor(() => expect(fetchMessages).toHaveBeenCalledTimes(2))
  act(() => { client.setQueryData(['summary'], { ...summary, last_sync_at: '2026-01-01T09:00:00' }) })
  await act(async () => { await new Promise(resolve => setTimeout(resolve, 30)) })
  expect(fetchMessages).toHaveBeenCalledTimes(2)
  act(() => { client.setQueryData(['summary'], { ...summary, last_sync_at: '2026-01-01T09:01:00' }) })
  await waitFor(() => expect(fetchMessages).toHaveBeenCalledTimes(3))
  unsubscribe()
})
test('all twelve conversations appear as links in the sidebar', async () => {
  width = 1200
  spyOn(sdk, 'mailSyncAll').mockImplementation((async () => ({ error: {} })) as never)
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } })
  setup('/', client)
  const entries = Array.from({ length: 12 }, (_, index) => ({ id: `conversation-${index}`, title: `Unterhaltung ${index + 1}`, updated_at: new Date().toISOString() }))
  act(() => { client.setQueryData(['conversations'], entries) })
  const last = await screen.findByRole('link', { name: /Unterhaltung 12/ })
  const list = last.closest('.le-shell-conversations')
  expect(list?.querySelectorAll('a')).toHaveLength(12)
  for (const entry of entries) expect(list?.querySelector(`a[href="/chat/${entry.id}"]`)).toBeTruthy()
})
test('only conversations are inside the sidebar scroll container', async () => {
  width = 1200
  spyOn(sdk, 'mailSyncAll').mockImplementation((async () => ({ data: {} })) as never)
  spyOn(sdk, 'mailSummary').mockImplementation((async () => ({ data: summary })) as never)
  setup()
  const conversation = await screen.findByRole('link', { name: /Erste Unterhaltung/ })
  const list = conversation.closest('.le-shell-conversations')
  expect(list).toBeTruthy()
  expect(list?.contains(screen.getByRole('link', { name: /Zweite Unterhaltung/ }))).toBe(true)
  expect(list?.textContent).toContain('Unterhaltungen')
  for (const name of ['Chat', /Posteingang/, 'Konten']) expect(list?.contains(screen.getByRole('link', { name }))).toBe(false)
  expect(list?.contains(screen.getByText('4 Konten · Stand 08:57'))).toBe(false)
})
test('chat navigation and the open conversation show their current state', async () => {
  width = 1200
  spyOn(sdk, 'mailSyncAll').mockImplementation((async () => ({ data: {} })) as never)
  spyOn(sdk, 'mailSummary').mockImplementation((async () => ({ data: summary })) as never)
  setup('/')
  expect((await screen.findByRole('link', { name: 'Chat' })).getAttribute('aria-current')).toBe('page')
  cleanup()
  setup('/chat/one')
  expect((await screen.findByRole('link', { name: 'Chat' })).getAttribute('aria-current')).toBe('page')
  expect(screen.getByRole('link', { name: /Erste Unterhaltung/ }).getAttribute('aria-current')).toBe('page')
  expect(screen.getByRole('link', { name: /Zweite Unterhaltung/ }).getAttribute('aria-current')).toBeNull()
  cleanup()
  setup('/mail')
  expect((await screen.findByRole('link', { name: 'Chat' })).getAttribute('aria-current')).toBeNull()
  const css = await Bun.file(new URL('../styles/ds.css', import.meta.url)).text()
  const selected = css.match(/\.le-conv\[aria-current="page"\] \{([^}]*)\}/u)?.[1]
  expect(selected).toContain('background: var(--accent-soft)')
  expect(selected).toContain('color: var(--accent)')
})
test.each([375, 800])('drawer close button restores focus at width %i', async (screenWidth) => {
  width = screenWidth
  spyOn(sdk, 'mailSyncAll').mockImplementation((async () => ({ data: {} })) as never)
  spyOn(sdk, 'mailSummary').mockImplementation((async () => ({ data: summary })) as never)
  setup()
  const trigger = await screen.findByRole('button', { name: screenWidth < 640 ? 'Menü öffnen' : 'Unterhaltungen' })
  act(() => { trigger.focus() })
  fireEvent.click(trigger)
  expect(screen.getByRole('dialog')).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: 'Menü schließen' }))
  expect(screen.queryByRole('dialog')).toBeNull()
  expect(document.activeElement).toBe(trigger)
})
test('drawer frame has inset padding, right radii and a coarse close target', async () => {
  const css = await Bun.file(new URL('../styles/ds-app.css', import.meta.url)).text()
  const rule = css.match(/\.le-drawer \{([^}]*)\}/u)?.[1]
  for (const property of ['width: min(308px, 100vw - 48px)', 'padding: var(--space-3)', 'border-radius: 0 var(--radius-lg) var(--radius-lg) 0', 'box-shadow: var(--shadow-overlay)']) expect(rule).toContain(property)
  expect(css).toContain('@media (pointer: coarse) { .le-drawer-brand .le-icon-btn { min-width: var(--control-height-lg); min-height: var(--control-height-lg); } }')
})
test('drawer stacks its content so the sidebar footer sits at the bottom', async () => {
  const css = await Bun.file(new URL('../styles/ds-app.css', import.meta.url)).text()
  const rule = css.match(/\.le-drawer \{([^}]*)\}/u)?.[1]
  for (const property of ['display: flex', 'flex-direction: column']) expect(rule).toContain(property)
  expect(css).toContain('.le-drawer .le-shell-sidebar { flex: 1 0 auto; }')
  expect(css).toMatch(/\.le-shell-status \{[^}]*margin-top: auto/u)
})
test('mobile menu opens and closes on Escape', async () => {
  width = 375
  spyOn(sdk, 'mailSyncAll').mockImplementation((async () => ({ data: {} })) as never)
  spyOn(sdk, 'mailSummary').mockImplementation((async () => ({ data: summary })) as never)
  setup()
  fireEvent.click(await screen.findByRole('button', { name: 'Menü öffnen' }))
  expect(screen.getByRole('dialog')).toBeTruthy()
  fireEvent.keyDown(document, { key: 'Escape' })
  expect(screen.queryByRole('dialog')).toBeNull()
})

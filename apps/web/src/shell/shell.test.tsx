import { afterEach, expect, mock, spyOn, test } from 'bun:test'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createMemoryHistory, createRootRoute, createRoute, createRouter, RouterProvider } from '@tanstack/react-router'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import * as sdk from '../api/generated/sdk.gen'
import { Shell, resetShellSyncForTest } from '../routes/_app'

let width = 1200
window.matchMedia = ((query: string) => ({ matches: query.includes('640') ? width >= 640 : query.includes('1024') ? width >= 1024 : query.includes('1440') ? width >= 1440 : false, media: query, addEventListener() {}, removeEventListener() {} })) as unknown as typeof window.matchMedia
const summary = { accounts: Array.from({ length: 4 }, () => ({ state: 'ok' })), unread_total: 47, last_sync_at: '2026-01-01T08:57:00' }
const conversations = [{ id: 'one', title: 'Erste Unterhaltung', updated_at: new Date().toISOString() }, { id: 'two', title: 'Zweite Unterhaltung', updated_at: new Date().toISOString() }]
function setup(path = '/') {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } })
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
  expect(screen.getByText('4 Konten · Stand 08:57')).toBeTruthy()
  first.unmount()
  setup()
  await screen.findByText('47')
  expect(sync).toHaveBeenCalledTimes(1)
  expect(sync).toHaveBeenCalledWith({ body: { only_if_older_than_minutes: 10 } })
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

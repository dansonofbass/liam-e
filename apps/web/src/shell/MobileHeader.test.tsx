import { afterEach, expect, mock, spyOn, test } from 'bun:test'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createMemoryHistory, createRootRoute, createRoute, createRouter, RouterProvider } from '@tanstack/react-router'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import * as sdk from '../api/generated/sdk.gen'
import { useChatSession } from '../chat/session'
import { Shell, resetShellSyncForTest } from '../routes/_app'

let width = 375
window.matchMedia = ((query: string) => ({ matches: query.includes('640') ? width >= 640 : query.includes('1024') ? width >= 1024 : query.includes('1440') ? width >= 1440 : false, media: query, addEventListener() {}, removeEventListener() {} })) as unknown as typeof window.matchMedia
const summary = { accounts: [{ id: 'a', display_name: 'Privat', email_address: 'ich@example.com', provider: 'gmail', color_index: 0, state: 'ok' }], unread_total: 0, last_sync_at: null }
const conversations = [{ id: 'one', title: 'Erste Unterhaltung', account_scope_json: JSON.stringify({ account_ids: ['a'], selection: 'a' }), updated_at: new Date().toISOString() }]
function StartProbe() {
  const { composerTexts } = useChatSession()
  return <div data-testid="start" data-draft={composerTexts.new ?? ''} />
}
function ChatRoute() {
  const { setComposerText } = useChatSession()
  return <button onClick={() => setComposerText('one', 'Noch offen')}>type</button>
}
function MailRoute() {
  const { setComposerText } = useChatSession()
  return <button onClick={() => { setComposerText('new', 'Bleibt') }}>start draft</button>
}
function setup(path: string) {
  width = 375
  spyOn(sdk, 'mailSyncAll').mockImplementation((async () => ({ data: {} })) as never)
  spyOn(sdk, 'mailSummary').mockImplementation((async () => ({ data: summary })) as never)
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } })
  client.setQueryData(['summary'], summary)
  client.setQueryData(['conversations'], conversations)
  const root = createRootRoute({ component: Shell })
  const index = createRoute({ getParentRoute: () => root, path: '/', component: StartProbe })
  const chat = createRoute({ getParentRoute: () => root, path: '/chat/$conversationId', component: ChatRoute })
  const mail = createRoute({ getParentRoute: () => root, path: '/mail', component: MailRoute })
  const router = createRouter({ routeTree: root.addChildren([index, chat, mail]), history: createMemoryHistory({ initialEntries: [path] }) })
  render(<QueryClientProvider client={client}><RouterProvider router={router} /></QueryClientProvider>)
  return router
}
afterEach(() => { cleanup(); mock.restore(); resetShellSyncForTest() })
test('the phone plus carries the open conversation draft', async () => {
  const router = setup('/chat/one')
  fireEvent.click(await screen.findByRole('button', { name: 'type' }))
  fireEvent.click(screen.getByRole('button', { name: 'Neue Unterhaltung' }))
  await waitFor(() => expect(router.state.location.pathname).toBe('/'))
  const start = await screen.findByTestId('start')
  expect(start.dataset.draft).toBe('Noch offen')
})
test('the phone plus outside a conversation leaves the start draft alone', async () => {
  const router = setup('/mail')
  fireEvent.click(await screen.findByRole('button', { name: 'start draft' }))
  fireEvent.click(screen.getByRole('button', { name: 'Neue Unterhaltung' }))
  await waitFor(() => expect(router.state.location.pathname).toBe('/'))
  const start = await screen.findByTestId('start')
  expect(start.dataset.draft).toBe('Bleibt')
})
// The router matches paths case-insensitively; the phone plus reads the conversation from the match.
test('the phone plus carries state from a conversation path in any spelling', async () => {
  const router = setup('/CHAT/one')
  fireEvent.click(await screen.findByRole('button', { name: 'type' }))
  fireEvent.click(screen.getByRole('button', { name: 'Neue Unterhaltung' }))
  await waitFor(() => expect(router.state.location.pathname).toBe('/'))
  const start = await screen.findByTestId('start')
  expect(start.dataset.draft).toBe('Noch offen')
})

import { afterEach, expect, test } from 'bun:test'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createMemoryHistory, createRootRoute, createRoute, createRouter, Outlet, RouterProvider } from '@tanstack/react-router'
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { ChatHeader } from './ChatHeader'
import { ChatSessionProvider, useChatSession } from './session'

const originalMatchMedia = window.matchMedia
afterEach(() => { cleanup(); window.matchMedia = originalMatchMedia })
function StartProbe() {
  const { scope, composerTexts } = useChatSession()
  return <div data-testid="start" data-scope={scope ?? 'all'} data-draft={composerTexts.new ?? ''} />
}
function TypeDraft() {
  const { setComposerText } = useChatSession()
  return <button onClick={() => setComposerText('one', 'Noch offen')}>type</button>
}
function setup(mobile: boolean, conversation = false) {
  window.matchMedia = (() => ({ matches: !mobile, addEventListener() {}, removeEventListener() {} })) as unknown as typeof window.matchMedia
  const client = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity } } })
  client.setQueryData(['conversations'], [{ id: 'one', title: 'Eine lange Unterhaltung', account_scope_json: JSON.stringify({ account_ids: ['a'], selection: 'a' }) }])
  const root = createRootRoute({ component: () => <QueryClientProvider client={client}><ChatSessionProvider><ChatHeader conversationId={conversation ? 'one' : undefined}><span>Modell</span></ChatHeader><Outlet /></ChatSessionProvider></QueryClientProvider> })
  const index = createRoute({ getParentRoute: () => root, path: '/', component: StartProbe })
  const chat = createRoute({ getParentRoute: () => root, path: '/chat/$conversationId', component: TypeDraft })
  const router = createRouter({ routeTree: root.addChildren([index, chat]), history: createMemoryHistory({ initialEntries: [conversation ? '/chat/one' : '/'] }) })
  render(<RouterProvider router={router} />)
  return router
}
test('desktop header shows the conversation crumb and starts a new conversation', async () => {
  const router = setup(false, true)
  expect(await screen.findByText('Chat')).toBeTruthy()
  expect(screen.getByTitle('Eine lange Unterhaltung')).toBeTruthy()
  const button = screen.getByRole('button', { name: 'Neue Unterhaltung' })
  fireEvent.keyDown(document.body, { key: 'Tab' })
  act(() => button.focus())
  expect((await screen.findByRole('tooltip')).textContent).toBe('Startet eine neue Unterhaltung.')
  fireEvent.click(button)
  await waitFor(() => expect(router.state.location.pathname).toBe('/'))
})
test('desktop restart carries the conversation account and unsent text to the start page', async () => {
  const router = setup(false, true)
  fireEvent.click(await screen.findByRole('button', { name: 'type' }))
  fireEvent.click(screen.getByRole('button', { name: 'Neue Unterhaltung' }))
  await waitFor(() => expect(router.state.location.pathname).toBe('/'))
  const start = await screen.findByTestId('start')
  expect(start.dataset.scope).toBe('a')
  expect(start.dataset.draft).toBe('Noch offen')
})
test('start header shows chat; mobile does not render its crumb or button', async () => {
  setup(false)
  expect(await screen.findByText('Chat')).toBeTruthy()
  expect(screen.getByRole('button', { name: 'Neue Unterhaltung' })).toBeTruthy()
  cleanup()
  setup(true)
  expect(await screen.findByText('Modell')).toBeTruthy()
  expect(screen.queryByText('Chat')).toBeNull()
  expect(screen.queryByRole('button', { name: 'Neue Unterhaltung' })).toBeNull()
})

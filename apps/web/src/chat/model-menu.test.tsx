// i18n-exempt: synthetic API fixtures and route paths.
import { afterEach, expect, mock, spyOn, test } from 'bun:test'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createMemoryHistory, createRootRoute, createRoute, createRouter, Outlet, RouterProvider } from '@tanstack/react-router'
import { cleanup, render, screen } from '@testing-library/react'
import * as sdk from '../api/generated/sdk.gen'
import type { ChatModelOut, ConversationOut } from '../api/generated/types.gen'
import { I18nProvider } from '../i18n/I18n'
import { ModelMenu } from './ModelMenu'
import { ChatSessionProvider } from './session'

const models: ChatModelOut[] = [
  { id: 'mistral-small-latest', label: 'Mistral Small', description: '', is_default: true, is_app_default: false, group: 'general', availability: 'available' },
  { id: 'mistral-medium-latest', label: 'Mistral Medium', description: '', is_default: false, is_app_default: true, group: 'general', availability: 'available' },
  { id: 'mistral-large-latest', label: 'Mistral Large', description: '', is_default: false, is_app_default: false, group: 'general', availability: 'available' },
]

const conversations: ConversationOut[] = [
  {
    id: 'legacy',
    title: 'Altbestand',
    model: '',
    prompt_revision_id: null,
    version: 1,
    account_scope_json: JSON.stringify({ account_ids: ['a'], selection: null }),
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
  },
  {
    id: 'explicit',
    title: 'Bestehend',
    model: 'mistral-large-latest',
    prompt_revision_id: null,
    version: 1,
    account_scope_json: JSON.stringify({ account_ids: ['a'], selection: null }),
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
  },
]

function renderMenu(props: { conversationId?: string; model?: string }) {
  spyOn(sdk, 'chatModelsList').mockResolvedValue({ data: models } as never)
  spyOn(sdk, 'chatConversationsList').mockResolvedValue({ data: conversations } as never)
  const query = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } })
  const root = createRootRoute({
    component: () => (
      <I18nProvider locale="de">
        <QueryClientProvider client={query}>
          <ChatSessionProvider>
            <Outlet />
          </ChatSessionProvider>
        </QueryClientProvider>
      </I18nProvider>
    ),
  })
  const page = createRoute({ getParentRoute: () => root, path: '/', component: () => <ModelMenu {...props} /> })
  const router = createRouter({ routeTree: root.addChildren([page]), history: createMemoryHistory({ initialEntries: ['/'] }) })
  render(<RouterProvider router={router} />)
}

afterEach(() => { cleanup(); mock.restore() })

test('chat start shows effective default while legacy empty conversation shows app default and explicit keeps its model', async () => {
  renderMenu({})
  expect(await screen.findByRole('button', { name: 'Mistral Small' })).toBeTruthy()
  cleanup()

  renderMenu({ conversationId: 'legacy' })
  expect(await screen.findByRole('button', { name: 'Mistral Medium' })).toBeTruthy()
  cleanup()

  renderMenu({ conversationId: 'explicit' })
  expect(await screen.findByRole('button', { name: 'Mistral Large' })).toBeTruthy()
})

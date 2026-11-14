import { describe, expect, test } from 'bun:test'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { ChatSessionProvider } from '../../chat/session'
import { createMemoryHistory, createRootRouteWithContext, createRoute, createRouter, RouterProvider } from '@tanstack/react-router'
import { render, screen, waitFor } from '@testing-library/react'
import { landingPath } from '../../landing'
import type { RouterContext } from '../__root'
import { Route } from './index'

function renderRouter(withMail: boolean) {
  const root = createRootRouteWithContext<RouterContext>()()
  const index = createRoute({ getParentRoute: () => root, path: '/', staticData: Route.options.staticData, beforeLoad: Route.options.beforeLoad as (args: { context: RouterContext }) => void, component: Route.options.component })
  const mail = createRoute({ getParentRoute: () => root, path: '/mail', staticData: { landing: 1 }, component: () => <div>Mail test page</div> })
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const router = createRouter({
    routeTree: root.addChildren(withMail ? [index, mail] : [index]),
    history: createMemoryHistory({ initialEntries: ['/'] }),
    context: { queryClient: client, landingPath: (): string | undefined => landingPath(router) },
  })
  render(<QueryClientProvider client={client}><ChatSessionProvider><RouterProvider router={router} /></ChatSessionProvider></QueryClientProvider>)
  return router
}

describe('start page landing', () => {
  test('stays on the start page when it is the only claim', async () => {
    const router = renderRouter(false)
    expect(await screen.findByText('Hallo,')).toBeTruthy()
    expect(router.state.location.pathname).toBe('/')
  })

  test('redirects to a higher ranked landing claim', async () => {
    const router = renderRouter(true)
    await waitFor(() => expect(router.state.location.pathname).toBe('/mail'))
    expect(await screen.findByText('Mail test page')).toBeTruthy()
  })
})

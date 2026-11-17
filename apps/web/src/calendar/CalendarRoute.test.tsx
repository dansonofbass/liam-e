import { afterEach, expect, mock, spyOn, test } from 'bun:test'
import { cleanup, render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createMemoryHistory, createRootRoute, createRoute, createRouter, Outlet, RouterProvider } from '@tanstack/react-router'
import * as sdk from '../api/generated/sdk.gen'
import { Route as CalendarRoute } from '../routes/_app/calendar'
import { Route as CalendarIndexRoute } from '../routes/_app/calendar/index'
import { de } from '../i18n/de'

const originalMatchMedia = window.matchMedia
afterEach(() => { cleanup(); mock.restore(); window.matchMedia = originalMatchMedia })

for (const desktop of [true, false]) {
  test(`calendar index shows its selection hint only in the desktop detail pane: ${desktop}`, async () => {
    window.matchMedia = ((query: string) => ({ matches: desktop && ['(min-width: 640px)', '(min-width: 1024px)'].includes(query), addEventListener() {}, removeEventListener() {} })) as unknown as typeof window.matchMedia
    spyOn(sdk, 'calendarSourcesList').mockResolvedValue({ data: [] } as never)
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const root = createRootRoute({ component: () => <QueryClientProvider client={client}><Outlet /></QueryClientProvider> })
    const calendar = createRoute({ getParentRoute: () => root, path: '/calendar', component: CalendarRoute.options.component })
    const index = createRoute({ getParentRoute: () => calendar, path: '/', component: CalendarIndexRoute.options.component })
    const router = createRouter({ routeTree: root.addChildren([calendar.addChildren([index])]), history: createMemoryHistory({ initialEntries: ['/calendar'] }) })
    render(<RouterProvider router={router} />)
    expect(await screen.findByText(de.calendar.unavailable)).toBeTruthy()
    expect(screen.getByRole('heading', { name: de.calendar.title })).toBeTruthy()
    if (desktop) expect((await screen.findByText(de.calendar.select)).classList.contains('le-calendar-detail')).toBe(true)
    else expect(screen.queryByText(de.calendar.select)).toBeNull()
  })
}

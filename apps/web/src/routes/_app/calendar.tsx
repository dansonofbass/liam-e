// i18n-exempt: router paths and class names.
import { createFileRoute, Outlet, useLocation } from '@tanstack/react-router'
import { CalendarView } from '../../calendar/CalendarView'
import { parseSearch } from '../../calendar/url'
import { useBreakpoint } from '../../shell/useBreakpoint'

export const Route = createFileRoute('/_app/calendar')({ validateSearch: (search: Record<string, unknown>): { view?: ReturnType<typeof parseSearch>['view']; date?: string } => {
  const parsed = parseSearch(search, typeof window !== 'undefined' && !window.matchMedia('(min-width: 640px)').matches)
  return { view: search.view === undefined ? undefined : parsed.view, date: search.date === undefined ? undefined : parsed.date }
}, component: Calendar })
function Calendar() {
  const breakpoint = useBreakpoint()
  const path = useLocation({ select: location => location.pathname })
  const split = breakpoint === 'desktop' || breakpoint === 'wide'
  return <div className="le-calendar">{(split || path === '/calendar') && <CalendarView />}{(split || path !== '/calendar') && <Outlet />}</div>
}

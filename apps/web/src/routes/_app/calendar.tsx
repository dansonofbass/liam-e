// i18n-exempt: router paths and class names.
import { createFileRoute, Outlet, useLocation } from '@tanstack/react-router'
import { CalendarAgenda } from '../../calendar/CalendarPage'
import { useBreakpoint } from '../../shell/useBreakpoint'

export const Route = createFileRoute('/_app/calendar')({ component: Calendar })
function Calendar() {
  const breakpoint = useBreakpoint()
  const path = useLocation({ select: location => location.pathname })
  const split = breakpoint === 'desktop' || breakpoint === 'wide'
  return <div className="le-calendar">{(split || path === '/calendar') && <CalendarAgenda />}{(split || path !== '/calendar') && <Outlet />}</div>
}

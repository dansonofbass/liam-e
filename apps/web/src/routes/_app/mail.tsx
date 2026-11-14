import { createFileRoute, Outlet, useLocation, useNavigate } from '@tanstack/react-router'
import { de } from '../../i18n/de'
import { inboxSearchSchema } from '../../mail/filters'
import { MailList } from '../../mail/MailList'
import { useBreakpoint } from '../../shell/useBreakpoint'

export const Route = createFileRoute('/_app/mail')({ validateSearch: inboxSearchSchema, component: Inbox })
function Inbox() {
  const breakpoint = useBreakpoint()
  const location = useLocation()
  const navigate = useNavigate()
  const split = breakpoint === 'desktop' || breakpoint === 'wide'
  const list = <section aria-label={de.inbox.mails} className="le-inbox-list"><MailList onOpen={id => { void navigate({ href: `/mail/${encodeURIComponent(id)}${location.searchStr}` }) }} /></section>
  return <div className="le-inbox">{(split || location.pathname === '/mail') && list}{split ? <div className="le-inbox-reading"><Outlet /></div> : location.pathname !== '/mail' ? <Outlet /> : null}</div>
}

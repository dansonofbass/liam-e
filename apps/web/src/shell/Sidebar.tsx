import { Link, useLocation } from '@tanstack/react-router'
import { useQuery } from '@tanstack/react-query'
import { conversationsQuery, summaryQuery } from '../api/queries'
import { Icon, IconButton, NavItem } from '../ds'
import { de } from '../i18n/de'
import { formatListDate, formatStand } from '../i18n/format'

export function Conversations({ onNavigate }: { onNavigate?: () => void }) {
  const { data = [] } = useQuery(conversationsQuery())
  const path = useLocation({ select: location => location.pathname })
  return <><div className="le-side-label">{de.shell.conversations}</div>{data.slice(0, 8).map(c => <Link key={c.id} to="/chat/$conversationId" params={{ conversationId: c.id }} className="le-conv" aria-current={path === `/chat/${c.id}` ? 'true' : undefined} onClick={onNavigate}><span className="le-conv-title">{c.title}</span><span className="le-conv-when">{formatListDate(new Date(c.updated_at), new Date())}</span></Link>)}</>
}
export function Sidebar({ collapsed = false, hideBrand = false, onConversations, onNavigate }: { collapsed?: boolean; hideBrand?: boolean; onConversations?: () => void; onNavigate?: () => void }) {
  const { data } = useQuery(summaryQuery())
  const path = useLocation({ select: location => location.pathname })
  const count = data?.accounts.length ?? 0
  return <div className="le-shell-sidebar" onClick={event => { if ((event.target as HTMLElement).closest('a')) onNavigate?.() }}>
    {!hideBrand && <div className="le-brand"><span className="le-mark"><Icon name="sparkle" /></span>{!collapsed && de.assistant.name}</div>}
    <NavItem to="/" icon="message-circle" label={de.shell.chat} tip={de.shell.chatTip} collapsed={collapsed} current={path === '/' || path.startsWith('/chat/')} />
    <NavItem to="/mail" icon="inbox" label={de.shell.inbox} tip={de.shell.inboxTip} badge={data?.unread_total || undefined} collapsed={collapsed} />
    <NavItem to="/accounts" icon="at-sign" label={de.shell.accounts} tip={de.shell.accountsTip} collapsed={collapsed} />
    {collapsed ? <IconButton label={de.shell.conversations} icon="message-circle" onClick={onConversations} /> : <Conversations onNavigate={onNavigate} />}
    {!collapsed && data && <small className="le-muted le-shell-status"><span className="le-dot le-dot--accent" aria-hidden="true" />{data.last_sync_at ? formatStand(count, new Date(data.last_sync_at)) : de.shell.accountCount(count)}</small>}
  </div>
}

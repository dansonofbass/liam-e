import { Link, useLocation } from '@tanstack/react-router'
import { useQuery } from '@tanstack/react-query'
import { conversationsQuery, summaryQuery } from '../api/queries'
import { BrandMark, NavButton, NavItem } from '../ds'
import { useI18n } from '../i18n/I18n'
import { formatListDate, formatStand } from '../i18n/format'
import { ThemeMenu } from './ThemeMenu'

export function Conversations({ onNavigate }: { onNavigate?: () => void }) {
  const { texts, locale } = useI18n()
  const { data = [] } = useQuery(conversationsQuery())
  const path = useLocation({ select: location => location.pathname })
  return <><div className="le-side-label">{texts.shell.conversations}</div>{data.map(c => <Link key={c.id} to="/chat/$conversationId" params={{ conversationId: c.id }} className="le-conv" aria-current={path === `/chat/${c.id}` ? 'true' : undefined} onClick={onNavigate}><span className="le-conv-title">{c.title}</span><span className="le-conv-when">{formatListDate(new Date(c.updated_at), new Date(), undefined, locale)}</span></Link>)}</>
}
export function Sidebar({ collapsed = false, hideBrand = false, onConversations, onNavigate }: { collapsed?: boolean; hideBrand?: boolean; onConversations?: () => void; onNavigate?: () => void }) {
  const { texts, locale } = useI18n()
  const { data } = useQuery(summaryQuery())
  const path = useLocation({ select: location => location.pathname })
  const count = data?.accounts.length ?? 0
  return <div className="le-shell-sidebar" onClick={event => { if ((event.target as HTMLElement).closest('a')) onNavigate?.() }}>
    {!hideBrand && <div className="le-brand"><BrandMark />{!collapsed && texts.assistant.name}</div>}
    <NavItem to="/" icon="message-circle" label={texts.shell.chat} tip={texts.shell.chatTip} collapsed={collapsed} current={path === '/' || path.startsWith('/chat/')} />
    <NavItem to="/mail" icon="inbox" label={texts.shell.inbox} tip={texts.shell.inboxTip} badge={data?.unread_total || undefined} badgeLabel={data?.unread_total ? texts.shell.unread(data.unread_total) : undefined} collapsed={collapsed} />
    <NavItem to="/calendar" icon="clock" label={texts.calendar.title} tip={texts.calendar.tip} collapsed={collapsed} current={path.startsWith('/calendar')} />
    <NavItem to="/tasks" icon="check" label={texts.tasks.title} tip={texts.tasks.tip} collapsed={collapsed} current={path === '/tasks' || path.startsWith('/tasks/')} />
    <NavItem to="/accounts" icon="at-sign" label={texts.shell.accounts} tip={texts.shell.accountsTip} collapsed={collapsed} />
    <NavItem to="/settings" icon="pencil" label={texts.prompts.settings} tip={texts.prompts.settingsTip} collapsed={collapsed} current={path.startsWith('/settings')} />
    {collapsed ? <NavButton icon="messages-square" label={texts.shell.conversations} tip={texts.shell.conversationsTip} collapsed onClick={onConversations} /> :<div className="le-shell-conversations"><Conversations onNavigate={onNavigate} /></div>}
    <div className={`le-shell-status${collapsed ? ' le-shell-status--collapsed' : ''}`}>{!collapsed && data && <small className="le-muted le-shell-stand"><span className="le-dot le-dot--accent" aria-hidden="true" />{data.last_sync_at ? formatStand(count, new Date(data.last_sync_at), undefined, locale) : texts.shell.accountCount(count)}</small>}<ThemeMenu placement={collapsed ? 'up-start' : 'up-end'} /></div>
  </div>
}

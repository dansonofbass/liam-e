import { createFileRoute, Outlet, useLocation } from '@tanstack/react-router'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import { mailSyncAll } from '../api/generated/sdk.gen'
import { summaryQuery } from '../api/queries'
import { AppShell, Drawer, Icon, IconButton } from '../ds'
import { de } from '../i18n/de'
import { Sidebar, Conversations } from '../shell/Sidebar'
import { MobileHeader } from '../shell/MobileHeader'
import { useBreakpoint } from '../shell/useBreakpoint'
import { ChatSessionProvider } from '../chat/session'

let started = false
export function resetShellSyncForTest() { started = false }
export function Shell() {
  const breakpoint = useBreakpoint()
  const [open, setOpen] = useState(false)
  const client = useQueryClient()
  const { data: summary } = useQuery(summaryQuery())
  const previousSummary = useRef<{ syncing: boolean, lastSync: number | null } | null>(null)
  useEffect(() => {
    if (!summary) return
    const syncing = summary.accounts.some(account => account.state === 'syncing')
    const parsed = summary.last_sync_at ? Date.parse(summary.last_sync_at) : NaN
    const lastSync = Number.isNaN(parsed) ? null : parsed
    const previous = previousSummary.current
    if (previous && ((previous.syncing && !syncing) || (lastSync !== null && (previous.lastSync === null || lastSync > previous.lastSync)))) {
      void client.invalidateQueries({ queryKey: ['messages'] })
    }
    previousSummary.current = { syncing, lastSync }
  }, [client, summary])
  const path = useLocation({ select: location => location.pathname })
  useEffect(() => {
    if (started) return
    started = true
    void mailSyncAll({ body: { only_if_older_than_minutes: 10 } }).then(result => { if (!result.error) void client.invalidateQueries({ queryKey: summaryQuery().queryKey }) }).catch(() => {})
  }, [client])
  const mobile = breakpoint === 'mobile', tablet = breakpoint === 'tablet'
  const title = path.startsWith('/mail') ? de.shell.inbox : path.startsWith('/accounts') ? de.shell.accounts : de.shell.chat
  return <ChatSessionProvider><AppShell sidebar={mobile ? null : <Sidebar collapsed={tablet} onConversations={() => setOpen(true)} />} header={mobile && !(path.startsWith('/mail/') && path !== '/mail/') ? <MobileHeader title={title} onMenu={() => setOpen(true)} /> : undefined}><div key={path === '/' || path.startsWith('/chat/') ? 'chat' : path.startsWith('/mail') ? 'mail' : path} className="le-page-fade"><Outlet /></div></AppShell><Drawer open={open} onClose={() => setOpen(false)} label={mobile ? de.shell.menu : de.shell.conversations}><div className="le-brand le-drawer-brand"><span className="le-mark"><Icon name="sparkle" /></span><span className="le-grow">{de.assistant.name}</span><IconButton icon="x" label={de.shell.closeMenu} onClick={() => setOpen(false)} /></div>{mobile ? <Sidebar hideBrand onNavigate={() => setOpen(false)} /> : <Conversations onNavigate={() => setOpen(false)} />}</Drawer></ChatSessionProvider>
}
export const Route = createFileRoute('/_app')({ component: Shell })

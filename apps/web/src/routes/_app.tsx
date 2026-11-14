import { createFileRoute, Outlet, useLocation } from '@tanstack/react-router'
import { useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { mailSyncAll } from '../api/generated/sdk.gen'
import { summaryQuery } from '../api/queries'
import { AppShell, Drawer } from '../ds'
import { de } from '../i18n/de'
import { Sidebar, Conversations } from '../shell/Sidebar'
import { MobileHeader } from '../shell/MobileHeader'
import { useBreakpoint } from '../shell/useBreakpoint'

let started = false
export function resetShellSyncForTest() { started = false }
export function Shell() {
  const breakpoint = useBreakpoint()
  const [open, setOpen] = useState(false)
  const client = useQueryClient()
  const path = useLocation({ select: location => location.pathname })
  useEffect(() => {
    if (started) return
    started = true
    void mailSyncAll({ body: { only_if_older_than_minutes: 10 } }).then(result => { if (!result.error) void client.invalidateQueries({ queryKey: summaryQuery().queryKey }) }).catch(() => {})
  }, [client])
  const mobile = breakpoint === 'mobile', tablet = breakpoint === 'tablet'
  const title = path.startsWith('/mail') ? de.shell.inbox : path.startsWith('/accounts') ? de.shell.accounts : de.shell.chat
  return <><AppShell sidebar={mobile ? null : <Sidebar collapsed={tablet} onConversations={() => setOpen(true)} />} header={mobile ? <MobileHeader title={title} onMenu={() => setOpen(true)} /> : undefined}><div key={path} className="le-page-fade"><Outlet /></div></AppShell><Drawer open={open} onClose={() => setOpen(false)} label={mobile ? de.shell.openMenu : de.shell.conversations}>{mobile ? <Sidebar onNavigate={() => setOpen(false)} /> : <Conversations onNavigate={() => setOpen(false)} />}</Drawer></>
}
export const Route = createFileRoute('/_app')({ component: Shell })

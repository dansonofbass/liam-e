import { useQuery } from '@tanstack/react-query'
import { useNavigate } from '@tanstack/react-router'
import type { ReactNode } from 'react'
import { conversationsQuery } from '../api/queries'
import { IconButton } from '../ds'
import { de } from '../i18n/de'
import { useBreakpoint } from '../shell/useBreakpoint'

export function ChatHeader({ conversationId, children }: { conversationId?: string; children: ReactNode }) {
  const mobile = useBreakpoint() === 'mobile'
  const navigate = useNavigate()
  const { data } = useQuery({ ...conversationsQuery(), enabled: Boolean(conversationId) && !mobile })
  const title = data?.find(conversation => conversation.id === conversationId)?.title
  return <div className={mobile ? 'le-chat-header' : 'le-topbar le-chat-topbar'}>
    {!mobile && <div className="le-crumb le-grow"><span>{de.shell.chat}</span>{title && <><span className="le-crumb-sep">/</span><span className="le-chat-crumb-title" title={title}>{title}</span></>}</div>}
    {children}
    {!mobile && <IconButton icon="plus" label={de.shell.newConversation} tip={de.shell.newConversationTip} onClick={() => { void navigate({ to: '/' }) }} />}
  </div>
}

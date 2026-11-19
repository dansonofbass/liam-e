import { useQuery } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { conversationsQuery } from '../api/queries'
import { IconButton } from '../ds'
import { useI18n } from '../i18n/I18n'
import { useBreakpoint } from '../shell/useBreakpoint'
import { useRestartConversation } from './session'

export function ChatHeader({ conversationId, modelMenu, children }: { conversationId?: string; modelMenu?: ReactNode; children: ReactNode }) {
  const { texts } = useI18n()
  const mobile = useBreakpoint() === 'mobile'
  const restart = useRestartConversation(conversationId)
  const { data } = useQuery({ ...conversationsQuery(), enabled: Boolean(conversationId) && !mobile })
  const title = data?.find(conversation => conversation.id === conversationId)?.title
  return <div className={mobile ? 'le-chat-header' : 'le-topbar le-chat-topbar'}>
    {!mobile && <div className="le-crumb le-grow"><span>{texts.shell.chat}</span>{title && <><span className="le-crumb-sep">/</span><span className="le-chat-crumb-title" title={title}>{title}</span></>}</div>}
    {children}
    {mobile ? modelMenu : <div className="le-chat-model-actions">{modelMenu}<IconButton icon="plus" label={texts.shell.newConversation} tip={texts.shell.newConversationTip} onClick={restart} /></div>}
  </div>
}

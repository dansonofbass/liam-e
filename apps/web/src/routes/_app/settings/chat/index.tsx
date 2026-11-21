import { createFileRoute } from '@tanstack/react-router'
import { ChatAccountSettings } from '../../../../settings/ChatAccountSettings'
import { ChatModelSettings } from '../../../../settings/ChatModelSettings'

function ChatSettings() {
  return <>
    <ChatModelSettings />
    <ChatAccountSettings />
  </>
}

export const Route = createFileRoute('/_app/settings/chat/')({ component: ChatSettings })

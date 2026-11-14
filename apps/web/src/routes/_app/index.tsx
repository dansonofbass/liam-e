import { createFileRoute, redirect, useNavigate } from '@tanstack/react-router'
import { useEffect, useState } from 'react'
import { ChatComposer } from '../../chat/Conversation'
import { useChatSession } from '../../chat/session'
import { de } from '../../i18n/de'
export const Route = createFileRoute('/_app/')({
  staticData: { landing: true },
  beforeLoad: ({ context }) => {
    const to = context.landingPath()
    if (to !== undefined && to !== '' && to !== '/') {
      // oxlint-disable-next-line typescript/only-throw-error -- TanStack Router's redirect is thrown, by design
      throw redirect({ href: to })
    }
  },
  component: Greeting,
})
function Greeting() {
  const { state } = useChatSession()
  const navigate = useNavigate()
  const [started, setStarted] = useState(false)
  useEffect(() => {
    if (started && state.conversationId) {
      setStarted(false)
      void navigate({ to: '/chat/$conversationId', params: { conversationId: state.conversationId } })
    }
  }, [started, state.conversationId, navigate])
  return <div className="le-chat-view"><div className="le-chat-messages"><h1 className="display le-greeting">{de.chat.greetingFirst}<br /><span>{de.chat.greetingSecond}</span></h1></div><div className="le-chat-composer"><ChatComposer onSend={() => setStarted(true)} /></div></div>
}

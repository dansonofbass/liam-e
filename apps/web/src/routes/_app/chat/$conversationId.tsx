import { createFileRoute } from '@tanstack/react-router'
import { Conversation } from '../../../chat/Conversation'

export const Route = createFileRoute('/_app/chat/$conversationId')({ component: ConversationPage })
function ConversationPage() {
  const { conversationId } = Route.useParams()
  return <Conversation conversationId={conversationId} />
}

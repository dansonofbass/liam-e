import { createFileRoute } from '@tanstack/react-router'
import { MailView } from '../../../mail/MailView'

export const Route = createFileRoute('/_app/mail/$messageId')({ component: Message })
function Message() {
  const { messageId } = Route.useParams()
  return <MailView id={messageId} />
}

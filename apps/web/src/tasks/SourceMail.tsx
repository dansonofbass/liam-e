// i18n-exempt: route path and CSS class.
import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { chatMailReferenceQuery, MessageNotFoundError, messageQuery } from '../api/queries'
import { useI18n } from '../i18n/I18n'

export function SourceMail({ id }: { id: string }) {
  const query = useQuery({ ...messageQuery(id), retry: false })
  return <MailLink id={id} query={query} />
}

export function ChatSourceMail({ id, version, contextId }: { id: string; version?: number; contextId?: string }) {
  const query = useQuery(chatMailReferenceQuery(id, contextId ? version : undefined, contextId))
  return <MailLink id={id} query={query} />
}

function MailLink({ id, query }: { id: string; query: { isPending: boolean; isError: boolean; error: Error | null } }) {
  const { texts } = useI18n()
  if (query.isPending) return <span role="status">{texts.tasks.mailLoading}</span>
  if (query.error instanceof MessageNotFoundError) return <span>{texts.tasks.unavailableMail}</span>
  if (query.isError) return <span>{texts.tasks.mailError}</span>
  return <Link className="le-link" to="/mail/$messageId" params={{ messageId: id }} search={{}}>{texts.tasks.openMail}</Link>
}

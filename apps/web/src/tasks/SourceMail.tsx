// i18n-exempt: route path and CSS class.
import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { MessageNotFoundError, messageQuery } from '../api/queries'
import { de } from '../i18n/de'

export function SourceMail({ id }: { id: string }) {
  const query = useQuery({ ...messageQuery(id), retry: false })
  if (query.isPending) return <span role="status">{de.tasks.mailLoading}</span>
  if (query.error instanceof MessageNotFoundError) return <span>{de.tasks.unavailableMail}</span>
  if (query.isError) return <span>{de.tasks.mailError}</span>
  return <Link className="le-link" to="/mail/$messageId" params={{ messageId: id }} search={{}}>{de.tasks.openMail}</Link>
}

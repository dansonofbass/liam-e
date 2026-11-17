// i18n-exempt: route path and CSS class.
import { useQuery } from '@tanstack/react-query'
import { MessageNotFoundError, messageQuery } from '../api/queries'
import { de } from '../i18n/de'

export function SourceMail({ id }: { id: string }) {
  const query = useQuery({ ...messageQuery(id), retry: false })
  if (query.isPending) return <span role="status">{de.tasks.mailLoading}</span>
  if (query.error instanceof MessageNotFoundError) return <span>{de.tasks.unavailableMail}</span>
  if (query.isError) return <span>{de.tasks.mailError}</span>
  return <a className="le-link" href={`/mail/${encodeURIComponent(id)}`}>{de.tasks.openMail}</a>
}

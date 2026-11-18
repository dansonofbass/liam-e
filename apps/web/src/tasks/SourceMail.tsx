// i18n-exempt: route path and CSS class.
import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { MessageNotFoundError, messageQuery } from '../api/queries'
import { useI18n } from '../i18n/I18n'

export function SourceMail({ id }: { id: string }) {
  const { texts } = useI18n()
  const query = useQuery({ ...messageQuery(id), retry: false })
  if (query.isPending) return <span role="status">{texts.tasks.mailLoading}</span>
  if (query.error instanceof MessageNotFoundError) return <span>{texts.tasks.unavailableMail}</span>
  if (query.isError) return <span>{texts.tasks.mailError}</span>
  return <Link className="le-link" to="/mail/$messageId" params={{ messageId: id }} search={{}}>{texts.tasks.openMail}</Link>
}

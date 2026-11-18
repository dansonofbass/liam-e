import { createFileRoute } from '@tanstack/react-router'
import { useI18n } from '../../../i18n/I18n'

export const Route = createFileRoute('/_app/mail/')({ component: InboxPlaceholder })

function InboxPlaceholder() {
  const { texts } = useI18n()
  return <p className="le-hint le-inbox-select">{texts.inbox.select}</p>
}

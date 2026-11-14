import { createFileRoute } from '@tanstack/react-router'
import { de } from '../../../i18n/de'

export const Route = createFileRoute('/_app/mail/')({ component: () => <p className="le-hint le-inbox-select">{de.inbox.select}</p> })

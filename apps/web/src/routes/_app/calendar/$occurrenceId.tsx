// i18n-exempt: router path.
import { createFileRoute } from '@tanstack/react-router'
import { CalendarDetail } from '../../../calendar/CalendarPage'
export const Route = createFileRoute('/_app/calendar/$occurrenceId')({ component: Detail })
function Detail() { return <CalendarDetail id={Route.useParams().occurrenceId} /> }

// i18n-exempt: router path and CSS classes.
import { createFileRoute } from '@tanstack/react-router'
import { de } from '../../../i18n/de'

export const Route = createFileRoute('/_app/calendar/')({ component: () => <p className="le-hint le-calendar-detail">{de.calendar.select}</p> })

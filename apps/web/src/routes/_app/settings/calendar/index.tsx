import { createFileRoute } from '@tanstack/react-router'
import { CalendarSettings } from '../../../../settings/CalendarSettings'

export const Route = createFileRoute('/_app/settings/calendar/')({ component: CalendarSettings })

// i18n-exempt: route path.
import { createFileRoute } from '@tanstack/react-router'
import { SwipeSettings } from '../../../../settings/SwipeSettings'
export const Route = createFileRoute('/_app/settings/controls/')({ component: SwipeSettings })

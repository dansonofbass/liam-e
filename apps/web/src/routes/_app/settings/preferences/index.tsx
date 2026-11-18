// i18n-exempt: route path.
import { createFileRoute } from '@tanstack/react-router'
import { Preferences } from '../../../../settings/Preferences'
export const Route = createFileRoute('/_app/settings/preferences/')({ component: Preferences })

// i18n-exempt: route path.
import { createFileRoute } from '@tanstack/react-router'
import { PreferenceEditor } from '../../../../settings/Preferences'
export const Route = createFileRoute('/_app/settings/preferences/new')({ component: PreferenceEditor })

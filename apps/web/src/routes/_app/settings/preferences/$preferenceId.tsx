// i18n-exempt: route path.
import { createFileRoute } from '@tanstack/react-router'
import { PreferenceEditor } from '../../../../settings/Preferences'
export const Route = createFileRoute('/_app/settings/preferences/$preferenceId')({ component: Screen })
function Screen() { const { preferenceId } = Route.useParams(); return <PreferenceEditor key={preferenceId} id={preferenceId} /> }

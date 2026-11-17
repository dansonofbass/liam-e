// i18n-exempt: route path.
import { createFileRoute } from '@tanstack/react-router'
import { Editor } from '../../../../prompts/Editor'
export const Route = createFileRoute('/_app/settings/prompts/$promptId')({ component: Screen })
function Screen() { const { promptId } = Route.useParams(); return <Editor key={promptId} id={promptId} /> }

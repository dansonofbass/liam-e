// i18n-exempt: route path.
import { createFileRoute } from '@tanstack/react-router'
import { Settings } from '../../prompts/Settings'
export const Route = createFileRoute('/_app/settings')({ component: Settings })

// i18n-exempt: route path.
import { createFileRoute } from '@tanstack/react-router'
import { Library } from '../../../../prompts/Library'
export const Route = createFileRoute('/_app/settings/prompts/')({ component: Library })

// i18n-exempt: route path.
import { createFileRoute } from '@tanstack/react-router'
import { Editor } from '../../../../prompts/Editor'
export const Route = createFileRoute('/_app/settings/prompts/new')({ component: () => <Editor /> })

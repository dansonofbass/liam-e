import { createFileRoute } from '@tanstack/react-router'
import { LanguageSettings } from '../../../../settings/LanguageSettings'

export const Route = createFileRoute('/_app/settings/language/')({ component: LanguageSettings })

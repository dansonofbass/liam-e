import { createFileRoute } from '@tanstack/react-router'
import { ChatAccountSettings } from '../../../../settings/ChatAccountSettings'

export const Route = createFileRoute('/_app/settings/chat/')({ component: ChatAccountSettings })

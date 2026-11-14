import { createFileRoute } from '@tanstack/react-router'
import { AccountsPage } from '../../accounts/AccountsPage'

export const Route = createFileRoute('/_app/accounts')({
  validateSearch: (search: Record<string, unknown>): { connected?: string; error?: string } => ({ connected: typeof search.connected === 'string' ? search.connected : undefined, error: typeof search.error === 'string' ? search.error : undefined }),
  component: AccountsPage,
})

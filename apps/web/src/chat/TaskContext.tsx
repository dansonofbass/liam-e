// i18n-exempt: CSS classes and protocol literals.
import { useQuery } from '@tanstack/react-query'
import { summaryQuery } from '../api/queries'
import { Chip } from '../ds'
import { de } from '../i18n/de'
import { useConversationScope, useTaskScope } from './session'

export function TaskScopeSelector({ conversationId, disabled }: { conversationId?: string; disabled: boolean }) {
  const tasks = useTaskScope(conversationId)
  const mail = useConversationScope(conversationId)
  const summary = useQuery(summaryQuery())
  const blocked = disabled || !tasks.ready || !mail.ready
  return <section aria-label={de.taskChat.scope}>
    <strong>{de.taskChat.scope}</strong><p className="le-hint">{de.taskChat.scopeHint}</p>
    <div className="le-calendar-controls">
      <Chip pressed={tasks.scope.source === 'none'} disabled={blocked} onClick={() => tasks.set({ source: 'none' })}>{de.taskChat.none}</Chip>
      {!mail.scope && <><Chip pressed={tasks.scope.source === 'all'} disabled={blocked} onClick={() => tasks.set({ source: 'all' })}>{de.tasks.allSources}</Chip>
        <Chip pressed={tasks.scope.source === 'unlinked'} disabled={blocked} onClick={() => tasks.set({ source: 'unlinked' })}>{de.tasks.unlinked}</Chip></>}
      {summary.data?.accounts.filter(account => !mail.scope || account.id === mail.scope).map(account => <Chip key={account.id} aria-label={de.taskChat.account(account.display_name || account.email_address)} pressed={tasks.scope.source === 'account' && tasks.scope.account_id === account.id} disabled={blocked} onClick={() => tasks.set({ source: 'account', account_id: account.id })}>{account.display_name || account.email_address}</Chip>)}
    </div>
  </section>
}

// i18n-exempt: CSS classes and protocol literals.
import { useQuery } from '@tanstack/react-query'
import { summaryQuery } from '../api/queries'
import { Chip, Icon, Menu, Tooltip } from '../ds'
import { de } from '../i18n/de'
import { useConversationScope, useTaskScope, type TaskScope } from './session'

type Choice = { label: string; scope: TaskScope; hint?: string }

// One chip in the composer bar, like the account chip beside it: a block of choice chips above the composer pushed the
// composer itself off a small phone screen.
export function TaskScopeSelector({ conversationId, disabled }: { conversationId?: string; disabled: boolean }) {
  const tasks = useTaskScope(conversationId)
  const mail = useConversationScope(conversationId)
  const summary = useQuery(summaryQuery())
  const blocked = disabled || !tasks.ready || !mail.ready
  const choices: Choice[] = [{ label: de.taskChat.none, scope: { source: 'none' } }]
  if (mail.scope) {
    choices.push({ label: de.tasks.allSources, scope: { source: 'account_and_unlinked', account_id: mail.scope }, hint: de.taskChat.accountAndUnlinkedHint })
    choices.push({ label: de.taskChat.thisAccount, scope: { source: 'account', account_id: mail.scope } })
  } else {
    choices.push({ label: de.tasks.allSources, scope: { source: 'all' } }, { label: de.tasks.unlinked, scope: { source: 'unlinked' } })
    for (const account of summary.data?.accounts ?? []) choices.push({ label: de.taskChat.account(account.display_name || account.email_address), scope: { source: 'account', account_id: account.id } })
  }
  const same = (scope: TaskScope) => scope.source === tasks.scope.source && (scope.account_id ?? null) === (tasks.scope.account_id ?? null)
  // A restored choice the list cannot offer (an account no longer listed, or not loaded yet) still names itself rather than
  // posing as "no tasks" while it is what the next request sends.
  if (!choices.some(choice => same(choice.scope))) choices.push({ label: tasks.scope.source === 'account' ? de.taskChat.account(de.prompts.scopeUnavailable) : tasks.scope.source === 'unlinked' ? de.tasks.unlinked : de.tasks.allSources, scope: tasks.scope })
  const current = choices.find(choice => same(choice.scope))!
  // In a conversation with history another choice applies only to a new one; touch has no tooltip, so the items say so.
  const items = choices.map(choice => ({ label: choice.label, checked: same(choice.scope), hint: [choice.hint, conversationId && !same(choice.scope) ? de.taskChat.needsNew : undefined].filter(Boolean).join(' ') || undefined, onSelect: () => tasks.set(choice.scope) }))
  return <Menu trigger={props => <Tooltip content={de.taskChat.scopeTip}><Chip {...props} quiet disabled={blocked}>{current.label}<Icon name="chevron-down" size="sm" /></Chip></Tooltip>} items={items} />
}

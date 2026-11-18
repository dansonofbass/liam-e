// i18n-exempt: CSS classes and protocol literals.
import { useQuery } from '@tanstack/react-query'
import { summaryQuery } from '../api/queries'
import { Chip, Icon, Menu, Tooltip } from '../ds'
import { useI18n } from '../i18n/I18n'
import { useConversationScope, useTaskScope, type TaskScope } from './session'

type Choice = { label: string; scope: TaskScope; hint?: string }

// One chip in the composer bar, like the account chip beside it: a block of choice chips above the composer pushed the
// composer itself off a small phone screen.
export function TaskScopeSelector({ conversationId, disabled }: { conversationId?: string; disabled: boolean }) {
  const { texts } = useI18n()
  const tasks = useTaskScope(conversationId)
  const mail = useConversationScope(conversationId)
  const summary = useQuery(summaryQuery())
  const blocked = disabled || !tasks.ready || !mail.ready
  const choices: Choice[] = [{ label: texts.taskChat.none, scope: { source: 'none' } }]
  if (mail.scope) {
    choices.push({ label: texts.tasks.allSources, scope: { source: 'account_and_unlinked', account_id: mail.scope }, hint: texts.taskChat.accountAndUnlinkedHint })
    choices.push({ label: texts.taskChat.thisAccount, scope: { source: 'account', account_id: mail.scope } })
  } else {
    choices.push({ label: texts.tasks.allSources, scope: { source: 'all' } }, { label: texts.tasks.unlinked, scope: { source: 'unlinked' } })
    for (const account of summary.data?.accounts ?? []) choices.push({ label: texts.taskChat.account(account.display_name || account.email_address), scope: { source: 'account', account_id: account.id } })
  }
  const same = (scope: TaskScope) => scope.source === tasks.scope.source && (scope.account_id ?? null) === (tasks.scope.account_id ?? null)
  // A restored choice the list cannot offer still names itself rather than posing as "no tasks" while it is what the next
  // request sends. It never repeats an offered label: a saved account shows its name (or that it is still loading or gone),
  // any other saved choice is marked as saved.
  const restoredLabel = (scope: TaskScope) => {
    if (scope.source !== 'account') return texts.taskChat.saved(scope.source === 'unlinked' ? texts.tasks.unlinked : texts.tasks.allSources)
    const account = summary.data?.accounts.find(item => item.id === scope.account_id)
    return texts.taskChat.account(account ? account.display_name || account.email_address : summary.isPending ? texts.taskChat.accountLoading : texts.prompts.scopeUnavailable)
  }
  if (!choices.some(choice => same(choice.scope))) choices.push({ label: restoredLabel(tasks.scope), scope: tasks.scope })
  const current = choices.find(choice => same(choice.scope))!
  // In a conversation with history another choice applies only to a new one; touch has no tooltip, so the items say so.
  const items = choices.map(choice => ({ label: choice.label, checked: same(choice.scope), hint: [choice.hint, conversationId && !same(choice.scope) ? texts.taskChat.needsNew : undefined].filter(Boolean).join(' ') || undefined, onSelect: () => tasks.set(choice.scope) }))
  return <Menu trigger={props => <Tooltip content={texts.taskChat.scopeTip}><Chip {...props} quiet disabled={blocked}>{current.label}<Icon name="chevron-down" size="sm" /></Chip></Tooltip>} items={items} />
}

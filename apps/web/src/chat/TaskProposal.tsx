// i18n-exempt: CSS classes and protocol literals.
import { useState } from 'react'
import type { Proposal, TaskCreateCommand } from '../api/generated/types.gen'
import { Button } from '../ds'
import { de } from '../i18n/de'
import { SourceMail } from '../tasks/SourceMail'
import { SchedulePreview, TaskForm, type TaskFormDraft } from '../tasks/TaskForm'
import { formatTaskDue } from '../tasks/format'
import { TaskRule } from '../tasks/TaskRule'
import './task-proposal.css'

export function TaskProposal({ proposal, busy, confirm, cancel, draft }: { proposal: Proposal; busy: boolean; confirm: (edit?: TaskCreateCommand) => void; cancel: () => void; draft?: TaskFormDraft }) {
  const [previewValid, setPreviewValid] = useState(false)
  const task = proposal.task
  if (!task) return null
  const source = task.source_message_id ? <SourceMail id={task.source_message_id} /> : <p>{de.tasks.unlinked}</p>
  if (task.action === 'create') return <section className="le-confirm le-task-proposal">
    <p>{proposal.reason}</p>{source}
    <TaskForm proposal busy={busy} draft={draft} initial={{ ...task, creation_key: 'proposal' }} save={body => confirm({
      action: 'create', title: body.title, start: body.start, timezone: body.timezone!, rrule: body.rrule,
      source_account_id: task.source_account_id, source_message_id: task.source_message_id,
    })} />
    <Button variant="ghost" disabled={busy} onClick={cancel}>{de.controls.cancel}</Button>
  </section>
  const start = task.action === 'patch' ? task.start : task.due_local
  const zone = task.action === 'patch' ? task.timezone ?? task.display_timezone : task.display_timezone
  const rule = task.action === 'patch' && task.rule_supplied ? task.rrule : task.display_rrule
  let through: string | undefined
  if (start) {
    const end = new Date(`${start.slice(0, 10)}T00:00:00Z`)
    end.setUTCDate(end.getUTCDate() + 365)
    through = end.toISOString().slice(0, 10) + (start.includes('T') ? 'T23:59:59' : '')
  }
  return <section className="le-confirm le-task-proposal"><h3 className="heading">{de.taskChat.actions[task.action]}</h3>
    <strong>{task.title}</strong><p>{proposal.reason}</p>{source}
    {start && <p>{de.taskChat.target}: {formatTaskDue(start)}</p>}
    <p>{de.tasks.zone}: {zone ?? 'UTC'}</p>
    <TaskRule rule={rule} />
    <p>{de.taskChat.version}: {task.expected_version}</p>
    {task.action === 'patch' && <p>{task.scope === 'occurrence' ? de.tasks.onlyThis : de.tasks.following}</p>}
    {task.occurrence_key && <p>{task.action === 'patch' && task.scope === 'this_and_following' ? de.taskChat.boundary : de.taskChat.originalDue}: {formatTaskDue(task.occurrence_key)}</p>}
    {task.action === 'patch' && start && through ? <SchedulePreview input={{ start, through, timezone: zone ?? 'UTC', rrule: task.scope === 'occurrence' ? null : rule, limit: 5 }} onValid={setPreviewValid} /> : <section aria-label={de.tasks.preview}><h3>{de.tasks.preview}</h3><ol>{task.next_due?.map((due, index) => <li key={`${due}-${index}`}>{formatTaskDue(due)}</li>)}</ol><p>{de.tasks.previewIncomplete}</p></section>}
    <Button variant="primary" disabled={busy || (task.action === 'patch' && !previewValid)} onClick={() => confirm()}>{de.taskChat.confirm}</Button>
    <Button variant="ghost" disabled={busy} onClick={cancel}>{de.controls.cancel}</Button>
  </section>
}

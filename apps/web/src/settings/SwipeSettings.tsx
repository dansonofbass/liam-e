// i18n-exempt: route paths and CSS classes.
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useRef, useState } from 'react'
import { settingsUiUpdate } from '../api/generated/sdk.gen'
import type { UiSettingsOut } from '../api/generated/types.gen'
import { uiSettingsQuery } from '../api/queries'
import { errorCode, unwrap } from '../api/unwrap'
import { Button, Chip, Icon, Menu, Notice, Tooltip, type IconName } from '../ds'
import { de } from '../i18n/de'
import type { SwipeAction } from './useSwipeSettings'
import './settings.css'

const ACTIONS: SwipeAction[] = ['none', 'archive', 'toggle_read', 'trash']
const DEFAULTS = { left: 'archive' as SwipeAction, right: 'toggle_read' as SwipeAction }
const actionIcon = (action: SwipeAction): IconName | undefined =>
  action === 'archive' ? 'archive' : action === 'toggle_read' ? 'mail-open' : action === 'trash' ? 'trash-2' : undefined
const codeOf = (cause: unknown) => errorCode(cause instanceof Error ? cause.cause : cause)

export function SwipeSettings() {
  const query = useQuery(uiSettingsQuery())
  if (!query.data) return <section className="le-swipe"><h2 className="heading">{de.settingsUi.title}</h2>
    {query.isPending ? <><p role="status">{de.settingsUi.loading}</p>{[0, 1].map(index => <div key={index} className="le-swipe-placeholder" aria-hidden="true" />)}</>
      : <Notice tone="danger" action={{ label: de.chat.retry, onClick: () => { void query.refetch() } }}>{de.settingsUi.error}</Notice>}
  </section>
  return <SwipeSettingsForm settings={query.data} reload={async () => {
    const result = await query.refetch()
    if (result.isError) throw result.error
  }} />
}

/** Edited form values and the confirmed assignment stay separate until the server accepts a save. */
function SwipeSettingsForm({ settings, reload }: { settings: UiSettingsOut; reload: () => Promise<void> }) {
  const client = useQueryClient()
  const [left, setLeft] = useState<SwipeAction>(settings.swipe_left)
  const [right, setRight] = useState<SwipeAction>(settings.swipe_right)
  const [busy, setBusy] = useState(false)
  const [outcome, setOutcome] = useState<'saved' | 'error' | 'conflict'>()
  const lock = useRef(false)
  const select = (setter: (value: SwipeAction) => void, value: SwipeAction) => { setter(value); setOutcome(undefined) }
  const save = async (assignment: { left: SwipeAction; right: SwipeAction }) => {
    if (lock.current) return
    lock.current = true; setBusy(true); setOutcome(undefined)
    try {
      const saved = await unwrap(settingsUiUpdate({ body: { expected_revision: settings.revision, swipe_left: assignment.left, swipe_right: assignment.right }, throwOnError: true }))
      client.setQueryData(uiSettingsQuery().queryKey, saved)
      setLeft(assignment.left); setRight(assignment.right)
      setOutcome('saved')
    } catch (cause) {
      if (codeOf(cause) === 'ui_settings_conflict') {
        // Show the competing change, but never retry on our own: the next save is a conscious one.
        setOutcome('conflict')
        await reload().catch(() => setOutcome('error'))
      } else setOutcome('error')
    } finally { lock.current = false; setBusy(false) }
  }
  return <form className="le-swipe" onSubmit={event => { event.preventDefault(); void save({ left, right }) }}>
    <h2 className="heading">{de.settingsUi.title}</h2>
    <p className="le-swipe-intro">{de.settingsUi.intro}</p>
    <div className="le-swipe-fields">
      <SwipeSelect id="le-swipe-left" label={de.settingsUi.left} action={left} onSelect={value => select(setLeft, value)} />
      <SwipeSelect id="le-swipe-right" label={de.settingsUi.right} action={right} onSelect={value => select(setRight, value)} />
    </div>
    {outcome === 'saved' && <Notice tone="success">{de.settingsUi.saved}</Notice>}
    {outcome === 'error' && <Notice tone="danger">{de.settingsUi.saveError}</Notice>}
    {outcome === 'conflict' && <Notice tone="danger" action={{ label: de.settingsUi.reload, onClick: () => { setLeft(settings.swipe_left); setRight(settings.swipe_right); setOutcome(undefined) } }}>
      {de.settingsUi.conflict(de.settingsUi.actions[settings.swipe_left], de.settingsUi.actions[settings.swipe_right])}</Notice>}
    <div className="le-swipe-actions">
      <Button type="submit" variant="primary" disabled={busy}>{de.settingsUi.save}</Button>
      <Tooltip content={de.settingsUi.restoreTip}><Button variant="secondary" disabled={busy} onClick={() => { void save(DEFAULTS) }}>{de.settingsUi.restore}</Button></Tooltip>
    </div>
  </form>
}

function SwipeSelect({ id, label, action, onSelect }: { id: string; label: string; action: SwipeAction; onSelect: (action: SwipeAction) => void }) {
  return <div className="le-swipe-field">
    <span className="le-swipe-label" id={`${id}-label`}>{label}</span>
    <Menu trigger={props => <Chip {...props} quiet aria-labelledby={`${id}-label`}>{de.settingsUi.actions[action]}<Icon name="chevron-down" size="sm" /></Chip>}
      items={ACTIONS.map(value => ({ label: de.settingsUi.actions[value], checked: value === action, onSelect: () => onSelect(value) }))} />
    <SwipePreview action={action} />
  </div>
}

function SwipePreview({ action }: { action: SwipeAction }) {
  const icon = actionIcon(action)
  return <div className="le-swipe-preview">
    <span className="le-swipe-preview-row" aria-hidden="true"><span className="le-swipe-preview-name">{de.settingsUi.previewSender}</span><span className="le-swipe-preview-subject">{de.settingsUi.previewSubject}</span></span>
    <span className="le-swipe-preview-effect">{icon && <Icon name={icon} size="sm" />}{de.settingsUi.effects[action]}</span>
  </div>
}

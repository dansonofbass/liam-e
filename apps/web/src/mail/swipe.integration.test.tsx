import { afterEach, expect, mock, spyOn, test } from 'bun:test'
import { QueryClient, QueryClientProvider, useQuery, type InfiniteData } from '@tanstack/react-query'
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import * as sdk from '../api/generated/sdk.gen'
import type { MessagePageOut } from '../api/generated/types.gen'
import { MailRow } from '../ds/MailRow'
import { useSwipeSettings } from '../settings/useSwipeSettings'
import { useMailActions } from './useMailActions'

const row = { id: 'm1', account_id: 'a', color_index: 0, sender_name: 'Anna', sender_address: 'anna@example.org', subject: 'Termin', snippet: '', internal_date: null, deadline: null, has_attachments: false, is_flagged: false, is_read: false, needs_reply: false }
const key = ['messages', {}]
const assignment = { swipe_left: 'archive', swipe_right: 'toggle_read', revision: 1 }
function setup() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  client.setQueryData<InfiniteData<MessagePageOut>>(key, { pages: [{ items: [row], next_cursor: null }], pageParams: [undefined] })
  client.setQueryData(['ui-settings'], assignment)
  const action = spyOn(sdk, 'mailMessageAction').mockImplementation((async () => ({ data: { action_id: 'a1', message: row }, response: { status: 200 } })) as never)
  const open = mock(() => {})
  function Harness() {
    const { data } = useQuery<InfiniteData<MessagePageOut>>({ queryKey: key, queryFn: async () => client.getQueryData<InfiniteData<MessagePageOut>>(key)!, enabled: false })
    const settings = useSwipeSettings()
    const actions = useMailActions()
    const mail = data!.pages[0]!.items[0]!
    return <MailRow mail={mail} selected={false} coarse onOpen={open} onArchive={() => {}} onToggleRead={() => {}} onTrash={() => {}} swipe={{ basis: settings.assignment && settings.revision !== undefined ? { id: mail.id, isRead: mail.is_read, revision: settings.revision, ...settings.assignment } : undefined, enabled: settings.status === 'ready' && actions.capacityAvailable && !actions.isBusy(mail.id), navigation: '/mail', valid: basis => { const settings = client.getQueryData<typeof assignment>(['ui-settings']); const current = client.getQueryData<InfiniteData<MessagePageOut>>(key)?.pages[0]?.items[0]; return settings?.revision === basis.revision && settings.swipe_left === basis.left && settings.swipe_right === basis.right && current?.id === basis.id && current.is_read === basis.isRead && !actions.isBusy(basis.id) }, run: kind => { if (!actions.isBusy(mail.id) && actions.checkCapacity()) void actions.run(mail.id, kind) } }} />
  }
  const view = render(<QueryClientProvider client={client}><Harness /></QueryClientProvider>)
  const element = view.container.querySelector<HTMLElement>('.le-mailrow')!
  element.getBoundingClientRect = () => ({ width: 300, height: 100, left: 0, right: 300, top: 0, bottom: 100, x: 0, y: 0, toJSON() {} })
  return { client, action, open, element }
}
function pointer(element: Element, type: string, x: number, y = 100, id = 1, pointerType = 'touch') {
  const event = new MouseEvent(type, { bubbles: true, cancelable: true, clientX: x, clientY: y })
  Object.defineProperties(event, { pointerId: { value: id }, pointerType: { value: pointerType }, isPrimary: { value: id === 1 } })
  fireEvent(element, event)
}
const down = (el: Element) => pointer(el, 'pointerdown', 200)
const move = (el: Element, x: number, y = 100) => pointer(el, 'pointermove', x, y)
const up = (el: Element, x: number) => pointer(el, 'pointerup', x)
afterEach(() => { cleanup(); mock.restore() })

test('visible concrete preview executes once through the real action hook', async () => {
  const { element, action } = setup(); down(element); move(element, 300)
  expect(screen.getByRole('status').textContent).toBe('Loslassen: Als gelesen markieren')
  up(element, 300)
  await waitFor(() => expect(action).toHaveBeenCalledTimes(1))
  expect(action.mock.calls[0]?.[0]).toEqual({ path: { message_id: 'm1' }, body: { kind: 'mark_read' } })
})

test.each(['short', 'flick', 'return', 'vertical', 'cancel', 'capture', 'second', 'mouse'])('%s cannot mutate', async mode => {
  const { element, action } = setup()
  if (mode === 'mouse') { pointer(element, 'pointerdown', 200, 100, 1, 'mouse'); pointer(element, 'pointermove', 310, 100, 1, 'mouse'); pointer(element, 'pointerup', 310, 100, 1, 'mouse') }
  else {
    down(element)
    if (mode === 'vertical') { move(element, 205, 120); move(element, 310, 120) }
    else if (mode === 'flick') move(element, 230)
    else if (mode === 'short') move(element, 289)
    else { move(element, 310); if (mode === 'return') move(element, 250) }
    if (mode === 'cancel') pointer(element, 'pointercancel', 310)
    if (mode === 'capture') pointer(element, 'lostpointercapture', 310)
    if (mode === 'second') pointer(document.body, 'pointerdown', 300, 100, 2)
    up(element, 310)
  }
  await act(async () => {})
  expect(action).not.toHaveBeenCalled()
})

test.each(['read', 'settings', 'identity'])('changing %s invalidates an existing preview', async change => {
  const { element, action, client } = setup(); down(element); move(element, 310)
  act(() => {
    if (change === 'settings') client.setQueryData(['ui-settings'], { ...assignment, revision: 2 })
    else client.setQueryData<InfiniteData<MessagePageOut>>(key, data => ({ ...data!, pages: [{ ...data!.pages[0]!, items: [{ ...row, ...(change === 'read' ? { is_read: true } : { id: 'm2' }) }] }] }))
  })
  up(element, 310); await act(async () => {})
  expect(action).not.toHaveBeenCalled()
})

test('tap opens, while a drag suppresses its following click', () => {
  const { element, open } = setup(); down(element); up(element, 200); fireEvent.click(element); expect(open).toHaveBeenCalledTimes(1)
  down(element); move(element, 250); up(element, 250); fireEvent.click(element); expect(open).toHaveBeenCalledTimes(1)
})

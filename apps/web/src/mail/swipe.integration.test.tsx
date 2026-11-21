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
function setup(settings = assignment, count = 1) {
  const rows = Array.from({ length: count }, (_, i) => i === 0 ? row : { ...row, id: `m${i + 1}`, subject: `Mail ${i + 1}` })
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  client.setQueryData<InfiniteData<MessagePageOut>>(key, { pages: [{ items: rows, next_cursor: null }], pageParams: [undefined] })
  client.setQueryData(['ui-settings'], settings)
  spyOn(sdk, 'settingsUiGet').mockImplementation((async () => ({ data: client.getQueryData(['ui-settings']) ?? settings, response: { ok: true } })) as never)
  const action = spyOn(sdk, 'mailMessageAction').mockImplementation((async (options: { path: { message_id: string } }) => ({ data: { action_id: 'a1', message: rows.find(item => item.id === options.path.message_id) ?? row }, response: { status: 200 } })) as never)
  const undo = spyOn(sdk, 'mailActionsUndo').mockImplementation((async () => ({ data: { restored: ['a1'], skipped: [], expired: [], failed: [] }, response: { status: 200 } })) as never)
  const open = mock<(id: string) => void>(() => {})
  let triggerUndo: (() => Promise<void>) | undefined
  function Harness() {
    const { data } = useQuery<InfiniteData<MessagePageOut>>({ queryKey: key, queryFn: async () => client.getQueryData<InfiniteData<MessagePageOut>>(key)!, enabled: false })
    const settings = useSwipeSettings()
    const actions = useMailActions()
    triggerUndo = async () => { await actions.undo() }
    const items = data!.pages[0]!.items
    if (!items.length) return null
    return <div className="le-inbox-scroll">{items.map(mail => <MailRow key={mail.id} mail={mail} selected={false} coarse onOpen={() => open(mail.id)} onArchive={() => {}} onToggleRead={() => {}} onTrash={() => {}} swipe={{ basis: settings.assignment && settings.revision !== undefined ? { id: mail.id, isRead: mail.is_read, revision: settings.revision, ...settings.assignment } : undefined, enabled: settings.status === 'ready' && actions.capacityAvailable && !actions.isBusy(mail.id), navigation: '/mail', valid: basis => { const settings = client.getQueryData<typeof assignment>(['ui-settings']); const current = client.getQueryData<InfiniteData<MessagePageOut>>(key)?.pages[0]?.items.find(item => item.id === basis.id); return settings?.revision === basis.revision && settings.swipe_left === basis.left && settings.swipe_right === basis.right && current?.id === basis.id && current.is_read === basis.isRead && !actions.isBusy(basis.id) }, run: kind => { if (!actions.isBusy(mail.id) && actions.checkCapacity()) void actions.run(mail.id, kind) } }} />)}</div>
  }
  const view = render(<QueryClientProvider client={client}><Harness /></QueryClientProvider>)
  const scroller = view.container.querySelector<HTMLElement>('.le-inbox-scroll')!
  const elements = Array.from(view.container.querySelectorAll<HTMLElement>('.le-mailrow'))
  for (const el of elements) el.getBoundingClientRect = () => ({ width: 300, height: 100, left: 0, right: 300, top: 0, bottom: 100, x: 0, y: 0, toJSON() {} })
  return { client, action, undo, triggerUndo: () => triggerUndo?.(), open, element: elements[0]!, elements, scroller, unmount: view.unmount }
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

test.each(['edge', 'button'])('start on %s never takes the gesture', async target => {
  const { element, action } = setup()
  const start = target === 'button' ? element.querySelector('.le-mailrow-more button')! : element
  pointer(start, 'pointerdown', target === 'edge' ? 10 : 200)
  move(element, 310); up(element, 310)
  await act(async () => {})
  expect(action).not.toHaveBeenCalled()
  expect(screen.getByRole('status').textContent).toBe('')
})

test('the subject line belongs to the row: a drag there swipes once, a tap there opens once', async () => {
  const { element, action, open } = setup()
  const subject = element.querySelector('.le-mailrow-subject')!
  pointer(subject, 'pointerdown', 200); move(element, 300); up(element, 300)
  await waitFor(() => expect(action).toHaveBeenCalledTimes(1))
  fireEvent.click(subject)
  expect(open).not.toHaveBeenCalled()
  pointer(subject, 'pointerdown', 200); pointer(subject, 'pointerup', 200); fireEvent.click(subject)
  expect(open).toHaveBeenCalledTimes(1)
  expect(action).toHaveBeenCalledTimes(1)
})

test('tap opens, while a drag suppresses its following click', () => {
  const { element, open } = setup(); down(element); up(element, 200); fireEvent.click(element); expect(open).toHaveBeenCalledTimes(1)
  down(element); move(element, 250); up(element, 250); fireEvent.click(element); expect(open).toHaveBeenCalledTimes(1)
})

test('a drag without a following click does not swallow a later mouse click', () => {
  const { element, open } = setup()
  down(element); move(element, 250); up(element, 250)
  pointer(element, 'pointerdown', 200, 100, 1, 'mouse'); fireEvent.click(element)
  expect(open).toHaveBeenCalledTimes(1)
})

// iOS WebKit hands a horizontal drag to vertical scrolling once the finger drifts about 10 px, cancels the
// pointer and the row snaps back; only a prevented touchmove keeps the touch with the row.
function touchMove(element: Element, x: number, y = 100, fingers = 1, cancelable = true) {
  const event = new Event('touchmove', { bubbles: true, cancelable })
  Object.defineProperty(event, 'touches', { value: Array.from({ length: fingers }, (_, i) => ({ clientX: x + 40 * i, clientY: y })) })
  fireEvent(element, event)
  return event.defaultPrevented
}

test('a swipe drifting like a thumb arc keeps its touch from native scrolling once it is decided and still runs once', async () => {
  const { element, action } = setup()
  const subject = element.querySelector('.le-mailrow-subject')!
  expect(touchMove(subject, 230)).toBe(false)
  pointer(subject, 'pointerdown', 200)
  // Leaning horizontal is not a swipe yet; the row only keeps the touch once the swipe is decided.
  move(element, 204, 101); expect(touchMove(subject, 204, 101)).toBe(false)
  move(element, 230, 110); expect(touchMove(subject, 230, 110)).toBe(true)
  move(element, 300, 140); expect(touchMove(subject, 300, 140)).toBe(true)
  up(element, 300)
  await waitFor(() => expect(action).toHaveBeenCalledTimes(1))
  expect(touchMove(subject, 300, 140)).toBe(false)
})

test('a touch that starts leaning horizontal and then scrolls is never kept from scrolling', () => {
  const { element, action } = setup()
  down(element)
  move(element, 204, 101); expect(touchMove(element, 204, 101)).toBe(false)
  move(element, 218, 113); expect(touchMove(element, 218, 113)).toBe(false)
  move(element, 220, 160); expect(touchMove(element, 220, 160)).toBe(false)
  move(element, 330, 160); expect(touchMove(element, 330, 160)).toBe(false)
  up(element, 330)
  expect(action).not.toHaveBeenCalled()
})

test('a second finger on a decided swipe is left to pinch-zoom', () => {
  const { element } = setup()
  down(element)
  move(element, 230); expect(touchMove(element, 230)).toBe(true)
  expect(touchMove(element, 240, 100, 2)).toBe(false)
})

test.each(['vertical', 'mouse', 'second'])('a %s gesture leaves native scrolling alone', mode => {
  const { element } = setup()
  if (mode === 'mouse') { pointer(element, 'pointerdown', 200, 100, 1, 'mouse'); pointer(element, 'pointermove', 260, 100, 1, 'mouse'); expect(touchMove(element, 260)).toBe(false); return }
  down(element)
  if (mode === 'second') { move(element, 230); pointer(document.body, 'pointerdown', 300, 100, 2); expect(touchMove(element, 240)).toBe(false); return }
  move(element, 201, 105); expect(touchMove(element, 201, 105)).toBe(false)
  move(element, 203, 120); expect(touchMove(element, 203, 120)).toBe(false)
  move(element, 320, 120); expect(touchMove(element, 320, 120)).toBe(false)
})

test('click suppression after a drag expires for a later keyboard activation', () => {
  const { element, open } = setup()
  const now = spyOn(performance, 'now').mockReturnValue(1000)
  down(element); move(element, 250); up(element, 250)
  now.mockReturnValue(1000 + 5_000)
  fireEvent.click(element)
  expect(open).toHaveBeenCalledTimes(1)
})

test('a native horizontal move before pointermove shows the configured trash action and commits it once', async () => {
  const { element, action } = setup({ ...assignment, swipe_left: 'trash' })
  const subject = element.querySelector('.le-mailrow-subject')!
  pointer(subject, 'pointerdown', 220)
  expect(touchMove(subject, 190, 105)).toBe(true)
  expect(touchMove(subject, 115, 115)).toBe(true)
  expect(screen.getByRole('status').textContent).toBe('Loslassen für den Papierkorb')
  up(element, 115)
  await waitFor(() => expect(action).toHaveBeenCalledTimes(1))
  expect(action.mock.calls[0]?.[0]).toEqual({ path: { message_id: 'm1' }, body: { kind: 'trash' } })
})

test('lifting inside the threshold after the last armed preview cancels the swipe', () => {
  const { element, action } = setup({ ...assignment, swipe_left: 'trash' })
  down(element); move(element, 100); up(element, 180)
  expect(action).not.toHaveBeenCalled()
})

test('a swipe after minor scroll momentum settle runs once and supports undo', async () => {
  const { element, scroller, action, undo, triggerUndo } = setup()
  scroller.scrollTop = 200
  down(element)
  scroller.scrollTop = 205
  fireEvent.scroll(scroller)
  expect(touchMove(element, 180, 104)).toBe(true)
  expect(touchMove(element, 100, 108)).toBe(true)
  expect(screen.getByRole('status').textContent).toBe('Loslassen zum Archivieren')
  up(element, 100)
  await waitFor(() => expect(action).toHaveBeenCalledTimes(1))
  expect(action.mock.calls[0]?.[0]).toEqual({ path: { message_id: 'm1' }, body: { kind: 'archive' } })
  await act(async () => { await triggerUndo() })
  expect(undo).toHaveBeenCalledWith({ body: { action_ids: ['a1'] }, signal: expect.any(AbortSignal) })
})

test('a right swipe after minor scroll momentum settle locks scroll and runs once', async () => {
  const { element, scroller, action } = setup()
  scroller.scrollTop = 150
  down(element)
  scroller.scrollTop = 146
  fireEvent.scroll(scroller)
  expect(touchMove(element, 220, 103)).toBe(true)
  expect(touchMove(element, 300, 106)).toBe(true)
  expect(screen.getByRole('status').textContent).toBe('Loslassen: Als gelesen markieren')
  up(element, 300)
  await waitFor(() => expect(action).toHaveBeenCalledTimes(1))
  expect(action.mock.calls[0]?.[0]).toEqual({ path: { message_id: 'm1' }, body: { kind: 'mark_read' } })
})

test('active list scrolling before horizontal intent locks out swiping, suppresses drag click, and allows a fresh tap', () => {
  const { element, scroller, action, open } = setup()
  scroller.scrollTop = 100
  down(element)
  scroller.scrollTop = 116
  fireEvent.scroll(scroller)
  expect(touchMove(element, 100)).toBe(false)
  move(element, 90)
  expect(screen.getByRole('status').textContent).toBe('')
  up(element, 90)
  expect(action).not.toHaveBeenCalled()
  fireEvent.click(element)
  expect(open).not.toHaveBeenCalled()

  down(element); up(element, 200); fireEvent.click(element)
  expect(open).toHaveBeenCalledTimes(1)
  expect(open).toHaveBeenCalledWith('m1')
})

test('undecided touch locks at the inclusive 12 px scroll boundary while a stationary tap still opens', () => {
  const { element, scroller, action, open } = setup()
  scroller.scrollTop = 100
  down(element)
  scroller.scrollTop = 112
  fireEvent.scroll(scroller)
  expect(touchMove(element, 100)).toBe(false)
  up(element, 100)
  expect(action).not.toHaveBeenCalled()
  fireEvent.click(element)
  expect(open).not.toHaveBeenCalled()

  scroller.scrollTop = 100
  down(element)
  scroller.scrollTop = 116
  fireEvent.scroll(scroller)
  up(element, 200)
  expect(action).not.toHaveBeenCalled()
  fireEvent.click(element)
  expect(open).toHaveBeenCalledTimes(1)
})

test('continued list scrolling after preview cancels the swipe before release', () => {
  const { element, scroller, action } = setup()
  scroller.scrollTop = 100
  down(element)
  expect(touchMove(element, 160)).toBe(true)
  expect(screen.getByRole('status').textContent).toBe('Archivieren')
  scroller.scrollTop = 102.5
  fireEvent.scroll(scroller)
  expect(screen.getByRole('status').textContent).toBe('')
  up(element, 80)
  expect(action).not.toHaveBeenCalled()
})

test('fractional scroll settle beyond 2 px cancels an armed swipe on release while exact 2 px commits', async () => {
  const { element, scroller, action } = setup()
  scroller.scrollTop = 100
  down(element)
  expect(touchMove(element, 100)).toBe(true)
  expect(screen.getByRole('status').textContent).toBe('Loslassen zum Archivieren')
  scroller.scrollTop = 102.5
  up(element, 100)
  expect(screen.getByRole('status').textContent).toBe('')
  expect(action).not.toHaveBeenCalled()

  scroller.scrollTop = 100
  down(element)
  expect(touchMove(element, 100)).toBe(true)
  scroller.scrollTop = 102
  up(element, 100)
  await waitFor(() => expect(action).toHaveBeenCalledTimes(1))
})

test('non-cancelable touchmove from active browser scrolling cancels without showing a preview', () => {
  const { element, action, open } = setup()
  const now = spyOn(performance, 'now').mockReturnValue(1000)
  down(element)
  expect(touchMove(element, 100, 100, 1, false)).toBe(false)
  expect(screen.getByRole('status').textContent).toBe('')
  now.mockReturnValue(1700)
  up(element, 100)
  expect(action).not.toHaveBeenCalled()
  fireEvent.click(element)
  expect(open).not.toHaveBeenCalled()

  down(element); up(element, 200); fireEvent.click(element)
  expect(open).toHaveBeenCalledTimes(1)
})

test('a small non-cancelable move followed by a drag suppresses its release click while a fresh tap opens', () => {
  const { element, action, open } = setup()
  down(element)
  expect(touchMove(element, 204, 100, 1, false)).toBe(false)
  move(element, 220)
  expect(screen.getByRole('status').textContent).toBe('')
  up(element, 220)
  expect(action).not.toHaveBeenCalled()
  fireEvent.click(element)
  expect(open).not.toHaveBeenCalled()

  down(element)
  expect(touchMove(element, 204, 100, 1, false)).toBe(false)
  expect(touchMove(element, 220, 100, 1, false)).toBe(false)
  up(element, 220)
  fireEvent.click(element)
  expect(open).not.toHaveBeenCalled()

  down(element); up(element, 200); fireEvent.click(element)
  expect(open).toHaveBeenCalledTimes(1)
})

test('touchcancel and a missed pointerup recover cleanly for the next swipe or tap', async () => {
  const { element, action, open } = setup()
  down(element)
  move(element, 100)
  expect(screen.getByRole('status').textContent).toBe('Loslassen zum Archivieren')
  fireEvent(element, new Event('touchcancel', { bubbles: true }))
  expect(screen.getByRole('status').textContent).toBe('')
  up(element, 100)
  expect(action).not.toHaveBeenCalled()

  // Simulate a gesture that never received pointerup/pointercancel before a fresh primary tap arrives.
  down(element)
  move(element, 100)
  down(element)
  up(element, 200)
  fireEvent.click(element)
  expect(open).toHaveBeenCalledTimes(1)
  expect(action).not.toHaveBeenCalled()

  // A subsequent swipe still runs once cleanly.
  down(element)
  move(element, 300)
  up(element, 300)
  await waitFor(() => expect(action).toHaveBeenCalledTimes(1))
})

test('a fresh primary touch on another row with the same pointerId clears a stale armed swipe', async () => {
  const { elements, action, open } = setup(assignment, 2)
  const [first, second] = elements as [HTMLElement, HTMLElement]
  down(first)
  move(first, 100)
  await waitFor(() => expect(first.style.transform).toBe('translateX(-100px)'))
  expect(screen.getAllByRole('status').map(node => node.textContent)).toEqual(['Loslassen zum Archivieren', ''])

  // Reuse pointerId=1 for a new primary touch on the second row without releasing the first.
  down(second)
  await waitFor(() => expect(first.style.transform).toBe(''))
  expect(screen.getAllByRole('status').map(node => node.textContent)).toEqual(['', ''])
  up(second, 200)
  fireEvent.click(second)
  expect(open).toHaveBeenCalledWith('m2')
  expect(action).not.toHaveBeenCalled()

  // Swiping the second row afterwards commits only on m2.
  down(second)
  move(second, 300)
  up(second, 300)
  await waitFor(() => expect(action).toHaveBeenCalledTimes(1))
  expect(action.mock.calls[0]?.[0]).toEqual({ path: { message_id: 'm2' }, body: { kind: 'mark_read' } })
})

test('document scroll listener is registered only while a swipe gesture is active', () => {
  const add = spyOn(window.EventTarget.prototype, 'addEventListener')
  const remove = spyOn(window.EventTarget.prototype, 'removeEventListener')
  const docCalls = (spy: typeof add, eventType: string, capture?: boolean) =>
    spy.mock.calls.filter(([type, , options], index) =>
      spy.mock.contexts[index] === document &&
      type === eventType &&
      (capture === undefined || (typeof options === 'boolean' ? options === capture : options?.capture === capture)),
    ).length
  const scrollAdds = () => docCalls(add, 'scroll')
  const scrollRemoves = () => docCalls(remove, 'scroll')
  const pointerAdds = () => docCalls(add, 'pointerdown', true)
  const pointerRemoves = () => docCalls(remove, 'pointerdown', true)

  const { elements, scroller, unmount } = setup(assignment, 5)
  const [first, second] = elements as [HTMLElement, HTMLElement]
  scroller.scrollTop = 40
  fireEvent.scroll(scroller)
  expect(scrollAdds()).toBe(0)
  expect(pointerAdds()).toBe(0)

  down(first)
  expect(scrollAdds()).toBe(1)
  expect(pointerAdds()).toBe(1)
  up(first, 200)
  expect(scrollRemoves()).toBe(1)
  expect(pointerRemoves()).toBe(1)

  down(second)
  expect(scrollAdds()).toBe(2)
  expect(pointerAdds()).toBe(2)
  unmount()
  expect(scrollRemoves()).toBe(2)
  expect(pointerRemoves()).toBe(2)
})

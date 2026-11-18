import { afterEach, expect, mock, spyOn, test } from 'bun:test'
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import * as sdk from '../api/generated/sdk.gen'
import { GoogleSetup } from './GoogleSetup'
import { CalendarSetup } from './FeedSetup'
import { de } from '../i18n/de'

const calendars = [
  { id: 'work@example.org', name: 'Werkstatt', timezone: 'Europe/Berlin', source_id: null },
  { id: 'garden@example.org', name: 'Garten', timezone: 'UTC', source_id: null },
  { id: 'connected@example.org', name: 'Bereits da', timezone: 'UTC', source_id: 'test-only-source' },
]

afterEach(() => { cleanup(); mock.restore() })
function setup() {
  const list = spyOn(sdk, 'calendarGoogleCalendarsList').mockResolvedValue({ data: { calendars } } as never)
  const connect = spyOn(sdk, 'calendarGoogleConnect').mockResolvedValue({ data: [] } as never)
  const close = mock(), saved = mock()
  render(<GoogleSetup close={close} saved={saved} />)
  return { list, connect, close, saved }
}

test('loads placeholders, then unselected choices and disabled connected choices', async () => {
  const list = spyOn(sdk, 'calendarGoogleCalendarsList')
  let resolve!: (value: never) => void
  list.mockReturnValue(new Promise<never>(done => { resolve = done }) as never)
  render(<GoogleSetup close={mock()} saved={mock()} />)
  const dialog = screen.getByRole('dialog', { name: de.calendar.googleConnect })
  expect(dialog.parentElement?.parentElement).toBe(document.body)
  expect(screen.getByRole('status').textContent).toBe(de.calendar.googleLoading)
  expect(dialog.querySelectorAll('.le-calendar-placeholder[aria-hidden="true"]').length).toBe(3)
  await act(async () => { resolve({ data: { calendars } } as never) })
  const first = screen.getByRole('checkbox', { name: 'Werkstatt' }) as HTMLInputElement
  expect(first.checked).toBe(false)
  const connected = screen.getByRole('checkbox', { name: 'Bereits da' }) as HTMLInputElement
  expect(connected.checked).toBe(true)
  expect(connected.disabled).toBe(true)
  expect(screen.getByText(de.calendar.googleConnected)).toBeTruthy()
  expect((screen.getByRole('button', { name: de.calendar.googleConnectCount(0) }) as HTMLButtonElement).disabled).toBe(true)
  expect(screen.queryByRole('status')).toBeNull()
})

test('selection count excludes existing connections and sends only explicitly selected calendars', async () => {
  const { connect, saved } = setup()
  fireEvent.click(await screen.findByRole('checkbox', { name: 'Werkstatt' }))
  expect(screen.getByRole('button', { name: de.calendar.googleConnectCount(1) })).toBeTruthy()
  fireEvent.click(screen.getByRole('checkbox', { name: 'Garten' }))
  expect(screen.getByRole('button', { name: de.calendar.googleConnectCount(2) })).toBeTruthy()
  fireEvent.click(screen.getByRole('checkbox', { name: 'Werkstatt' }))
  fireEvent.click(screen.getByRole('button', { name: de.calendar.googleConnectCount(1) }))
  await waitFor(() => expect(saved).toHaveBeenCalledTimes(1))
  expect(connect).toHaveBeenCalledWith({ body: { calendar_ids: ['garden@example.org'] } })
})

test('connect success from CalendarSetup invalidates the calendar group and closes', async () => {
  spyOn(sdk, 'calendarGoogleCalendarsList').mockResolvedValue({ data: { calendars } } as never)
  spyOn(sdk, 'calendarGoogleConnect').mockResolvedValue({ data: [] } as never)
  const query = new QueryClient()
  const invalidated = spyOn(query, 'invalidateQueries')
  render(<QueryClientProvider client={query}><CalendarSetup /></QueryClientProvider>)
  fireEvent.click(screen.getByRole('button', { name: de.calendar.googleConnect }))
  fireEvent.click(await screen.findByRole('checkbox', { name: 'Werkstatt' }))
  fireEvent.click(screen.getByRole('button', { name: de.calendar.googleConnectCount(1) }))
  await waitFor(() => expect(invalidated).toHaveBeenCalledWith({ queryKey: ['calendar'] }))
  expect(screen.queryByRole('dialog')).toBeNull()
})

test.each([409, 502])('discovery status %s shows a fixed error and retry rereads the provider', async status => {
  const list = spyOn(sdk, 'calendarGoogleCalendarsList').mockResolvedValueOnce({ error: {}, response: { status } } as never).mockResolvedValue({ data: { calendars } } as never)
  render(<GoogleSetup close={mock()} saved={mock()} />)
  expect(await screen.findByText(status === 409 ? de.calendar.googleNotConnected : de.calendar.googleError)).toBeTruthy()
  expect(screen.queryAllByRole('checkbox')).toHaveLength(0)
  fireEvent.click(screen.getByRole('button', { name: de.calendar.retry }))
  expect(await screen.findByRole('checkbox', { name: 'Werkstatt' })).toBeTruthy()
  expect(list).toHaveBeenCalledTimes(2)
})

test('empty list is explained and offers a fresh read', async () => {
  spyOn(sdk, 'calendarGoogleCalendarsList').mockResolvedValue({ data: { calendars: [] } } as never)
  render(<GoogleSetup close={mock()} saved={mock()} />)
  expect(await screen.findByText(de.calendar.googleEmpty)).toBeTruthy()
  expect(screen.getByRole('button', { name: de.calendar.retry })).toBeTruthy()
  expect((screen.getByRole('button', { name: de.calendar.googleConnectCount(0) }) as HTMLButtonElement).disabled).toBe(true)
})

test.each([409, 502])('failed connection %s preserves selection without provider text', async status => {
  const { connect, saved } = setup()
  connect.mockResolvedValue({ error: { detail: 'private-value' }, response: { status } } as never)
  fireEvent.click(await screen.findByRole('checkbox', { name: 'Werkstatt' }))
  fireEvent.click(screen.getByRole('button', { name: de.calendar.googleConnectCount(1) }))
  expect(await screen.findByText(status === 409 ? de.calendar.googleNotConnected : de.calendar.googleSaveError)).toBeTruthy()
  expect((screen.getByRole('checkbox', { name: 'Werkstatt' }) as HTMLInputElement).checked).toBe(true)
  expect(saved).not.toHaveBeenCalled()
  expect(screen.getByRole('dialog').textContent).not.toContain('private-value')
})

test('focus stays in the portal and Escape and the scrim dismiss idle setup', async () => {
  const { close } = setup()
  await screen.findByRole('checkbox', { name: 'Werkstatt' })
  const dialog = screen.getByRole('dialog')
  const cancel = within(dialog).getByRole('button', { name: de.calendar.cancel })
  cancel.focus()
  fireEvent.keyDown(document, { key: 'Tab', shiftKey: true })
  expect(dialog.contains(document.activeElement)).toBe(true)
  fireEvent.click(dialog)
  expect(close).not.toHaveBeenCalled()
  fireEvent.click(dialog.parentElement!)
  expect(close).toHaveBeenCalledTimes(1)
  fireEvent.keyDown(document, { key: 'Escape' })
  expect(close).toHaveBeenCalledTimes(2)
})

test('selection is bounded to twenty new calendars', async () => {
  spyOn(sdk, 'calendarGoogleCalendarsList').mockResolvedValue({ data: { calendars: Array.from({ length: 21 }, (_, i) => ({ ...calendars[0], id: `calendar-${i}`, name: `Kalender ${i}` })) } } as never)
  render(<GoogleSetup close={mock()} saved={mock()} />)
  const choices = await screen.findAllByRole('checkbox')
  for (const choice of choices.slice(0, 20)) fireEvent.click(choice)
  expect((choices[20] as HTMLInputElement).disabled).toBe(true)
  expect(screen.getByText(de.calendar.googleLimit)).toBeTruthy()
  expect(screen.getByRole('button', { name: de.calendar.googleConnectCount(20) })).toBeTruthy()
  fireEvent.click(choices[0]!)
  expect((choices[20] as HTMLInputElement).disabled).toBe(false)
})
test('the selection hint no longer promises that nothing is changed at Google', () => {
  expect(de.calendar.googleChoose).not.toMatch(/ändert nichts/)
  expect(de.calendar.googleChoose).toMatch(/bestätigst/)
})

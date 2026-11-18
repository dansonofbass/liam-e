import { afterEach, expect, mock, spyOn, test } from 'bun:test'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import * as sdk from '../api/generated/sdk.gen'
import type { SourceOut, LiveEvent } from '../api/generated/types.gen'
import { EventDialog } from './EventDialog'
const sources = [{ id: 's', name: 'Planung', is_active: true, capabilities: ['read', 'write'] }, { id: 'r', name: 'Nur lesen', is_active: true, capabilities: ['read'] }] as SourceOut[]
afterEach(() => { cleanup(); mock.restore() })
function mount(initial: { date: string; minute?: number } | LiveEvent = { date: '2026-11-20', minute: 540 }, mode: 'create' | 'edit' = 'create') {
  const close = mock(() => {})
  render(<QueryClientProvider client={new QueryClient()}><EventDialog mode={mode} initial={initial} sources={sources} onClose={close} /></QueryClientProvider>)
  return close
}
function title() { fireEvent.change(screen.getByLabelText('Titel'), { target: { value: 'Testtermin' } }) }
test('slot prefills one hour and only writable calendars', () => {
  mount(); expect((screen.getByLabelText('Beginn') as HTMLInputElement).value).toBe('2026-11-20T09:00')
  expect((screen.getByLabelText('Ende') as HTMLInputElement).value).toBe('2026-11-20T10:00')
  expect(screen.queryByText('Nur lesen')).toBeNull()
})
test('month slot is all-day and sends exclusive end', async () => {
  const create = spyOn(sdk, 'calendarEventCreate').mockResolvedValue({ data: { status: 'done' }, response: { status: 201 } } as never)
  mount({ date: '2026-11-20' }); title()
  expect((screen.getByLabelText('Ganztägig') as HTMLInputElement).checked).toBe(true)
  fireEvent.click(screen.getByRole('button', { name: 'Speichern' }))
  await waitFor(() => expect(create).toHaveBeenCalledTimes(1))
  expect(create.mock.calls[0]?.[0]?.body).toMatchObject({ start_date: '2026-11-20', end_date: '2026-11-21' })
})
test('double submission is locked and unknown can only be checked', async () => {
  let resolve!: (value: never) => void
  const create = spyOn(sdk, 'calendarEventCreate').mockImplementation(() => new Promise(r => { resolve = r }) as never)
  const check = spyOn(sdk, 'calendarWriteCheck').mockResolvedValue({ data: { status: 'done' }, response: { status: 200 } } as never)
  const close = mount(); title()
  fireEvent.click(screen.getByRole('button', { name: 'Speichern' })); fireEvent.click(screen.getByRole('button', { name: 'Speichern' }))
  expect(create).toHaveBeenCalledTimes(1)
  resolve({ data: { status: 'unknown' }, response: { status: 202 } } as never)
  fireEvent.click(await screen.findByRole('button', { name: 'Prüfen' }))
  await waitFor(() => expect(close).toHaveBeenCalledTimes(1))
  expect(check.mock.calls[0]?.[0]?.path.write_id).toBe(create.mock.calls[0]?.[0]?.body.write_id)
  expect(screen.queryByRole('button', { name: 'Erneut versuchen' })).toBeNull()
})
test('not applied offers a new attempt with a new ID', async () => {
  const create = spyOn(sdk, 'calendarEventCreate').mockResolvedValue({ data: { status: 'not_applied' }, response: { status: 200 } } as never)
  mount(); title(); fireEvent.click(screen.getByRole('button', { name: 'Speichern' }))
  fireEvent.click(await screen.findByRole('button', { name: 'Erneut versuchen' }))
  fireEvent.click(screen.getByRole('button', { name: 'Speichern' }))
  await waitFor(() => expect(create).toHaveBeenCalledTimes(2))
  expect(create.mock.calls[0]?.[0]?.body.write_id).not.toBe(create.mock.calls[1]?.[0]?.body.write_id)
})
test('conflict shows current values and adopting rereads live before a new edit', async () => {
  const before = { occurrence_id: 'e', source_id: 's', title: 'Planung', start_date: '2026-11-20', end_date: '2026-11-21', revision: 'v1', editable: true }
  const update = spyOn(sdk, 'calendarEventUpdate').mockResolvedValue({ error: { detail: { status: 'not_applied', error_code: 'calendar_event_changed', current: { ...before, title: 'Geänderte Planung', revision: 'v2' } } }, response: { status: 409 } } as never)
  const read = spyOn(sdk, 'calendarOccurrenceLive').mockResolvedValue({ data: { ...before, title: 'Aktuelle Planung', revision: 'v3' }, response: { status: 200 } } as never)
  mount(before, 'edit'); title(); fireEvent.click(screen.getByRole('button', { name: 'Speichern' }))
  await screen.findByText('Geänderte Planung')
  expect(screen.queryByRole('button', { name: 'Speichern' })).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: 'Übernehmen und neu bearbeiten' }))
  await waitFor(() => expect((screen.getByLabelText('Titel') as HTMLInputElement).value).toBe('Aktuelle Planung'))
  expect(read).toHaveBeenCalledTimes(1)
  title(); fireEvent.click(screen.getByRole('button', { name: 'Speichern' }))
  await waitFor(() => expect(update).toHaveBeenCalledTimes(2))
  expect(update.mock.calls[1]?.[0]?.body.expected_revision).toBe('v3')
  expect(update.mock.calls[1]?.[0]?.body.write_id).not.toBe(update.mock.calls[0]?.[0]?.body.write_id)
})
test('edit sends only changed fields and explicit clearing', async () => {
  const update = spyOn(sdk, 'calendarEventUpdate').mockResolvedValue({ data: { status: 'done' }, response: { status: 200 } } as never)
  mount({ occurrence_id: 'e', source_id: 's', title: 'Planung', start_date: '2026-11-20', end_date: '2026-11-21', location: 'Raum', revision: 'v1', editable: true }, 'edit')
  fireEvent.change(screen.getByLabelText('Ort'), { target: { value: '' } })
  fireEvent.click(screen.getByRole('button', { name: 'Speichern' }))
  await waitFor(() => expect(update).toHaveBeenCalledTimes(1))
  const body = update.mock.calls[0]?.[0]?.body
  expect(body).toEqual({ write_id: expect.any(String), expected_revision: 'v1', location: '' })
})

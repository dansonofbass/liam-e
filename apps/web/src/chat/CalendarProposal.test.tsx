import { afterEach, expect, mock, spyOn, test } from 'bun:test'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import * as sdk from '../api/generated/sdk.gen'
import type { ChatMessageOut } from '../api/generated/types.gen'
import { CalendarProposal } from './CalendarProposal'
const message = { created_at: '2026-11-20T09:00:00Z', extras: {}, stopped: false, tool_name: '', id: 'proposal', conversation_id: 'conversation', role: 'assistant', content: '', proposal_status: 'pending', proposal: { kind: 'calendar', reason: 'Zeit anpassen', items: [], calendar: { action: 'update', source_id: 's', timezone: 'Europe/Berlin', before: { source_id: 's', title: 'Vorheriger Termin', start_date: '2026-11-20', end_date: '2026-11-21' }, after: { title: 'Neuer Titel', start_date: '2026-11-21', end_date: '2026-11-22', location: 'Raum' } } } } as ChatMessageOut
afterEach(() => { cleanup(); mock.restore() })
function mount(value = message) {
  spyOn(sdk, 'calendarSourcesList').mockResolvedValue({ data: [{ id: 's', name: 'Planung', is_active: true, chat_access: 'writable', capabilities: ['read', 'write'] }] } as never)
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(<QueryClientProvider client={client}><CalendarProposal message={value} /></QueryClientProvider>)
  return client
}
test('update shows before and after, calendar and timezone', async () => {
  mount()
  await screen.findByText('Planung')
  expect(screen.getByText('Bisher')).toBeTruthy(); expect(screen.getByText('Vorschlag')).toBeTruthy()
  expect(screen.getByText('Vorheriger Termin')).toBeTruthy(); expect(screen.getByText('Neuer Titel')).toBeTruthy()
  expect(screen.getByText(/Europe\/Berlin/)).toBeTruthy()
})
test('delete warns about undo', async () => {
  mount({ ...message, proposal: { ...message.proposal!, calendar: { ...message.proposal!.calendar!, action: 'delete', after: null } } })
  await screen.findByText('Planung')
  expect(screen.getByText(/nicht garantiert rückgängig/)).toBeTruthy()
})
test('unknown has check but no confirm and updates to done', async () => {
  const check = spyOn(sdk, 'chatProposalCheck').mockResolvedValue({ data: { ...message, proposal_status: 'done' }, response: { status: 200 } } as never)
  mount({ ...message, proposal_status: 'unknown' })
  fireEvent.click(await screen.findByRole('button', { name: 'Prüfen' }))
  expect(screen.queryByRole('button', { name: 'Bestätigen' })).toBeNull()
  await screen.findByText('Termin geändert.')
  expect(check).toHaveBeenCalledTimes(1)
})
test('confirmation invalidates calendar and cannot be repeated', async () => {
  const confirm = spyOn(sdk, 'chatProposalConfirm').mockResolvedValue({ data: { ...message, proposal_status: 'done' }, response: { status: 200 } } as never)
  const client = mount(), invalidate = spyOn(client, 'invalidateQueries')
  await screen.findByText('Planung')
  fireEvent.click(await screen.findByRole('button', { name: 'Bestätigen' }))
  await screen.findByText('Termin geändert.')
  expect(screen.queryByRole('button', { name: 'Bestätigen' })).toBeNull()
  await waitFor(() => expect(invalidate).toHaveBeenCalledWith({ queryKey: ['calendar'] }))
  expect(confirm.mock.calls[0]?.[0]?.body).toEqual({ selected_ids: [] })
})
test('a card left running after an interrupted confirm can be checked', async () => {
  const check = spyOn(sdk, 'chatProposalCheck').mockResolvedValue({ data: { ...message, proposal_status: 'done' }, response: { status: 200 } } as never)
  mount({ ...message, proposal_status: 'running' })
  fireEvent.click(await screen.findByRole('button', { name: 'Prüfen' }))
  await screen.findByText('Termin geändert.')
  expect(check).toHaveBeenCalledTimes(1)
})
test('a definite refusal outside the conversation scope is not called unclear', async () => {
  mount({ ...message, proposal_status: 'failed', proposal: { ...message.proposal!, result: { done: 0, failed: [{ id: 'proposal', code: 'calendar_out_of_scope' }] } } } as ChatMessageOut)
  await screen.findByText(/nicht zur Kalenderauswahl/)
  expect(screen.queryByText(/noch unklar/)).toBeNull()
})
test('a confirm that never reached the server returns to the open card after a check', async () => {
  spyOn(sdk, 'chatProposalConfirm').mockRejectedValue(new TypeError('test-only'))
  const check = spyOn(sdk, 'chatProposalCheck').mockResolvedValue({ error: { detail: { error_code: 'proposal_not_pending' } }, response: { status: 409 } } as never)
  mount()
  await screen.findByText('Planung')
  fireEvent.click(screen.getByRole('button', { name: 'Bestätigen' }))
  fireEvent.click(await screen.findByRole('button', { name: 'Prüfen' }))
  // The server still has the card pending: confirm and cancel come back, with no stale error.
  await screen.findByRole('button', { name: 'Bestätigen' })
  expect(screen.getByRole('button', { name: 'Abbrechen' })).toBeTruthy()
  expect(screen.queryByRole('button', { name: 'Prüfen' })).toBeNull()
  expect(screen.queryByRole('alert')).toBeNull()
  expect(check).toHaveBeenCalledTimes(1)
})

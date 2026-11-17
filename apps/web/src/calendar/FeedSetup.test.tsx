import { afterEach, expect, mock, spyOn, test } from 'bun:test'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import * as sdk from '../api/generated/sdk.gen'
import { FeedSetup } from './FeedSetup'
import { de } from '../i18n/de'

afterEach(() => { cleanup(); mock.restore() })
const preview = { validation_id: 'test-only-proof', name: 'Verein', coverage_start: '2026-01-01T00:00:00Z', coverage_end: '2026-02-01T00:00:00Z', occurrence_count: 2, expires_at: '2026-01-01T00:10:00Z', format_issues: [] }
function setup() {
  const validate = spyOn(sdk, 'calendarFeedValidate').mockResolvedValue({ data: preview } as never)
  const subscribe = spyOn(sdk, 'calendarFeedSubscribe').mockResolvedValue({ data: { id: 'test-only-source' } } as never)
  const discard = spyOn(sdk, 'calendarFeedValidationDiscard').mockResolvedValue({} as never)
  const saved = mock(), close = mock()
  render(<FeedSetup saved={saved} close={close} />)
  fireEvent.change(screen.getByLabelText(de.calendar.feedName), { target: { value: 'Verein' } })
  fireEvent.change(screen.getByLabelText(de.calendar.feedAddress), { target: { value: 'webcal://calendar.example/test-only' } })
  fireEvent.change(screen.getByLabelText(de.calendar.feedZone), { target: { value: 'UTC' } })
  return { validate, subscribe, discard, saved, close }
}

test('setup normalizes visibly, previews without address and subscribes only after checking', async () => {
  const { validate, subscribe, saved } = setup()
  expect(screen.getByRole('dialog', { name: de.calendar.subscribe })).toBeTruthy()
  expect(screen.getByText(de.calendar.feedReadOnly)).toBeTruthy()
  expect(screen.queryByRole('button', { name: de.calendar.subscribeConfirm })).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: de.calendar.feedCheck }))
  expect(await screen.findByText(de.calendar.feedCount(2))).toBeTruthy()
  expect((screen.getByLabelText(de.calendar.feedAddress) as HTMLInputElement).value).toBe('https://calendar.example/test-only')
  expect(validate.mock.calls[0]?.[0]?.body?.timezone).toBe('UTC')
  expect(subscribe).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole('button', { name: de.calendar.subscribeConfirm }))
  await waitFor(() => expect(saved).toHaveBeenCalledTimes(1))
  expect(subscribe.mock.calls[0]?.[0]?.body?.validation_id).toBe(preview.validation_id)
})

test.each([de.calendar.feedName, de.calendar.feedAddress, de.calendar.feedZone])('changing %s invalidates and discards the proof', async label => {
  const { discard, subscribe } = setup()
  fireEvent.click(screen.getByRole('button', { name: de.calendar.feedCheck }))
  await screen.findByText(de.calendar.feedCount(2))
  fireEvent.change(screen.getByLabelText(label), { target: { value: 'changed' } })
  expect(screen.queryByRole('button', { name: de.calendar.subscribeConfirm })).toBeNull()
  expect(discard).toHaveBeenCalledWith({ body: { validation_id: preview.validation_id } })
  expect(subscribe).not.toHaveBeenCalled()
})

test('failed checks expose only a fixed message and never allow subscription', async () => {
  const { validate, subscribe } = setup()
  validate.mockRejectedValue(new Error('https://calendar.example/test-only'))
  fireEvent.click(screen.getByRole('button', { name: de.calendar.feedCheck }))
  expect(await screen.findByText(de.calendar.feedError)).toBeTruthy()
  expect(screen.queryByRole('button', { name: de.calendar.subscribeConfirm })).toBeNull()
  expect(subscribe).not.toHaveBeenCalled()
  expect(screen.getByRole('dialog').textContent).not.toContain('calendar.example')
})

test('expired proof requires another check; Escape dismisses an idle dialog', async () => {
  const { subscribe, close } = setup()
  fireEvent.click(screen.getByRole('button', { name: de.calendar.feedCheck }))
  await screen.findByText(de.calendar.feedCount(2))
  subscribe.mockResolvedValue({ error: { detail: 'calendar_validation_expired_or_changed' } } as never)
  fireEvent.click(screen.getByRole('button', { name: de.calendar.subscribeConfirm }))
  expect(await screen.findByText(de.calendar.feedSaveError)).toBeTruthy()
  expect(screen.queryByRole('button', { name: de.calendar.subscribeConfirm })).toBeNull()
  fireEvent.keyDown(document, { key: 'Escape' })
  expect(close).toHaveBeenCalled()
})

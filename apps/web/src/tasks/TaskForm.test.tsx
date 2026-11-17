// i18n-exempt: synthetic API fixtures.
import { afterEach, expect, test } from 'bun:test'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { client as api } from '../api/generated/client.gen'
import { TaskForm } from './TaskForm'

const originalFetch = globalThis.fetch, originalConfig = api.getConfig()
afterEach(() => { cleanup(); globalThis.fetch = originalFetch; api.setConfig(originalConfig) })

test('weekdays are independently selectable chips', () => {
  const query = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(<QueryClientProvider client={query}><TaskForm busy={false} save={() => {}} /></QueryClientProvider>)
  fireEvent.click(screen.getByRole('button', { name: 'Wiederholung' }))
  fireEvent.click(screen.getByRole('menuitemradio', { name: 'Benutzerdefiniert' }))
  fireEvent.click(screen.getByRole('button', { name: 'Rhythmus' }))
  fireEvent.click(screen.getByRole('menuitemradio', { name: 'Wöchentlich' }))
  const monday = screen.getByRole('button', { name: 'Mo.' })
  const tuesday = screen.getByRole('button', { name: 'Di.' })
  fireEvent.click(monday); fireEvent.click(tuesday)
  expect(monday.getAttribute('aria-pressed')).toBe('true')
  expect(tuesday.getAttribute('aria-pressed')).toBe('true')
  fireEvent.click(monday)
  expect(monday.getAttribute('aria-pressed')).toBe('false')
  expect(tuesday.getAttribute('aria-pressed')).toBe('true')
})

test('invalid time zones show an explanation and prevent saving', () => {
  const query = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(<QueryClientProvider client={query}><TaskForm busy={false} save={() => { throw new Error('unexpected save') }} /></QueryClientProvider>)
  fireEvent.change(screen.getByLabelText('Zeitzone'), { target: { value: 'Invalid/Zone' } })
  expect(screen.getByText(/Gib eine gültige Zeitzone ein/)).toBeTruthy()
  expect((screen.getByRole('button', { name: 'Aufgabe speichern' }) as HTMLButtonElement).disabled).toBe(true)
})

test('the form renders and accepts a zone without Intl.supportedValuesOf', () => {
  const intl = Intl as { supportedValuesOf?: unknown }, original = intl.supportedValuesOf
  intl.supportedValuesOf = undefined
  try {
    const query = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(<QueryClientProvider client={query}><TaskForm busy={false} save={() => {}} /></QueryClientProvider>)
    fireEvent.change(screen.getByLabelText('Zeitzone'), { target: { value: 'Europe/Berlin' } })
    expect(screen.queryByText(/Gib eine gültige Zeitzone ein/)).toBeNull()
  } finally { intl.supportedValuesOf = original }
})

test('late preview cannot replace a newer schedule and failed save preserves inputs', async () => {
  api.setConfig({ baseUrl: 'https://api.example.test' })
  const pending: { start: string; resolve: (response: Response) => void }[] = []
  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const req = input instanceof Request ? input : new Request(input, init)
    const body = await req.clone().json() as { start: string }
    return await new Promise<Response>(resolve => pending.push({ start: body.start, resolve }))
  }) as typeof fetch
  const query = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  let saved = 0
  const view = render(<QueryClientProvider client={query}><TaskForm busy={false} save={() => { saved++ }} /></QueryClientProvider>)
  fireEvent.change(screen.getByLabelText('Titel'), { target: { value: 'Plan prüfen' } })
  fireEvent.change(screen.getByLabelText('Erstes Datum'), { target: { value: '2027-01-01' } })
  await waitFor(() => expect(pending.length).toBe(1))
  fireEvent.change(screen.getByLabelText('Erstes Datum'), { target: { value: '2027-01-02' } })
  await waitFor(() => expect(pending.length).toBe(2))
  const answer = (value: string) => Response.json({ occurrences: [value], exceptions: [], through: value, complete: true })
  await act(async () => pending[1]!.resolve(answer('2027-01-02')))
  await screen.findByText(/2\.1\.2027/)
  await act(async () => pending[0]!.resolve(answer('2027-01-01')))
  expect(screen.queryByText(/1\.1\.2027/)).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: 'Aufgabe speichern' }))
  expect(saved).toBe(1)
  view.rerender(<QueryClientProvider client={query}><TaskForm busy={false} save={() => { saved++ }} error="Nicht gespeichert" /></QueryClientProvider>)
  expect((screen.getByLabelText('Titel') as HTMLInputElement).value).toBe('Plan prüfen')
  expect(screen.getByText('Nicht gespeichert')).toBeTruthy()
})

// i18n-exempt: route paths and technical identifiers.
import { afterEach, expect, mock, spyOn, test } from 'bun:test'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createMemoryHistory, createRootRoute, createRoute, createRouter, RouterProvider } from '@tanstack/react-router'
import * as sdk from '../api/generated/sdk.gen'
import { CalendarView } from './CalendarView'
import { MonthView } from './MonthView'
import { TimeGrid } from './TimeGrid'
import { de } from '../i18n/de'
import { I18nProvider } from '../i18n/I18n'
import { calendarTime } from './state'
import { resetUnresolvedWrites, trackWrite } from './write-state'

const originalMatchMedia = window.matchMedia
const mobile = () => { window.matchMedia = ((query: string) => ({ matches: query === '(pointer: coarse)', media: query, addEventListener() {}, removeEventListener() {} })) as unknown as typeof window.matchMedia }
afterEach(() => { cleanup(); mock.restore(); window.matchMedia = originalMatchMedia; resetUnresolvedWrites() })
const source = { id: 'test-only', name: 'Planung', provider: 'google', timezone: 'UTC', is_active: true, capabilities: ['read'], coverage_start: '2026-01-01T00:00:00Z', coverage_end: '2027-01-01T00:00:00Z', last_success_at: '2026-11-18T00:00:00Z', stale: false, incomplete: false }
const event = (id: string) => ({ id, event_id: id, source_id: source.id, title: `Termin ${id}`, start_at: '2026-11-18T09:00:00Z', end_at: '2026-11-18T10:00:00Z', start_date: null, end_date: null, timezone: 'UTC' })
function setup(initial = '/calendar?view=week&date=2026-11-18') {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } })
  const root = createRootRoute({ component: () => <QueryClientProvider client={client}><CalendarView /></QueryClientProvider> })
  const page = createRoute({ getParentRoute: () => root, path: '/calendar' })
  const router = createRouter({ routeTree: root.addChildren([page]), history: createMemoryHistory({ initialEntries: [initial] }) })
  render(<RouterProvider router={router} />)
  return router
}
for (const writable of [true, false]) test(`slot writing follows capability: ${writable}`, async () => {
  spyOn(sdk, 'calendarSourcesList').mockResolvedValue({ data: [{ ...source, capabilities: writable ? ['read', 'write'] : ['read'] }] } as never)
  spyOn(sdk, 'calendarOccurrencesList').mockResolvedValue({ data: { items: [], next_cursor: null } } as never)
  spyOn(sdk, 'calendarSourceSync').mockResolvedValue({ data: { queued: false }, response: { ok: true } } as never)
  setup('/calendar?view=day&date=2026-11-18')
  await screen.findByText(de.calendar.empty)
  fireEvent.click(screen.getByRole('button', { name: /18\.11\.2026, 09:00/ }))
  if (writable) {
    expect(screen.getByRole('dialog', { name: de.calendar.newEvent })).toBeTruthy()
    expect((screen.getByLabelText(de.calendar.eventStart) as HTMLInputElement).value).toBe('2026-11-18T09:00')
    expect((screen.getByLabelText(de.calendar.eventEnd) as HTMLInputElement).value).toBe('2026-11-18T10:00')
  } else {
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(screen.queryByRole('button', { name: de.calendar.addEvent })).toBeNull()
  }
})
test('mobile defaults to day and offers seven dates with the selected day pressed', async () => {
  mobile()
  spyOn(sdk, 'calendarSourcesList').mockResolvedValue({ data: [source] } as never)
  spyOn(sdk, 'calendarOccurrencesList').mockResolvedValue({ data: { items: [], next_cursor: null } } as never)
  spyOn(sdk, 'calendarSourceSync').mockResolvedValue({ data: { queued: false }, response: { ok: true } } as never)
  setup('/calendar?date=2026-11-18')
  expect((await screen.findByRole('button', { name: de.calendar.day })).getAttribute('aria-pressed')).toBe('true')
  const strip = screen.getByRole('group', { name: de.calendar.dayStrip })
  const buttons = strip.querySelectorAll('button')
  expect(buttons).toHaveLength(7)
  expect([...buttons].every(button => /(?:Mo|Di|Mi|Do|Fr|Sa|So)/.test(button.textContent ?? '') && /\d/.test(button.textContent ?? ''))).toBe(true)
  expect([...buttons].filter(button => button.getAttribute('aria-pressed') === 'true')).toHaveLength(1)
})
test('mobile month shows dots and the selected day appointments', async () => {
  mobile()
  spyOn(sdk, 'calendarSourcesList').mockResolvedValue({ data: [source] } as never)
  spyOn(sdk, 'calendarOccurrencesList').mockResolvedValue({ data: { items: [event('a')], next_cursor: null } } as never)
  spyOn(sdk, 'calendarSourceSync').mockResolvedValue({ data: { queued: false }, response: { ok: true } } as never)
  setup('/calendar?view=month&date=2026-11-18')
  const selected = await screen.findByRole('button', { name: /18\.11\.2026/ })
  await waitFor(() => expect(selected.querySelector('.le-month-dot')).toBeTruthy())
  expect(screen.getByRole('link', { name: /Termin a/ }).closest('.le-month-mobile-list')).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: /19\.11\.2026/ }))
  expect(screen.queryByRole('link', { name: /Termin a/ })).toBeNull()
})
test('all-day gutter wraps its complete label rather than clipping it', async () => {
  const css = await Bun.file(new URL('./calendar.css', import.meta.url)).text()
  const rule = css.match(/\.le-time-all-label \{([^}]+)\}/u)?.[1] ?? ''
  expect(rule).toContain('overflow-wrap: anywhere')
  expect(rule).not.toContain('overflow: hidden')
  const root = createRootRoute({ component: () => <TimeGrid from="2026-11-18" to="2026-11-19" rows={[]} sources={[]} onSlot={() => {}} onOpen={() => {}} /> })
  const router = createRouter({ routeTree: root, history: createMemoryHistory({ initialEntries: ['/'] }) })
  render(<RouterProvider router={router} />)
  const label = await screen.findByText(de.calendar.allDayGutter)
  expect(label.getAttribute('aria-hidden')).not.toBe('true')
  // A soft hyphen gives a German break point; Chromium on Linux has no hyphenation dictionary.
  expect(de.calendar.allDayGutter).toBe('Ganz\u00ADtägig')
  expect(rule).not.toContain('hyphens: auto')
})
test('mobile calendar targets have coarse pointer token sizing', async () => {
  const css = await Bun.file(new URL('./calendar.css', import.meta.url)).text()
  const coarse = css.match(/@media \(pointer: coarse\) \{([\s\S]*?)\n\}/gu)?.join('\n') ?? ''
  expect(coarse).toContain('.le-month-date')
  expect(coarse).toContain('.le-day-strip .le-chip')
  expect(coarse).toContain('min-height: var(--control-height-lg)')
  expect(coarse).toContain('min-width: var(--control-height-lg)')
})
test('toolbar changes view and period in the URL', async () => {
  spyOn(sdk, 'calendarSourcesList').mockResolvedValue({ data: [source] } as never)
  spyOn(sdk, 'calendarOccurrencesList').mockResolvedValue({ data: { items: [event('a')], next_cursor: null } } as never)
  spyOn(sdk, 'calendarSourceSync').mockResolvedValue({ data: { queued: false }, response: { ok: true } } as never)
  const router = setup()
  expect(await screen.findByRole('link', { name: new RegExp(`Termin a.*${calendarTime(event('a').start_at!)}.*${calendarTime(event('a').end_at!)}`) })).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: de.calendar.month }))
  await waitFor(() => expect(router.state.location.searchStr).toContain('view=month'))
  fireEvent.click(screen.getByRole('button', { name: de.calendar.next }))
  await waitFor(() => expect(router.state.location.searchStr).toContain('date=2026-12-18'))
})
test('month overflow opens the selected day', async () => {
  const openDay = mock(() => {})
  const root = createRootRoute({ component: () => <MonthView date="2026-11-18" rows={Array.from({ length: 5 }, (_, i) => event(String(i)))} sources={[source]} onDay={openDay} onSlot={() => {}} onOpen={() => {}} /> })
  const router = createRouter({ routeTree: root, history: createMemoryHistory({ initialEntries: ['/'] }) })
  render(<RouterProvider router={router} />)
  fireEvent.click(await screen.findByRole('button', { name: /2 weitere/ }))
  expect(openDay).toHaveBeenCalledWith('2026-11-18')
})
test('incomplete coverage never claims an empty range', async () => {
  spyOn(sdk, 'calendarSourcesList').mockResolvedValue({ data: [{ ...source, incomplete: true }] } as never)
  spyOn(sdk, 'calendarOccurrencesList').mockResolvedValue({ data: { items: [], next_cursor: null } } as never)
  spyOn(sdk, 'calendarSourceSync').mockResolvedValue({ data: { queued: false }, response: { ok: true } } as never)
  setup()
  expect(await screen.findByText(de.calendar.unknown)).toBeTruthy()
  expect(screen.queryByText(de.calendar.empty)).toBeNull()
})
test('month draws all-day events as a single span across the week', async () => {
  const row = { ...event('urlaub'), start_at: null, end_at: null, start_date: '2026-11-20', end_date: '2026-11-23' }
  const root = createRootRoute({ component: () => <MonthView date="2026-11-18" rows={[row]} sources={[source]} onDay={() => {}} onSlot={() => {}} onOpen={() => {}} /> })
  const router = createRouter({ routeTree: root, history: createMemoryHistory({ initialEntries: ['/'] }) })
  render(<RouterProvider router={router} />)
  const span = await screen.findByRole('link', { name: /Termin urlaub/ })
  expect(screen.getAllByRole('link', { name: /Termin urlaub/ })).toHaveLength(1)
  expect(span.style.gridColumn).toBe('5 / span 3')
})
test('padded results outside the visible range do not hide a covered empty state', async () => {
  spyOn(sdk, 'calendarSourcesList').mockResolvedValue({ data: [source] } as never)
  spyOn(sdk, 'calendarOccurrencesList').mockResolvedValue({ data: { items: [{ ...event('outside'), start_at: '2026-11-24T09:00:00Z', end_at: '2026-11-24T10:00:00Z' }], next_cursor: null } } as never)
  spyOn(sdk, 'calendarSourceSync').mockResolvedValue({ data: { queued: false }, response: { ok: true } } as never)
  setup()
  expect(await screen.findByText(de.calendar.empty)).toBeTruthy()
})
test('manual refresh reports failure instead of silently swallowing it', async () => {
  spyOn(sdk, 'calendarSourcesList').mockResolvedValue({ data: [source] } as never)
  spyOn(sdk, 'calendarOccurrencesList').mockResolvedValue({ data: { items: [], next_cursor: null } } as never)
  spyOn(sdk, 'calendarSourceSync').mockResolvedValue({ error: { detail: 'test-only' }, response: { ok: false } } as never)
  setup()
  await screen.findByText(de.calendar.empty)
  await waitFor(() => expect((screen.getByRole('button', { name: de.calendar.refresh }) as HTMLButtonElement).disabled).toBe(false))
  fireEvent.click(screen.getByRole('button', { name: de.calendar.refresh }))
  expect(await screen.findByText((text) => text.includes(de.calendar.refreshError))).toBeTruthy()
})
test('pagination stops after ten pages and reports the cap', async () => {
  spyOn(sdk, 'calendarSourcesList').mockResolvedValue({ data: [source] } as never)
  const pages = spyOn(sdk, 'calendarOccurrencesList').mockResolvedValue({ data: { items: [], next_cursor: 'next' } } as never)
  spyOn(sdk, 'calendarSourceSync').mockResolvedValue({ data: { queued: false }, response: { ok: true } } as never)
  setup()
  expect(await screen.findByText(de.calendar.capped)).toBeTruthy()
  expect(pages).toHaveBeenCalledTimes(10)
})

test('toolbar exposes a single pressed view and icon navigation', async () => {
  spyOn(sdk, 'calendarSourcesList').mockResolvedValue({ data: [source] } as never)
  spyOn(sdk, 'calendarOccurrencesList').mockResolvedValue({ data: { items: [], next_cursor: null } } as never)
  spyOn(sdk, 'calendarSourceSync').mockResolvedValue({ data: { queued: false }, response: { ok: true } } as never)
  setup()
  await screen.findByRole('button', { name: de.calendar.previous })
  expect(screen.getByRole('button', { name: de.calendar.next })).toBeTruthy()
  const group = screen.getByRole('group', { name: 'Ansicht' })
  expect(group.querySelectorAll('button')).toHaveLength(4)
  expect(group.querySelectorAll('[aria-pressed="true"]')).toHaveLength(1)
})
test('time grid shows gutter, empty slots, spanning all-day and timed events', async () => {
  const allDay = { ...event('all'), start_at: null, end_at: null, start_date: '2026-11-18', end_date: '2026-11-20' }
  const root = createRootRoute({ component: () => <TimeGrid from="2026-11-18" to="2026-11-25" rows={[event('a'), allDay]} sources={[source]} onSlot={() => {}} onOpen={() => {}} /> })
  const router = createRouter({ routeTree: root, history: createMemoryHistory({ initialEntries: ['/'] }) })
  render(<RouterProvider router={router} />)
  await screen.findByRole('link', { name: /Termin all/ })
  expect(document.querySelectorAll('.le-time-hour')).toHaveLength(23)
  expect([...document.querySelectorAll('.le-time-slot')].every(el => el.textContent === '')).toBe(true)
  expect((screen.getByRole('link', { name: /Termin all/ }) as HTMLElement).style.gridColumn).toContain('span 2')
  expect(screen.getByRole('link', { name: /Termin a,/ }).textContent).toContain(calendarTime(event('a').start_at!))
})
test('with a touch pointer back-to-back short appointments share the width instead of overlapping', async () => {
  mobile()
  const rows = [{ ...event('a'), start_at: '2026-11-18T09:00:00Z', end_at: '2026-11-18T09:30:00Z' }, { ...event('b'), start_at: '2026-11-18T09:30:00Z', end_at: '2026-11-18T10:00:00Z' }]
  const root = createRootRoute({ component: () => <TimeGrid from="2026-11-18" to="2026-11-19" rows={rows} sources={[source]} onSlot={() => {}} onOpen={() => {}} /> })
  const router = createRouter({ routeTree: root, history: createMemoryHistory({ initialEntries: ['/'] }) })
  render(<RouterProvider router={router} />)
  const first = await screen.findByRole('link', { name: /Termin a,/ })
  expect([(first as HTMLElement).style.width, (screen.getByRole('link', { name: /Termin b,/ }) as HTMLElement).style.width]).toEqual(['50%', '50%'])
})
test('month day button and empty cell have distinct actions', async () => {
  const onDay = mock(() => {}), onSlot = mock(() => {})
  const root = createRootRoute({ component: () => <MonthView date="2026-11-18" rows={[]} sources={[source]} onDay={onDay} onSlot={onSlot} onOpen={() => {}} /> })
  const router = createRouter({ routeTree: root, history: createMemoryHistory({ initialEntries: ['/'] }) })
  render(<RouterProvider router={router} />)
  fireEvent.click(await screen.findByRole('button', { name: '18.11.2026' }))
  expect(onDay).toHaveBeenCalledWith('2026-11-18')
  fireEvent.click(document.querySelector('[data-calendar-cell="2026-11-18"]')!)
  expect(onSlot).toHaveBeenCalledWith({ date: '2026-11-18' })
})

test('today is marked in the time header', async () => {
  const today = new Date(), day = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, '0')}-${String(today.getDate()).padStart(2, '0')}`
  const tomorrow = new Date(today.getFullYear(), today.getMonth(), today.getDate() + 1)
  const end = `${tomorrow.getFullYear()}-${String(tomorrow.getMonth() + 1).padStart(2, '0')}-${String(tomorrow.getDate()).padStart(2, '0')}`
  const root = createRootRoute({ component: () => <TimeGrid from={day} to={end} rows={[]} sources={[source]} onSlot={() => {}} onOpen={() => {}} /> })
  const router = createRouter({ routeTree: root, history: createMemoryHistory({ initialEntries: ['/'] }) })
  render(<RouterProvider router={router} />)
  await waitFor(() => expect(document.querySelector('.le-time-days [aria-current="date"]')).toBeTruthy())
})
test('toolbar wraps instead of letting the period title run under the buttons', async () => {
  const css = await Bun.file(new URL('./calendar.css', import.meta.url)).text()
  const rule = css.match(/^\.le-calendar-toolbar \{([^}]+)\}/mu)?.[1] ?? ''
  expect(rule).toContain('flex-wrap: wrap')
})
test('an unresolved create blocks new appointments until it is checked', async () => {
  spyOn(sdk, 'calendarSourcesList').mockResolvedValue({ data: [{ ...source, capabilities: ['read', 'write'] }] } as never)
  spyOn(sdk, 'calendarOccurrencesList').mockResolvedValue({ data: { items: [], next_cursor: null } } as never)
  spyOn(sdk, 'calendarSourceSync').mockResolvedValue({ data: { queued: false }, response: { ok: true } } as never)
  const check = spyOn(sdk, 'calendarWriteCheck').mockResolvedValue({ data: { write_id: 'test-only', status: 'done' }, response: { status: 200 } } as never)
  trackWrite({ writeId: 'test-only', kind: 'create' }, 'unknown')
  setup('/calendar?view=day&date=2026-11-18')
  await screen.findByText(de.calendar.empty)
  expect((screen.getByRole('button', { name: de.calendar.addEvent }) as HTMLButtonElement).disabled).toBe(true)
  fireEvent.click(screen.getByRole('button', { name: /18\.11\.2026, 09:00/ }))
  expect(screen.queryByRole('dialog')).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: de.calendar.check }))
  await waitFor(() => expect((screen.getByRole('button', { name: de.calendar.addEvent }) as HTMLButtonElement).disabled).toBe(false))
  expect(check.mock.calls[0]?.[0]?.path.write_id).toBe('test-only')
  expect(screen.queryByText(de.calendar.unresolved)).toBeNull()
})
test('coarse pointers get 44 px view switch, month dates and overflow buttons, and the calendar row wraps', async () => {
  const css = await Bun.file(new URL('./calendar.css', import.meta.url)).text()
  // The base rules size these controls smaller at the same specificity, so the touch block wins
  // only as the last rule in the file. A text match alone let an inert rule pass before.
  const tail = css.slice(css.lastIndexOf('@media (pointer: coarse)'))
  let depth = 0, end = -1
  for (let i = 0; i < tail.length && end < 0; i++) { if (tail[i] === '{') depth++; else if (tail[i] === '}' && --depth === 0) end = i }
  expect(tail.slice(end + 1).trim()).toBe('')
  for (const selector of ['.le-month-week', '.le-calendar-switch .le-btn', '.le-month-more.le-btn', '.le-month-date.le-btn', '.le-day-strip .le-chip']) expect(tail).toContain(selector)
  expect(css.match(/^\.le-calendar-sources-row \{([^}]+)\}/mu)?.[1]).toContain('flex-wrap: wrap')
})
test('the list keeps its own range: no period navigation, but open writes stay visible', async () => {
  spyOn(sdk, 'calendarSourcesList').mockResolvedValue({ data: [{ ...source, capabilities: ['read', 'write'] }] } as never)
  spyOn(sdk, 'calendarOccurrencesList').mockResolvedValue({ data: { items: [], next_cursor: null } } as never)
  spyOn(sdk, 'calendarSourceSync').mockResolvedValue({ data: { queued: false }, response: { ok: true } } as never)
  trackWrite({ writeId: 'test-only', kind: 'create' }, 'unknown')
  setup('/calendar?view=list&date=2026-11-18')
  expect(await screen.findByText(de.calendar.unresolved)).toBeTruthy()
  expect(screen.queryByRole('button', { name: de.calendar.previous })).toBeNull()
  expect(screen.queryByRole('button', { name: de.calendar.next })).toBeNull()
  expect(screen.getByRole('button', { name: de.calendar.list }).getAttribute('aria-pressed')).toBe('true')
  // The embedded list brings no second page title and no second fetch button.
  expect(screen.getAllByRole('heading', { level: 1 })).toHaveLength(1)
  expect(screen.getAllByRole('button', { name: de.calendar.refresh })).toHaveLength(1)
  const css = await Bun.file(new URL('./calendar.css', import.meta.url)).text()
  const rule = css.match(/^\.le-calendar-grid-page > \.le-calendar-agenda \{([^}]+)\}/mu)?.[1] ?? ''
  expect(rule).toContain('overflow-y: auto')
  expect(rule).toContain('min-height: 0')
})


test('an English afternoon slot keeps its wall-clock position on a spring-forward day', () => {
  const browserOptions = Intl.DateTimeFormat().resolvedOptions()
  spyOn(Intl.DateTimeFormat.prototype, 'resolvedOptions').mockReturnValue({ ...browserOptions, timeZone: 'Europe/Berlin' })
  const onSlot = mock(() => {})
  render(<I18nProvider locale="en">
    <TimeGrid from="2026-03-29" to="2026-03-30" rows={[]} sources={[]} onSlot={onSlot} onOpen={() => {}} />
  </I18nProvider>)
  expect(screen.queryByRole('button', { name: /02:00 AM/ })).toBeNull()
  const slot = screen.getByRole('button', { name: /05:00 PM/ })
  expect(slot.style.top).toBe(`${17 * 48}px`)
  fireEvent.click(slot)
  expect(onSlot).toHaveBeenCalledWith({ date: '2026-03-29', minute: 17 * 60 })
})

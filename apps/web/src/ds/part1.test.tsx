import { describe, expect, test, mock, afterEach, spyOn } from 'bun:test'
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { IconButton } from './IconButton'
import { Menu } from './Menu'
import { Drawer } from './Drawer'
import { Avatar } from './Avatar'

afterEach(() => { cleanup(); mock.restore() })

describe('IconButton', () => {
  test('shows tooltip immediately on focus', () => {
    render(<IconButton label="Archivieren" icon="archive" shortcut="E" />)
    fireEvent.keyDown(document.body, { key: 'Tab' })
    act(() => screen.getByRole('button').focus())
    expect(screen.getByRole('tooltip').textContent).toBe('Archivieren (E)')
  })
  test('shows no tooltip when focus is not keyboard focus', () => {
    render(<IconButton label="Archivieren" icon="archive" />)
    fireEvent.focus(screen.getByRole('button'))
    expect(screen.queryByRole('tooltip')).toBeNull()
  })
  test('shows tooltip after hovering for 350 ms', () => {
    let callback: (() => void) | undefined
    let delay = 0
    spyOn(globalThis, 'setTimeout').mockImplementation(((fn: () => void, ms: number) => { callback = fn; delay = ms; return 1 }) as typeof setTimeout)
    const advance = (ms: number) => { delay -= ms; if (delay <= 0) callback?.() }
    render(<IconButton label="Archivieren" icon="archive" shortcut="E" />)
    fireEvent.mouseEnter(screen.getByRole('button'))
    act(() => { advance(349) })
    expect(screen.queryByRole('tooltip')).toBeNull()
    act(() => { advance(1) })
    expect(screen.getByRole('tooltip').textContent).toBe('Archivieren (E)')
  })
})

test('menu closes only on outside pointerdown without stealing focus', () => {
  render(<><Menu trigger={(props) => <button {...props}>Menü</button>} items={[{ label: 'Eins', onSelect: () => {} }]} /><button>Außen</button></>)
  const trigger = screen.getByRole('button', { name: 'Menü' })
  fireEvent.click(trigger)
  fireEvent.pointerDown(trigger)
  fireEvent.pointerDown(screen.getByRole('menuitem'))
  expect(screen.getByRole('menu')).toBeTruthy()
  const outside = screen.getByRole('button', { name: 'Außen' })
  outside.focus()
  fireEvent.pointerDown(outside)
  expect(screen.queryByRole('menu')).toBeNull()
  expect(document.activeElement).toBe(outside)
})

test('opening another menu closes the first even without a pointer', () => {
  render(<><Menu trigger={(props) => <button {...props}>Erstes Menü</button>} items={[{ label: 'Eins', onSelect: () => {} }]} /><Menu trigger={(props) => <button {...props}>Zweites Menü</button>} items={[{ label: 'Zwei', onSelect: () => {} }]} /></>)
  fireEvent.keyDown(document.body, { key: 'Tab' })
  const first = screen.getByRole('button', { name: 'Erstes Menü' })
  const second = screen.getByRole('button', { name: 'Zweites Menü' })
  fireEvent.click(first)
  fireEvent.click(second)
  expect(first.getAttribute('aria-expanded')).toBe('false')
  expect(second.getAttribute('aria-expanded')).toBe('true')
  expect(screen.getAllByRole('menu')).toHaveLength(1)
  expect(document.activeElement?.textContent).toBe('Zwei')
})

test('menu navigates and returns focus on Escape', () => {
  fireEvent.keyDown(document.body, { key: 'Tab' })
  render(<Menu trigger={(props) => <button {...props}>Menü</button>} items={[{ label: 'Eins', onSelect: () => {} }, { label: 'Zwei', onSelect: () => {} }]} />)
  const trigger = screen.getByRole('button')
  fireEvent.click(trigger)
  fireEvent.keyDown(screen.getByRole('menu'), { key: 'ArrowDown' })
  expect(document.activeElement?.textContent).toBe('Zwei')
  fireEvent.keyDown(screen.getByRole('menu'), { key: 'Escape' })
  expect(screen.queryByRole('menu')).toBeNull()
  expect(document.activeElement).toBe(trigger)
})

test('drawer traps focus and closes on Escape', () => {
  const close = mock(() => {})
  const { rerender } = render(<><button>Öffnen</button><Drawer open={false} onClose={close} label="Menü"><button>Erster</button><button>Letzter</button></Drawer></>)
  const trigger = screen.getByText('Öffnen')
  trigger.focus()
  rerender(<><button>Öffnen</button><Drawer open onClose={close} label="Menü"><button>Erster</button><button>Letzter</button></Drawer></>)
  screen.getByText('Letzter').focus()
  fireEvent.keyDown(document, { key: 'Tab' })
  expect(document.activeElement).toBe(screen.getByText('Erster'))
  fireEvent.keyDown(document, { key: 'Escape' })
  expect(close).toHaveBeenCalledTimes(1)
  rerender(<><button>Öffnen</button><Drawer open={false} onClose={close} label="Menü"><button>Erster</button><button>Letzter</button></Drawer></>)
  expect(document.activeElement).toBe(trigger)
})

test('avatar uses name initials or address fallback', () => {
  const { rerender } = render(<Avatar name="Hausverwaltung Kurz" colorIndex={0} />)
  expect(screen.getByText('HK')).toBeTruthy()
  rerender(<Avatar name="" address="max@example.org" colorIndex={0} />)
  expect(screen.getByText('M')).toBeTruthy()
})

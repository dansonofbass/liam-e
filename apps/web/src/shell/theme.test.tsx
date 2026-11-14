import { afterEach, beforeEach, expect, test } from 'bun:test'
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { THEME_STORAGE_KEY, applyTheme, readTheme, setTheme, themeScript } from './theme'
import { ThemeMenu } from './ThemeMenu'

beforeEach(() => { window.localStorage.clear(); document.documentElement.removeAttribute('data-theme') })
afterEach(() => { cleanup(); window.localStorage.clear(); document.documentElement.removeAttribute('data-theme') })
// The script runs as a classic script in the browser, where `localStorage` and `document` are globals; here they come from jsdom.
const runHeadScript = (storage: Pick<Storage, 'getItem'>) => new Function('localStorage', 'document', themeScript)(storage, document)

test('the head script applies a stored light or dark theme and ignores anything else', () => {
  window.localStorage.setItem(THEME_STORAGE_KEY, 'dark')
  runHeadScript(window.localStorage)
  expect(document.documentElement.getAttribute('data-theme')).toBe('dark')
  document.documentElement.removeAttribute('data-theme')
  window.localStorage.setItem(THEME_STORAGE_KEY, 'purple')
  runHeadScript(window.localStorage)
  expect(document.documentElement.hasAttribute('data-theme')).toBe(false)
  expect(readTheme()).toBe('system')
})

test('the head script survives blocked storage', () => {
  const original = Object.getOwnPropertyDescriptor(window, 'localStorage')!
  Object.defineProperty(window, 'localStorage', { configurable: true, get() { throw new Error('blocked') } })
  try {
    expect(() => runHeadScript({ getItem() { throw new Error('blocked') } })).not.toThrow()
    expect(document.documentElement.hasAttribute('data-theme')).toBe(false)
    expect(readTheme()).toBe('system')
    expect(() => setTheme('dark')).not.toThrow()
    expect(document.documentElement.getAttribute('data-theme')).toBe('dark')
  } finally {
    Object.defineProperty(window, 'localStorage', original)
  }
})

test('choosing a theme sets it on the document and stores it; system clears both', () => {
  render(<ThemeMenu placement="up-end" />)
  const trigger = screen.getByRole('button', { name: 'Darstellung' })
  fireEvent.click(trigger)
  expect(screen.getByRole('menu').classList.contains('le-menu--up-end')).toBe(true)
  const system = screen.getByRole('menuitemradio', { name: 'Wie im System' })
  expect(system.getAttribute('aria-checked')).toBe('true')
  expect(document.activeElement).toBe(system)
  expect(system.querySelector('.lucide-check')).toBeTruthy()
  fireEvent.click(screen.getByRole('menuitemradio', { name: 'Dunkel' }))
  expect(document.documentElement.getAttribute('data-theme')).toBe('dark')
  expect(window.localStorage.getItem(THEME_STORAGE_KEY)).toBe('dark')
  expect(document.activeElement).toBe(trigger)
  fireEvent.click(trigger)
  expect(screen.getByRole('menuitemradio', { name: 'Dunkel' }).getAttribute('aria-checked')).toBe('true')
  expect(screen.getByRole('menuitemradio', { name: 'Hell' }).getAttribute('aria-checked')).toBe('false')
  fireEvent.click(screen.getByRole('menuitemradio', { name: 'Wie im System' }))
  expect(document.documentElement.hasAttribute('data-theme')).toBe(false)
  expect(window.localStorage.getItem(THEME_STORAGE_KEY)).toBeNull()
})

test('a choice made in another tab applies here too', () => {
  render(<ThemeMenu placement="up-start" />)
  window.localStorage.setItem(THEME_STORAGE_KEY, 'light')
  act(() => { window.dispatchEvent(new window.StorageEvent('storage', { key: THEME_STORAGE_KEY })) })
  expect(document.documentElement.getAttribute('data-theme')).toBe('light')
  fireEvent.click(screen.getByRole('button', { name: 'Darstellung' }))
  expect(screen.getByRole('menuitemradio', { name: 'Hell' }).getAttribute('aria-checked')).toBe('true')
  applyTheme('system')
})

test('the root document runs the theme script in the head before anything else', async () => {
  const root = await Bun.file(new URL('../routes/__root.tsx', import.meta.url)).text()
  expect(root).toMatch(/<head>\s*\{\/\*[^]*?\*\/\}\s*<script dangerouslySetInnerHTML=\{\{ __html: themeScript \}\} \/>\s*<HeadContent \/>/u)
})

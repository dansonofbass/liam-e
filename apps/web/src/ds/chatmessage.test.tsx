import { afterEach, expect, test } from 'bun:test'
import { cleanup, render, screen } from '@testing-library/react'
import { ChatMessage } from './ChatMessage'

afterEach(cleanup)

test('the user bubble sits on the right with its small corner at the bottom right, like the boards', async () => {
  render(<ChatMessage role="user">Was ist heute wichtig?</ChatMessage>)
  expect(screen.getByText('Was ist heute wichtig?').classList.contains('le-msg-user')).toBe(true)
  const css = await Bun.file(new URL('../styles/ds.css', import.meta.url)).text()
  const rule = css.match(/\.le-msg-user \{([^}]*)\}/u)?.[1] ?? ''
  // top-left, top-right, bottom-right, bottom-left
  expect(rule).toContain('border-radius: 20px 20px 6px 20px')
  expect(rule).toContain('align-self: flex-end')
  expect(rule).toContain('background: var(--accent)')
  expect(css.match(/\.le-msg-user[^{]*\{[^}]*border-radius/gu)).toHaveLength(1)
})

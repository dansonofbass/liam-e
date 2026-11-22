import { afterEach, expect, test } from 'bun:test'
import { cleanup, render } from '@testing-library/react'
import { SafeMarkdown } from './SafeMarkdown'
afterEach(cleanup)
test('renders only safe links and no HTML or tracking images', () => {
  const { container } = render(<SafeMarkdown text={'<script>alert(1)</script>\n\n[x](javascript:alert(1)) [safe](https://example.org) [mail](mailto:a@example.org) ![pixel](https://example.org/x)'} />)
  expect(container.querySelector('script')).toBeNull()
  expect(container.querySelector('img')).toBeNull()
  const links = container.querySelectorAll('a')
  expect(links[0]!.hasAttribute('href')).toBe(false)
  expect(links[1]!.getAttribute('target')).toBe('_blank')
  expect(links[1]!.getAttribute('rel')).toBe('noopener noreferrer')
  expect(links[2]!.getAttribute('href')).toBe('mailto:a@example.org')
})

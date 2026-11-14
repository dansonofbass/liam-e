import { expect, test } from 'bun:test'

test('the viewport bounds the shell and its independently scrolling content', async () => {
  const base = await Bun.file(new URL('../styles/ds.css', import.meta.url)).text()
  const app = await Bun.file(new URL('../styles/ds-app.css', import.meta.url)).text()
  const rule = (css: string, selector: string) => css.split(`${selector} {`)[1]?.split('}')[0] ?? ''
  for (const property of ['height: 100dvh', 'overflow: hidden']) expect(rule(base, '.le-app')).toContain(property)
  expect(rule(base, '.le-app')).not.toContain('flex-wrap: wrap')
  for (const selector of ['.le-side', '.le-sheet']) expect(rule(base, selector)).toContain('min-height: 0')
  for (const selector of ['.le-page-fade', '.le-chat-view', '.le-inbox', '.le-inbox-list', '.le-mail-view']) expect(rule(app, selector)).toContain('min-height: 0')
  for (const selector of ['.le-chat-messages', '.le-inbox-scroll', '.le-mail-scroll', '.le-accounts-scroll']) {
    for (const property of ['min-height: 0', 'overflow-y: auto']) expect(rule(app, selector)).toContain(property)
  }
  for (const selector of ['.le-chat-composer', '.le-mail-bottom']) expect(rule(app, selector)).toContain('env(safe-area-inset-bottom)')
})

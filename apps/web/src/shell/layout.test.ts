import { expect, test } from 'bun:test'

test('conversation and composer share the same centred column', async () => {
  const css = await Bun.file(new URL('../styles/ds-app.css', import.meta.url)).text()
  const tokens = await Bun.file(new URL('../styles/tokens.css', import.meta.url)).text()
  const rule = (selector: string) => css.split(`${selector} {`)[1]?.split('}')[0] ?? ''
  for (const selector of ['.le-chat-thread', '.le-chat-composer']) {
    for (const property of ['width: 100%', 'max-width: var(--chat-width)', 'align-self: center', 'box-sizing: border-box']) expect(rule(selector)).toContain(property)
  }
  expect(rule('.le-chat-messages')).toContain('padding: var(--space-5)')
  expect(rule('.le-chat-composer')).toContain('var(--space-5)')
  expect(tokens).toContain('--chat-width: 780px')
  expect(tokens).toContain('--space-5: 24px')
})

test('start content is centred and quick actions use four columns or two on mobile', async () => {
  const css = await Bun.file(new URL('../styles/ds-app.css', import.meta.url)).text()
  const route = await Bun.file(new URL('../routes/_app/index.tsx', import.meta.url)).text()
  expect(route).toContain('le-chat-messages le-chat-thread le-chat-start-scroll')
  expect(css).toContain('.le-chat-start-scroll { display: flex; flex-direction: column; }')
  expect(css).toMatch(/\.le-chat-start \{[^}]*width: 100%; margin: auto 0;/u)
  expect(css).toMatch(/\.le-chat-quick-actions \{[^}]*grid-template-columns: repeat\(4, minmax\(0, 1fr\)\)/u)
  expect(css).toContain('@media (max-width: 639px) { .le-chat-quick-actions { grid-template-columns: repeat(2, minmax(0, 1fr)); } }')
})

test('shell navigation and composer have coarse pointer targets', async () => {
  const css = await Bun.file(new URL('../styles/ds-app.css', import.meta.url)).text()
  const rule = css.match(/@media \(pointer: coarse\) \{ (\.le-topbar \.le-icon-btn[^{}]+)\{ ([^{}]+) \} \.le-composer textarea \{ ([^{}]+) \} \}/u)
  expect(rule).toBeTruthy()
  for (const selector of ['.le-topbar .le-icon-btn', '.le-side .le-icon-btn', '.le-side .le-nav-item', '.le-side .le-conv', '.le-drawer .le-nav-item', '.le-drawer .le-conv']) expect(rule?.[1]).toContain(selector)
  for (const property of ['min-width: var(--control-height-lg)', 'min-height: var(--control-height-lg)']) expect(rule?.[2]).toContain(property)
  expect(rule?.[3]).toContain('min-height: var(--control-height-lg)')
})

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
  const insets = rule(app, '.le-app, .le-drawer')
  for (const edge of ['top', 'bottom', 'left', 'right']) expect(insets).toContain('env(safe-area-inset-' + edge + ')')
  for (const selector of ['.le-chat-composer', '.le-mail-bottom']) expect(rule(app, selector)).not.toContain('safe-area-inset-bottom')
})

test('only the sidebar conversation list scrolls, with room for focus rings', async () => {
  const css = await Bun.file(new URL('../styles/ds-app.css', import.meta.url)).text()
  const rule = (selector: string) => css.split(`${selector} {`)[1]?.split('}')[0] ?? ''
  for (const property of ['flex: 1', 'min-height: 0', 'overflow-y: auto', 'margin-inline: calc(-1 * var(--space-1))', 'padding-inline: var(--space-1)', 'padding-bottom: var(--space-1)']) expect(rule('.le-side .le-shell-conversations')).toContain(property)
  expect(rule('.le-shell-sidebar')).not.toContain('overflow')
  expect(rule('.le-shell-status')).toContain('margin-top: auto')
  expect(rule('.le-side .le-shell-status')).toBe('')
  expect(rule('.le-drawer')).toContain('overflow: auto')
  expect(rule('.le-drawer .le-shell-sidebar')).toContain('flex: 1 0 auto')
})

test('the conversations heading stays put while the list scrolls', async () => {
  const css = await Bun.file(new URL('../styles/ds-app.css', import.meta.url)).text()
  const rule = css.split('.le-shell-conversations > .le-side-label {')[1]?.split('}')[0] ?? ''
  for (const property of ['position: sticky', 'top: 0', 'background: var(--surface)']) expect(rule).toContain(property)
})

test('the model chip in the chat header gets a 44 px target on touch', async () => {
  const css = await Bun.file(new URL('../styles/ds-app.css', import.meta.url)).text()
  const coarse = css.split('@media (pointer: coarse) {').map(block => block.split('}')[0] ?? '')
  expect(coarse.some(block => block.includes('.le-chat-topbar .le-menu-anchor .le-chip') && block.includes('min-height: var(--control-height-lg)'))).toBe(true)
})

test('views with their own scroll area share one viewport-height rule', async () => {
  const css = await Bun.file(new URL('../styles/ds-app.css', import.meta.url)).text()
  const rules = css.match(/^[^{}\n]*\.le-app:has\([^{]*\{[^}]*\}/gmu) ?? []
  expect(rules).toHaveLength(1)
  for (const view of ['.le-accounts-scroll', '.le-chat-view', '.le-inbox']) expect(rules[0]).toContain(`.le-app:has(${view})`)
  for (const property of ['height: 100dvh', 'overflow: hidden']) expect(rules[0]).toContain(property)
})

test('menus scroll within 60 % of the screen and never beyond the room they have', async () => {
  const css = await Bun.file(new URL('../styles/ds-app.css', import.meta.url)).text()
  const rule = css.match(/(?:^|\n)\.le-menu \{([^}]*)\}/u)?.[1] ?? ''
  for (const property of ['max-width: calc(100vw - 2 * var(--space-4))', 'max-height: min(60dvh, var(--le-menu-room))', 'overflow-y: auto']) expect(rule).toContain(property)
  // The model menu aligns with its right-aligned chip through its placement (ModelMenu.tsx), not a CSS offset.
  expect(await Bun.file(new URL('../chat/ModelMenu.tsx', import.meta.url)).text()).toContain('<Menu placement="down-end"')
})

test('on a phone the main sheet fills the screen without frame, rounding or shadow', async () => {
  const css = await Bun.file(new URL('../styles/ds-app.css', import.meta.url)).text()
  const rule = css.match(/@media \(max-width: 639px\) \{ \.le-app \{ ([^}]+) \} \.le-sheet \{ ([^}]+) \} \}/u)
  expect(rule).toBeTruthy()
  for (const property of ['--shell-inset: 0px', 'gap: 0']) expect(rule?.[1]).toContain(property)
  for (const property of ['border-radius: 0', 'box-shadow: none']) expect(rule?.[2]).toContain(property)
})

test('a long conversation title cannot widen the sidebar past its token width', async () => {
  // A flex item's min-width defaults to its min-content width, and conversation titles do not wrap.
  const css = await Bun.file(new URL('../styles/ds.css', import.meta.url)).text()
  expect(css).toMatch(/^\.le-side \{ flex: 0 0 var\(--sidebar-width\); min-width: 0;/mu)
})

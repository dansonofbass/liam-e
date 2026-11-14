import { expect, test } from 'bun:test'

const read = (name: string) => Bun.file(new URL(`./${name}`, import.meta.url)).text()

test('the six text styles take their sizes from font-size tokens', async () => {
  const tokens = await read('tokens.css')
  const sizes = { display: '36px', title: '24px', heading: '17px', body: '14.5px', small: '13px', caption: '12px' }
  for (const [name, value] of Object.entries(sizes)) {
    expect(tokens).toContain(`--font-size-${name}: ${value};`)
    expect(tokens).toMatch(new RegExp(`^\\.${name} \\{[^}]*font-size: var\\(--font-size-${name}\\);`, 'mu'))
  }
  expect(tokens).toMatch(/^\.body-strong \{[^}]*font-size: var\(--font-size-body\);/mu)
  expect(tokens).not.toContain('tokens.json')
})

test('stylesheets have no free font sizes, no dead tooltip rules and no motion literals in app styles', async () => {
  const [ds, app] = await Promise.all([read('ds.css'), read('ds-app.css')])
  for (const css of [ds, app]) {
    expect(css).not.toMatch(/font-size: \d/u)
    expect(css).not.toMatch(/font: [^;]*\d+(\.\d+)?px/u)
    expect(css).not.toContain('[data-tip')
    expect(css).not.toContain('--le-tip-delay')
  }
  expect(app).not.toMatch(/\d+ms/u)
  expect(app).not.toContain('cubic-bezier(')
  for (const unused of ['.le-avatar--sm', '.le-notice--warm']) expect(ds).not.toContain(unused)
})

test('with reduced motion content still fades in but no longer rises, and page changes keep their fade', async () => {
  const [ds, app] = await Promise.all([read('ds.css'), read('ds-app.css')])
  expect(ds).toContain('@keyframes le-fade { from { opacity: 0; } to { opacity: 1; } }')
  const reduce = ds.split('@media (prefers-reduced-motion: reduce) {')[1]?.split('\n}')[0] ?? ''
  expect(reduce).toContain('.le-rise { animation-name: le-fade; }')
  expect(reduce).not.toMatch(/\.le-rise[^{]*\{ animation: none/u)
  expect(app).toMatch(/\.le-page-fade \{[^}]*animation: le-fade /u)
  expect(app).not.toMatch(/prefers-reduced-motion: reduce\) \{ \.le-page-fade/u)
  expect(app).toContain('@media (prefers-reduced-motion: reduce) { .le-drawer { animation-name: le-fade; } }')
})

test('every custom property the stylesheets read is defined, and radii come from the radius tokens', async () => {
  const [tokens, ds, app] = await Promise.all([read('tokens.css'), read('ds.css'), read('ds-app.css')])
  const defined = new Set([...`${tokens}\n${ds}\n${app}`.matchAll(/(--[\w-]+):/gu)].map(match => match[1]))
  for (const css of [ds, app]) {
    for (const [, name] of css.matchAll(/var\((--[\w-]+)/gu)) expect(defined.has(name!)).toBe(true)
    for (const [, value] of css.matchAll(/border-radius: ([^;]+);/gu)) expect(value).not.toMatch(/(^|[\s(])\d+px/u)
  }
})

test('padding, margin and gap sit on the 4 px grid', async () => {
  for (const css of await Promise.all([read('ds.css'), read('ds-app.css')])) {
    for (const [, property, value] of css.matchAll(/(?<![\w-])(padding|margin|gap|row-gap|column-gap)(?:-[a-z]+)?: ([^;}]+)/gu)) {
      for (const [, px] of value!.matchAll(/(-?\d+(?:\.\d+)?)px/gu)) expect({ property, px: Number(px) % 4 }).toEqual({ property, px: 0 })
    }
  }
})

test('every base control reaches 44 px with a coarse pointer, wherever it sits', async () => {
  const ds = await read('ds.css')
  const block = ds.match(/@media \(pointer: coarse\) \{\n  ([^{}]+)\{ ([^{}]+) \}\n\}/u)
  expect(block).not.toBeNull()
  const selectors = block![1]!.split(',').map(selector => selector.trim())
  for (const control of ['.le-btn', '.le-icon-btn', '.le-send', '.le-chip', '.le-nav-item', '.le-conv', '.le-menu-item']) expect(selectors).toContain(control)
  expect(block![2]).toContain('min-width: var(--control-height-lg)')
  expect(block![2]).toContain('min-height: var(--control-height-lg)')
})

test('the breakpoints agree in the hook, the media queries and the Tailwind names', async () => {
  // DESIGN.md §7.1: mobile below 640 px, tablet to 1023 px, desktop from 1024 px, wide from 1440 px.
  const hook = await Bun.file(new URL('../shell/useBreakpoint.tsx', import.meta.url)).text()
  for (const width of [640, 1024, 1440]) expect(hook).toContain(`'(min-width: ${width}px)'`)
  const index = await Bun.file(new URL('../index.css', import.meta.url)).text()
  expect(index).toContain('--breakpoint-tablet: 40rem;')
  expect(index).toContain('--breakpoint-desktop: 64rem;')
  expect(index).toContain('--breakpoint-wide: 90rem;')
  const css = (await read('ds.css')) + (await read('ds-app.css'))
  const widths = [...css.matchAll(/\((min|max)-width: (\d+)px\)/gu)].map(([, kind, px]) => `${kind} ${px}`)
  expect(widths.length).toBeGreaterThan(0)
  for (const width of widths) expect(['max 639', 'max 1023', 'min 640', 'min 1024', 'min 1440']).toContain(width)
})

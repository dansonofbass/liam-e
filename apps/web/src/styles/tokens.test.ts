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

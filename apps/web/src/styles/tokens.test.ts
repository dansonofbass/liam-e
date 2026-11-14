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

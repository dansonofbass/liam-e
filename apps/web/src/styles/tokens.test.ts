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

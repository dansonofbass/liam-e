import { expect, test } from 'bun:test'
import { readdirSync } from 'node:fs'
import { join, relative } from 'node:path'

// DESIGN.md §6 and §7.2: controls are control-height (38 px) tall; the 44 px of control-height-lg
// is the touch target for a coarse pointer, which ds.css already gives every base control.
// A stylesheet that sets it without `pointer: coarse` makes one view taller than the rest.
const root = new URL('..', import.meta.url).pathname
const base = /\.le-(btn|chip|icon-btn|send|link)(?![\w-])[^\s>+~]*$/u
// Bars that DESIGN.md sizes at 44 px on every pointer: the mail reader's bottom bar exists only on mobile (§7.4).
const allowed = new Set(['.le-mail-bottom .le-btn'])

function files(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap(entry => entry.isDirectory() ? files(join(dir, entry.name)) : entry.name.endsWith('.css') ? [join(dir, entry.name)] : [])
}

/** Rules as [media condition chain, selector, declarations]; comments removed, nesting by braces. */
function rules(css: string) {
  const out: [string, string, string][] = []
  const stack: string[] = []
  const text = css.replace(/\/\*[\s\S]*?\*\//gu, '')
  let buffer = ''
  for (const char of text) {
    if (char === '{') { stack.push(buffer.trim()); buffer = '' }
    else if (char === '}') {
      const prelude = stack.pop() ?? ''
      if (!prelude.startsWith('@')) out.push([stack.join(' '), prelude, buffer])
      buffer = ''
    } else buffer += char
  }
  return out
}

test('no stylesheet makes a control 44 px tall outside a coarse pointer', async () => {
  const offending: string[] = []
  for (const file of files(root)) {
    for (const [media, selector, body] of rules(await Bun.file(file).text())) {
      if (!/(min-)?height:\s*var\(--control-height-lg\)/u.test(body) || /pointer:\s*coarse/u.test(media)) continue
      for (const part of selector.split(',').map(s => s.trim())) {
        if (base.test(part) && !allowed.has(part)) offending.push(`${relative(root, file)}: ${part}`)
      }
    }
  }
  expect(offending).toEqual([])
})

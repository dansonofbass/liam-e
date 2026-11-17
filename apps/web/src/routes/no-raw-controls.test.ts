import { expect, test } from 'bun:test'
import { readdirSync, readFileSync } from 'node:fs'
import { join, relative } from 'node:path'

const root = import.meta.dir
const LEGACY_ROUTES: string[] = []
function files(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap(entry => entry.isDirectory() ? files(join(dir, entry.name)) : [join(dir, entry.name)])
}
test('routes do not contain raw controls outside legacy pages', () => {
  const paths = files(root)
  const names = paths.map(path => relative(root, path))
  for (const legacy of LEGACY_ROUTES) expect(names).toContain(legacy)
  const rawControl = new RegExp('<' + '(?:button|input)\\b', 'i')
  for (const path of paths) {
    if (!LEGACY_ROUTES.includes(relative(root, path))) expect(readFileSync(path, 'utf8')).not.toMatch(rawControl)
  }
})

test('task screens use design system controls', () => {
  const rawControl = new RegExp('<' + '(?:button|input|select)\\b')
  for (const path of files(join(root, '..', 'tasks'))) expect(readFileSync(path, 'utf8')).not.toMatch(rawControl)
})

test('the app-wide error and not-found screens build on the design system too', () => {
  const source = readFileSync(join(root, '..', 'root-screens', 'de.tsx'), 'utf8')
  // Case-sensitive: the design system's Button component is what these screens should use.
  expect(source).not.toMatch(new RegExp('<' + '(?:button|input)\\b'))
  for (const screen of ['MissingChunk:', 'ErrorScreen:', 'NotFound:']) expect(source).toContain(screen)
})

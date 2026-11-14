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

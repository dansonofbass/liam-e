import { expect, test } from 'bun:test'
import { createTypewriter } from './typewriter'

test('drains large buffers three code points per tick and finish waits', async () => {
  let fn: (() => void) | undefined
  const scheduler = { set(f: () => void, ms: number) { expect(ms).toBe(24); fn = f; return f }, clear() { fn = undefined } }
  let text = '', finished = false
  const writer = createTypewriter({ onText: value => { text = value }, schedule: scheduler })
  writer.push('😀'.repeat(300))
  void writer.finish().then(() => { finished = true })
  for (let i = 1; i <= 100; i++) { const tick = fn!; fn = undefined; tick(); expect(Array.from(text)).toHaveLength(i * 3); if (i < 100) expect(finished).toBe(false) }
  await Promise.resolve(); expect(finished).toBe(true)
})
test('reduced motion emits immediately; flush and cancel settle', async () => {
  let text = ''
  const writer = createTypewriter({ reducedMotion: true, onText: value => { text = value } })
  writer.push('abc'); expect(text).toBe('abc'); await writer.finish()
  writer.cancel(); writer.push('x'); expect(text).toBe('abc')
  const next = createTypewriter({ onText: value => { text = value } }); next.push('hello'); const done = next.finish(); next.flushNow(); await done; expect(text).toBe('hello')
})

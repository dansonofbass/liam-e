import { expect, test } from 'bun:test'
import { parseSse } from './sse'

test('parses split UTF-8, lines, CRLF, comments and multiline data; drops incomplete frame', async () => {
  const bytes = new TextEncoder().encode(': ping\r\nevent: delta\r\ndata: hä\r\ndata: llo\r\n\r\ndata: dropped')
  const split = bytes.indexOf(0xc3) + 1
  const stream = new ReadableStream<Uint8Array>({ start(c) { c.enqueue(bytes.slice(0, 9)); c.enqueue(bytes.slice(9, split)); c.enqueue(bytes.slice(split)); c.close() } })
  expect(await Array.fromAsync(parseSse(stream))).toEqual([{ event: 'delta', data: 'hä\nllo' }])
})
test('handles CR split from LF and default event', async () => {
  const enc = new TextEncoder()
  const stream = new ReadableStream<Uint8Array>({ start(c) { for (const s of ['data: x\r', '\n\r', '\n']) c.enqueue(enc.encode(s)); c.close() } })
  expect(await Array.fromAsync(parseSse(stream))).toEqual([{ event: 'message', data: 'x' }])
})

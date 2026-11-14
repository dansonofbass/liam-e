export async function* parseSse(stream: ReadableStream<Uint8Array>): AsyncIterable<{ event: string; data: string }> {
  const reader = stream.getReader()
  const decoder = new TextDecoder()
  let buffer = '', event = '', data: string[] = []
  try {
    while (true) {
      const result = await reader.read()
      buffer += decoder.decode(result.value, { stream: !result.done })
      let index: number
      while ((index = buffer.search(/[\r\n]/u)) !== -1) {
        if (buffer[index] === '\r' && index === buffer.length - 1 && !result.done) break
        const line = buffer.slice(0, index)
        const length = buffer[index] === '\r' && buffer[index + 1] === '\n' ? 2 : 1
        buffer = buffer.slice(index + length)
        if (!line) {
          if (data.length) yield { event: event || 'message', data: data.join('\n') }
          event = ''; data = []
        } else if (!line.startsWith(':')) {
          const colon = line.indexOf(':')
          const field = colon < 0 ? line : line.slice(0, colon)
          let value = colon < 0 ? '' : line.slice(colon + 1)
          if (value.startsWith(' ')) value = value.slice(1)
          if (field === 'data') data.push(value)
          else if (field === 'event') event = value
        }
      }
      if (result.done) break
    }
  } finally {
    await reader.cancel().catch(() => {})
    reader.releaseLock()
  }
}

type Scheduler = { set(fn: () => void, ms: number): unknown; clear(handle: unknown): void }
export function createTypewriter({ charsPerTick = 3, tickMs = 24, reducedMotion = false, onText, schedule }: { charsPerTick?: number; tickMs?: number; reducedMotion?: boolean; onText: (visible: string) => void; schedule?: Scheduler }) {
  const clock = schedule ?? { set: (fn: () => void, ms: number) => setTimeout(fn, ms), clear: (handle: unknown) => clearTimeout(handle as ReturnType<typeof setTimeout>) }
  let visible = '', buffer: string[] = [], timer: unknown, cancelled = false
  let waiters: (() => void)[] = []
  const settle = () => { if (!buffer.length) { const pending = waiters; waiters = []; pending.forEach(resolve => resolve()) } }
  const clear = () => { if (timer !== undefined) { clock.clear(timer); timer = undefined } }
  const tick = () => { timer = undefined; visible += buffer.splice(0, charsPerTick).join(''); onText(visible); settle(); arm() }
  const arm = () => { if (buffer.length && timer === undefined && !cancelled) timer = clock.set(tick, tickMs) }
  return {
    push(text: string) { if (cancelled) return; buffer.push(...Array.from(text)); if (reducedMotion) { visible += buffer.join(''); buffer = []; onText(visible); settle() } else arm() },
    finish(): Promise<void> { return buffer.length ? new Promise(resolve => { waiters.push(resolve) }) : Promise.resolve() },
    flushNow() { clear(); if (buffer.length) { visible += buffer.join(''); buffer = []; onText(visible) } settle() },
    cancel() { cancelled = true; clear(); buffer = []; settle() },
  }
}

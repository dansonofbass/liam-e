import { describe, expect, mock, test } from 'bun:test'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

import { LOCALE_COOKIE } from '../i18n/locales'
import { registerServiceWorker, type VisibilityDocumentLike } from './register'
import { setupServiceWorker, type WorkerScopeLike } from './service-worker'

function createScope(overrides: Partial<WorkerScopeLike> = {}) {
  const listeners = new Map<string, Array<(event: any) => void>>()
  const skipWaiting = mock(async () => {})
  const claim = mock(async () => {})
  const scope: WorkerScopeLike = {
    location: { origin: 'https://mail.example.test' },
    navigator: { languages: ['en-US'] },
    clients: { claim },
    skipWaiting,
    addEventListener(type, listener) {
      const list = listeners.get(type) ?? []
      list.push(listener)
      listeners.set(type, list)
    },
    ...overrides,
  }
  return { scope, listeners, skipWaiting, claim }
}

function pngDimensions(bytes: Uint8Array): { width: number; height: number; colorType: number } {
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength)
  return {
    width: view.getUint32(16),
    height: view.getUint32(20),
    colorType: bytes[25] ?? -1,
  }
}

describe('PWA service worker', () => {
  test('activates immediately on install and claims existing clients without CacheStorage', async () => {
    const { scope, listeners, skipWaiting, claim } = createScope()
    setupServiceWorker(scope)

    const installPromises: Promise<unknown>[] = []
    for (const fn of listeners.get('install') ?? []) {
      fn({ waitUntil: (promise: Promise<unknown>) => installPromises.push(promise) })
    }
    await Promise.all(installPromises)
    expect(skipWaiting).toHaveBeenCalledTimes(1)

    const activatePromises: Promise<unknown>[] = []
    for (const fn of listeners.get('activate') ?? []) {
      fn({ waitUntil: (promise: Promise<unknown>) => activatePromises.push(promise) })
    }
    await Promise.all(activatePromises)
    expect(claim).toHaveBeenCalledTimes(1)
  })

  test('ignores non-GET, non-navigation, cross-origin and /api requests', async () => {
    const fetcher = mock(async () => new Response('ok'))
    const { scope, listeners } = createScope()
    setupServiceWorker(scope, fetcher as unknown as typeof fetch)
    const [onFetch] = listeners.get('fetch') ?? []
    expect(onFetch).toBeDefined()

    const cases = [
      { method: 'POST', mode: 'navigate', url: 'https://mail.example.test/mail' },
      { method: 'GET', mode: 'cors', url: 'https://mail.example.test/api/v1/mail/summary' },
      { method: 'GET', mode: 'navigate', url: 'https://mail.example.test/api' },
      { method: 'GET', mode: 'navigate', url: 'https://mail.example.test/api/v1/mail/accounts/oauth/google/authorize' },
      { method: 'GET', mode: 'navigate', url: 'https://other.example.test/' },
    ]
    for (const request of cases) {
      let responded = false
      onFetch!({ request, respondWith: () => { responded = true } })
      expect(responded).toBe(false)
    }
    expect(fetcher).not.toHaveBeenCalled()
  })

  test('passes through HTTP responses including auth redirects and server errors', async () => {
    const redirectResponse = new Response(null, { status: 302, headers: { Location: 'https://auth.example.test/login' } })
    const fetcher = mock(async () => redirectResponse)
    const { scope, listeners } = createScope()
    setupServiceWorker(scope, fetcher as unknown as typeof fetch)
    const [onFetch] = listeners.get('fetch') ?? []

    let promise: Promise<Response> | undefined
    onFetch!({
      request: { method: 'GET', mode: 'navigate', url: 'https://mail.example.test/mail/123' },
      respondWith: (p: Promise<Response>) => { promise = p },
    })
    const result = await promise
    expect(result).toBe(redirectResponse)
  })

  test('synthesizes safe-area-aware no-store offline HTML on network failure using cookie or language fallback', async () => {
    const fetcher = mock(async () => { throw new TypeError('network down') })
    const { scope, listeners } = createScope({
      navigator: { languages: [], language: 'de-DE' },
      cookieStore: { get: async (name: string) => (name === LOCALE_COOKIE ? { value: 'en' } : undefined) },
    })
    setupServiceWorker(scope, fetcher as unknown as typeof fetch)
    const [onFetch] = listeners.get('fetch') ?? []

    let enPromise: Promise<Response> | undefined
    onFetch!({
      request: { method: 'GET', mode: 'navigate', url: 'https://mail.example.test/mail' },
      respondWith: (p: Promise<Response>) => { enPromise = p },
    })
    const enRes = await enPromise!
    expect(enRes.status).toBe(503)
    expect(enRes.headers.get('Cache-Control')).toBe('no-store')
    expect(enRes.headers.get('Content-Type')).toContain('text/html')
    const enHtml = await enRes.text()
    expect(enHtml).toContain('<html lang="en">')
    expect(enHtml).toContain('viewport-fit=cover')
    expect(enHtml).toContain('env(safe-area-inset-bottom)')
    expect(enHtml).toContain('min-height: 44px')
    expect(enHtml).toContain('You’re offline')

    const deSetup = createScope({
      navigator: { languages: [], language: 'de-AT' },
      cookieStore: undefined,
    })
    setupServiceWorker(deSetup.scope, fetcher as unknown as typeof fetch)
    let dePromise: Promise<Response> | undefined
    deSetup.listeners.get('fetch')![0]!({
      request: { method: 'GET', mode: 'navigate', url: 'https://mail.example.test/' },
      respondWith: (p: Promise<Response>) => { dePromise = p },
    })
    const deHtml = await (await dePromise!).text()
    expect(deHtml).toContain('<html lang="de">')
    expect(deHtml).toContain('Du bist offline')
  })

  test('service worker source never reads or writes CacheStorage', () => {
    const source = readFileSync(resolve(import.meta.dir, 'service-worker.ts'), 'utf8')
    expect(source).not.toMatch(/\bcaches\b/u)
  })
})

describe('PWA bootstrap & manifest', () => {
  test('registerServiceWorker uses updateViaCache: none and checks updates on foreground resume', async () => {
    let time = 100_000
    const update = mock(async () => {})
    const register = mock(async () => ({ update }))
    const visibilityListeners = new Set<() => void>()
    let state: DocumentVisibilityState = 'hidden'
    const doc: VisibilityDocumentLike = {
      get visibilityState() { return state },
      addEventListener(_type, fn) { visibilityListeners.add(fn) },
      removeEventListener(_type, fn) { visibilityListeners.delete(fn) },
    }

    const dispose = registerServiceWorker('/service-worker.js', {
      container: { register },
      doc,
      now: () => time,
      throttleMs: 60_000,
    })
    await Promise.resolve()

    expect(register).toHaveBeenCalledWith('/service-worker.js', { updateViaCache: 'none' })
    state = 'visible'
    for (const fn of visibilityListeners) fn()
    expect(update).toHaveBeenCalledTimes(0)

    time += 60_000
    for (const fn of visibilityListeners) fn()
    expect(update).toHaveBeenCalledTimes(1)

    dispose()
    expect(visibilityListeners.size).toBe(0)
  })

  test('manifest separates any and maskable icons backed by opaque PNG assets', () => {
    const publicDir = resolve(import.meta.dir, '../../public')
    const manifest = JSON.parse(readFileSync(resolve(publicDir, 'manifest.webmanifest'), 'utf8')) as {
      id: string
      name: string
      short_name: string
      start_url: string
      scope: string
      display: string
      icons: Array<{ src: string; sizes: string; type: string; purpose: string }>
    }

    expect(manifest.id).toBe('/')
    expect(manifest.start_url).toBe('/')
    expect(manifest.scope).toBe('/')
    expect(manifest.display).toBe('standalone')
    expect(manifest.icons.some(icon => icon.purpose.includes(' '))).toBe(false)
    expect(manifest.icons.some(icon => icon.purpose === 'any' && icon.sizes === '192x192')).toBe(true)
    expect(manifest.icons.some(icon => icon.purpose === 'any' && icon.sizes === '512x512')).toBe(true)
    expect(manifest.icons.some(icon => icon.purpose === 'maskable' && icon.sizes === '192x192')).toBe(true)
    expect(manifest.icons.some(icon => icon.purpose === 'maskable' && icon.sizes === '512x512')).toBe(true)

    for (const [file, size] of [['app-180.png', 180], ['app-192.png', 192], ['app-512.png', 512]] as const) {
      const info = pngDimensions(readFileSync(resolve(publicDir, file)))
      expect(info.width).toBe(size)
      expect(info.height).toBe(size)
      expect(info.colorType).toBe(2) // Opaque RGB PNG without alpha channel
    }
  })

  test('root head includes PWA bootstrap meta tags, viewport-fit, interactive-widget and credentials manifest', () => {
    const rootSource = readFileSync(resolve(import.meta.dir, '../routes/__root.tsx'), 'utf8')
    expect(rootSource).toContain('viewport-fit=cover')
    expect(rootSource).toContain('interactive-widget=resizes-content')
    expect(rootSource).toContain('apple-mobile-web-app-capable')
    expect(rootSource).toContain('mobile-web-app-capable')
    expect(rootSource).toContain('apple-mobile-web-app-title')
    expect(rootSource).toContain('crossOrigin: "use-credentials"')
    expect(rootSource).toContain('rel: "apple-touch-icon"')
  })
})

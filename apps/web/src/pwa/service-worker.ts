/// <reference lib="webworker" />
import { browserLocale, isLocale, LOCALE_COOKIE } from '../i18n/locales'
import { offline } from '../i18n/offline'

export interface WorkerScopeLike {
  location: { origin: string }
  navigator: { languages?: readonly string[]; language?: string }
  cookieStore?: { get(name: string): Promise<{ value?: string } | null | undefined> }
  clients: { claim(): Promise<void> }
  skipWaiting(): Promise<void>
  addEventListener(type: string, listener: (event: any) => void): void
}

function preferredLanguages(navigatorLike: WorkerScopeLike['navigator']): readonly string[] {
  if (navigatorLike.languages && navigatorLike.languages.length > 0) return navigatorLike.languages
  return navigatorLike.language ? [navigatorLike.language] : []
}

export async function buildOfflineResponse(scope: WorkerScopeLike): Promise<Response> {
  const preference = await scope.cookieStore?.get(LOCALE_COOKIE).catch(() => undefined)
  const lang = isLocale(preference?.value) ? preference.value : browserLocale(preferredLanguages(scope.navigator))
  const copy = offline[lang]
  const html = `<!doctype html>
<html lang="${lang}">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
  <meta name="theme-color" content="#0e6b5e">
  <title>liam-e · ${copy.title}</title>
  <style>
    :root { color-scheme: light dark; font: 100%/1.5 system-ui; }
    body { margin: 0; min-height: 100svh; min-height: 100dvh; display: grid; place-items: center; }
    main { max-width: 28rem; box-sizing: border-box; padding: max(1.5rem, env(safe-area-inset-top)) max(1.5rem, env(safe-area-inset-right)) max(1.5rem, env(safe-area-inset-bottom)) max(1.5rem, env(safe-area-inset-left)); }
    h1 { font-size: 1.5rem; }
    a { display: inline-flex; align-items: center; min-height: 44px; padding: .7rem 1rem; box-sizing: border-box; border-radius: 2rem; background: #0e6b5e; color: white; text-decoration: none; }
  </style>
</head>
<body>
  <main>
    <h1>${copy.title}</h1>
    <p>${copy.detail}</p>
    <a href="">${copy.retry}</a>
  </main>
</body>
</html>`
  return new Response(html, {
    status: 503,
    headers: { 'Content-Type': 'text/html; charset=utf-8', 'Cache-Control': 'no-store' },
  })
}

export function setupServiceWorker(scope: WorkerScopeLike, fetcher: typeof fetch = fetch): void {
  // This worker holds no CacheStorage state, so immediate activation never breaks cached chunks.
  scope.addEventListener('install', (event: ExtendableEvent) => {
    event.waitUntil(scope.skipWaiting())
  })
  scope.addEventListener('activate', (event: ExtendableEvent) => {
    event.waitUntil(scope.clients.claim())
  })
  scope.addEventListener('fetch', (event: FetchEvent) => {
    const { request } = event
    if (request.method !== 'GET' || request.mode !== 'navigate') return
    const url = new URL(request.url)
    if (url.origin !== scope.location.origin || url.pathname === '/api' || url.pathname.startsWith('/api/')) return
    // Only synthesize an offline document on a network failure. HTTP errors,
    // authentication redirects and all application data go through to the server.
    event.respondWith(fetcher(request).catch(() => buildOfflineResponse(scope)))
  })
}

if (typeof self !== 'undefined' && 'clients' in self && 'skipWaiting' in self) {
  setupServiceWorker(self as unknown as ServiceWorkerGlobalScope)
}

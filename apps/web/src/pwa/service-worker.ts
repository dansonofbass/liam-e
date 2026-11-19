/// <reference lib="webworker" />
import { browserLocale, isLocale, LOCALE_COOKIE } from '../i18n/locales'
import { offline } from '../i18n/offline'

declare const self: ServiceWorkerGlobalScope

async function offlinePage() {
  const preference = await self.cookieStore?.get(LOCALE_COOKIE).catch(() => undefined)
  const lang = isLocale(preference?.value) ? preference.value : browserLocale(self.navigator.languages)
  const copy = offline[lang]
  const html = `<!doctype html>
<html lang="${lang}">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>liam-e · ${copy.title}</title>
  <style>
    :root { color-scheme: light dark; font: 100%/1.5 system-ui; }
    body { margin: 0; min-height: 100svh; display: grid; place-items: center; }
    main { max-width: 28rem; padding: 1.5rem; }
    h1 { font-size: 1.5rem; }
    a { display: inline-block; padding: .7rem 1rem; border-radius: 2rem; background: #0e6b5e; color: white; text-decoration: none; }
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
  return new Response(html, { status: 503, headers: { 'Content-Type': 'text/html; charset=utf-8', 'Cache-Control': 'no-store' } })
}

self.addEventListener('activate', event => event.waitUntil(self.clients.claim()))
self.addEventListener('fetch', event => {
  const { request } = event
  if (request.method !== 'GET' || request.mode !== 'navigate') return
  const url = new URL(request.url)
  if (url.origin !== self.location.origin || url.pathname === '/api' || url.pathname.startsWith('/api/')) return
  // Only synthesize an offline document on a network failure. HTTP errors,
  // authentication redirects and all application data go through to the server.
  event.respondWith(fetch(request).catch(offlinePage))
})

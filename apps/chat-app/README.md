# Mistral Chat-App (minimal)

Minimale Web-App, die die [Mistral API](https://docs.mistral.ai) über das offizielle TypeScript-SDK (`@mistralai/mistralai`) aufruft. Der API-Key bleibt ausschließlich auf dem Server (`MISTRAL_API_KEY` als Umgebungsvariable) und wird nie an den Browser geschickt.

Die [Mail-App liam-e](../../README.md) hat ihren eigenen Einstieg.

## Voraussetzungen

- Node.js >= 20
- Ein Mistral API-Key ([console.mistral.ai](https://console.mistral.ai))

## Installation

Führe `npm ci` in `apps/chat-app` aus.

## Lokale Ausführung

Setze `MISTRAL_API_KEY` in der Umgebung des Servers.

```bash
# Entwicklung (mit automatischem Neustart bei Änderungen)
npm run dev

# Start ohne Watch-Modus
npm start
```

Danach im Browser öffnen: [http://localhost:3000](http://localhost:3000)

## Struktur

- `src/server.ts` – HTTP-Server, serviert die Chat-Seite und leitet Chat-Anfragen an `mistral-small-latest` weiter
- `public/index.html` – einfache Chat-Oberfläche (reines HTML/JS, kein Build-Schritt)

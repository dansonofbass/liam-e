# Mistral Chat-App (minimal)

Minimale Web-App, die die [Mistral API](https://docs.mistral.ai) über das offizielle TypeScript-SDK (`@mistralai/mistralai`) aufruft. Der API-Key bleibt ausschließlich auf dem Server (`MISTRAL_API_KEY` als Umgebungsvariable) und wird nie an den Browser geschickt.

## Voraussetzungen

- Node.js >= 20
- Ein Mistral API-Key ([console.mistral.ai](https://console.mistral.ai))

## Installation

```bash
npm install
cp .env.example .env
# .env editieren und MISTRAL_API_KEY eintragen
```

## Lokale Ausführung

```bash
# Entwicklung (mit automatischem Neustart bei Änderungen)
npm run dev

# oder ohne .env-Datei, Key direkt als Umgebungsvariable:
MISTRAL_API_KEY=... npm start
```

Danach im Browser öffnen: [http://localhost:3000](http://localhost:3000)

## Struktur

- `src/server.ts` – HTTP-Server, serviert die Chat-Seite und leitet Chat-Anfragen an `mistral-small-latest` weiter
- `public/index.html` – einfache Chat-Oberfläche (reines HTML/JS, kein Build-Schritt)
- `.env` – lokaler API-Key (nie committen, siehe `.gitignore`)

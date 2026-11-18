# Mistral chat app (minimal)

A minimal web app that calls the [Mistral API](https://docs.mistral.ai) through the official TypeScript SDK (`@mistralai/mistralai`). The API key stays exclusively on the server (`MISTRAL_API_KEY` as an environment variable) and is never sent to the browser.

The [liam-e mail app](../../README.md) has its own entry point.

## Prerequisites

- Node.js >= 20
- A Mistral API key ([console.mistral.ai](https://console.mistral.ai))

## Installation

Run `npm ci` in `apps/chat-app`.

## Running locally

Set `MISTRAL_API_KEY` in the server environment.

```bash
# Development (automatically restarts on changes)
npm run dev

# Start without watch mode
npm start
```

Then open [http://localhost:3000](http://localhost:3000) in your browser.

## Structure

- `src/server.ts` – HTTP server, serves the chat page and forwards chat requests to `mistral-small-latest`
- `public/index.html` – simple chat UI (plain HTML/JS, no build step)

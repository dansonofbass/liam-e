---
type: architecture
title: "Laufzeit und Deployment"
description: "TanStack Start, FastAPI, dauerhafte Jobs und Postgres teilen sich die Laufzeit der Einzel-Nutzer-App."
tags: [architecture, fastapi, studio]
verified:
  - by: openwiki/0.7.2
    at: 2026-11-17T18:59:26.600Z
sources:
  - id: openwiki-source-17a23f5c64c831875f9e67aa
    resource: repo://apps/api/src/api/lifespan/startup/mail_worker.py
  - id: openwiki-source-4274d74a4ad00e428c3ad5eb
    resource: repo://apps/api/src/api/mail/jobs.py
  - id: openwiki-source-94d24ebf5a6a1dce945f609f
    resource: repo://apps/api/src/api/routers/api/internal/health.py
  - id: openwiki-source-45c3329c0fca0da2878c19f7
    resource: repo://apps/api/src/api/routers/api/v1/__init__.py
  - id: openwiki-source-37186b9bfb98e1af333ad420
    resource: repo://apps/web/.env.example
  - id: openwiki-source-3fbb7dfbcddf16f1593eabc3
    resource: repo://apps/web/src/api/client-config.ts
  - id: openwiki-source-8fd9a59f53f850587ae367a1
    resource: repo://mistral.json
  - id: openwiki-source-b0615e797b9bed2b07743c53
    resource: repo://tools/gen-types.sh
generated: { by: "codex", at: "2026-11-17T18:59:26.600Z" }
---

# Laufzeit und Deployment

## Einstiegspunkte und Zugriff

TanStack Start liefert die deutsche Oberfläche. Der generierte Client schickt API-Pfade standardmäßig an dieselbe Origin. Für den lokalen Start auf getrennten Ports setzt die Anleitung `VITE_API_URL=http://127.0.0.1:3000` und öffnet die Web-App unter `http://localhost:3001`. Dieser Browser-Ursprung ist in den FastAPI-Settings voreingestellt. [Client-Konfiguration](../../apps/web/src/api/client-config.ts), [HTTP-Settings](../../packages/py/env/src/env/api.py), [Lokale Entwicklung](../../docs/lokale-entwicklung.md).

FastAPI baut die Anwendung aus Routerbaum und Lifecycle-Hooks. Der versionierte Router hat keine app-eigene Nutzerverwaltung. In Studio schützt das Gateway die Installation für einen Nutzer. Das Manifest bindet Web unter `/`, API unter `/api` und verwaltetes Postgres. Die Datenbankverbindung entsteht aus injizierten `POSTGRES_*`-Werten, sofern kein explizites `DATABASE_URL` gesetzt ist. Vor dem API-Start im Container läuft der Pre-Start mit Migrationen. [API-Einstieg](../../apps/api/src/api/main.py), [Zugriffsregel](../../apps/api/src/api/routers/api/v1/__init__.py), [Manifest](../../mistral.json), [DB-Settings](../../packages/py/env/src/env/db.py), [Pre-Start](../../packages/py/cli/src/cli/commands/pre_start.py).

## Prozesse und Verträge

Der aktivierte Hintergrund-Worker läuft im API-Prozess. Er nimmt Jobs aus Postgres an und stößt periodische Mailabrufe an. Stoppt der Prozess, wartet die weitere Verarbeitung auf einen laufenden Worker. Die Studio-Probe vom 13.11.2026 beobachtete nach 31 Minuten noch denselben Prozess. Das ist eine Messung der Test-App zu diesem Zeitpunkt. [Start-Hook](../../apps/api/src/api/lifespan/startup/mail_worker.py), [Jobschleife](../../apps/api/src/api/mail/jobs.py), [Studio-Probe](../../docs/superpowers/probes/2026-11-13-studio-proben.md).

[OpenAPI](../../apps/api/openapi.json) ist der Vertrag für den generierten TypeScript-Client. `bun run check` prüft, ob Spezifikation und Client den aktuellen Routen entsprechen. `/api/health` liefert Status und Abhängigkeitszustand auch bei HTTP 200 mit `degraded`. Die separate Readiness-Probe kann HTTP 503 liefern. [Client-Generierung](../../tools/gen-types.sh), [CI](../../.github/workflows/ci.yml), [Health](../../apps/api/src/api/routers/api/internal/health.py).

Studio-HTTP-Connectoren können importierte Operationen als MCP-Werkzeuge anbieten. Für einen Import gilt die lesende Erlaubnisliste. [Agentenregeln](../../AGENTS.md#sicherheit), [Inventurtest](../../apps/api/tests/test_mcp_exposure.py).

Weiter zu [Datenmodell](datenmodell.md), [Mailabruf](../mail/provider-und-sync.md) und [Studio-Deployment](../../docs/provider-und-betrieb.md#deployment-in-mistral-studio).

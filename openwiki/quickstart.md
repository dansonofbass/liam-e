---
type: guide
title: "Einstieg in liam-e"
description: "Einstiegspunkte für lokale Arbeit, Provider, Mail-Assistent, Kalenderindex, Aufgaben und Vorlagen."
tags: [quickstart, development, liam-e]
verified:
  - by: openwiki/0.7.2
    at: 2026-11-17T18:59:26.600Z
sources:
  - id: openwiki-source-a35ad249a5deff557d16c87b
    resource: repo://apps/api/src/api/mail/agent_tools.py
  - id: openwiki-source-d61b88008fe54ad410df669e
    resource: repo://apps/api/src/api/mail/dev_seed.py
  - id: openwiki-source-0ba5a5af644a629ba71f52bc
    resource: repo://apps/api/src/api/mail/proposals.py
  - id: openwiki-source-64c48731b5cb51f3890cde54
    resource: repo://apps/api/tests/test_seed_guard.py
  - id: openwiki-source-77a5035bde15962a522ff0b9
    resource: repo://apps/web/src/prompts/Settings.tsx
  - id: openwiki-source-b77274541336290203382438
    resource: repo://apps/web/src/routes/_app.tsx
  - id: openwiki-source-01835b5a507daf25562afb75
    resource: repo://apps/web/src/routes/_app/settings/index.tsx
  - id: openwiki-source-1ba98567db75ea696cc1ca58
    resource: repo://apps/web/src/routes/_app/settings/prompts/index.tsx
  - id: openwiki-source-b0615e797b9bed2b07743c53
    resource: repo://tools/gen-types.sh
generated: { by: "codex", at: "2026-11-17T18:59:26.600Z" }
---

# Einstieg in liam-e

liam-e ist eine deutsche Mail-App für eine Person pro Installation. Posteingang und Chat arbeiten auf dem Mailindex in Postgres. Der Assistent kann Mails durchsuchen, lesen und zusammenfassen. Für den Versand und Änderungen durch den Assistenten ist eine Bestätigung erforderlich. Die Einstellungen enthalten die Vorlagenbibliothek. Aufgaben sind über die API nutzbar. Beim Kalender steht der Index mit Verwaltung vorhandener Quellen zur Verfügung. Die Quellenanbindung und die Agenda sind noch nicht eingebunden. [README](../README.md), [API-Vertrag](../apps/api/openapi.json).

## Lokal ausprobieren

Die [Anleitung zur lokalen Entwicklung](../docs/lokale-entwicklung.md) führt durch Installation, Datenbank und Migrationen. Für den Seed-Modus verwende eine Testdatenbank auf Loopback und starte die API mit deaktiviertem Worker. Beispielkonten können keine Provideraktionen ausführen. Ein echter Modell-Turn braucht einen serverseitig konfigurierten Mistral-Zugang. [Seed](../apps/api/src/api/mail/dev_seed.py), [Seed-Tests](../apps/api/tests/test_seed_guard.py).

## Einstieg nach Aufgabe

| Wenn du … | Lies … |
| --- | --- |
| Web, API oder Studio starten willst | [Lokale Entwicklung](../docs/lokale-entwicklung.md), [Laufzeit](architektur/laufzeit.md) |
| Daten und Migrationen nachvollziehen willst | [Datenmodell](architektur/datenmodell.md) |
| Konten verbinden oder den Abruf verstehen willst | [Provider und Sync](mail/provider-und-sync.md), [Provider-Matrix und Betrieb](../docs/provider-und-betrieb.md) |
| Streaming, Mailvorschläge oder Versand ändern willst | [Assistent und Bestätigung](mail/chat-und-bestaetigung.md) |
| Quellen, Instanzen und ICS-Verarbeitung einordnen willst | [Kalender](domaenen/kalender.md) |
| Serien, Vorschau oder Fortschritt prüfen willst | [Aufgaben](domaenen/aufgaben.md) |
| Vorlagenrevisionen oder Widerruf verstehen willst | [Vorlagen](domaenen/vorlagen.md) |

Der [OpenAPI-Vertrag](../apps/api/openapi.json) definiert den API-Umfang für den generierten Webclient. Regeln für Beiträge und Sicherheitsmeldungen stehen in [CONTRIBUTING.md](../CONTRIBUTING.md) und [SECURITY.md](../SECURITY.md).

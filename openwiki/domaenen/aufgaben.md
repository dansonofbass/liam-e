---
type: domain
title: "Aufgabenserien und Fälligkeiten"
description: "Die Aufgaben-API verwaltet Einzel- und Serienaufgaben, lokale Fälligkeiten, Revisionen und Instanzzustände."
tags: [tasks, recurrence, postgres]
verified:
  - by: openwiki/0.7.2
    at: 2026-11-17T18:59:26.600Z
sources:
  - id: openwiki-source-d246fbcfbb572bc2be66186b
    resource: repo://apps/api/src/api/routers/api/v1/tasks/route.py
  - id: openwiki-source-cfb0fd9ba6fed48dfe896669
    resource: repo://apps/api/src/api/tasks/lifecycle.py
  - id: openwiki-source-6565a7a4a96b17638ba3cf15
    resource: repo://apps/api/src/api/tasks/patch.py
  - id: openwiki-source-5e0e8492347d2f168a2f2422
    resource: repo://apps/api/src/api/tasks/preview.py
  - id: openwiki-source-f3eb51c35314748cc6f02372
    resource: repo://apps/api/src/api/tasks/reconcile.py
  - id: openwiki-source-ebd4f75c9db71c8e0704fb6f
    resource: repo://apps/api/src/api/tasks/recurrence.py
generated: { by: "codex", at: "2026-11-17T18:59:26.600Z" }
---

# Aufgabenserien und Fälligkeiten

## Verfügbare Funktionen

Die [Aufgaben-API](../../apps/api/openapi.json) legt Einzel- und Serienaufgaben an, erstellt eine Vorschau, liest Serien und Instanzen und bearbeitet ihre Fälligkeit oder ihren Status. Die aktuelle Web-App hat keine Aufgabenroute. Der Mailassistent besitzt keine Aufgabenwerkzeuge. [Webrouten](../../apps/web/src/routes/_app/), [Agentenwerkzeuge](../../apps/api/src/api/mail/agent_tools.py).

Neue Aufgaben brauchen eine IANA-Zeitzone, auch wenn die Fälligkeit nur ein Datum trägt. Eine Erstellungskennung macht den Anlagenaufruf wiederholbar. Die erste Reconcile-Seite wird mit der Serie in derselben Transaktion gespeichert. Die Vorschau verwendet dieselbe Regelauswertung ohne Schreibzugriff. Nicht existente lokale Uhrzeiten zählen bei `COUNT` nicht. [Anlage](../../apps/api/src/api/routers/api/v1/tasks/route.py), [Vorschau](../../apps/api/src/api/tasks/preview.py), [Regelauswertung](../../apps/api/src/api/tasks/recurrence.py).

## Reconcile und Lesen

Reconcile materialisiert Instanzen unter Seriensperre bis zu einem festen Ziel, standardmäßig 30 Tage nach Beginn des Laufs. Jede Seite speichert Cursor und Instanzen gemeinsam. Ein alter expliziter Cursor führt zum Konflikt. Ein neuer Horizont verlangt den exakten Abschlusscursor des vorherigen Laufs. Leseaufrufe verwenden bestehende Instanzen. Die Serienliste bezieht `complete` auf ihr angefragtes Fenster, getrennt vom Zustand der Instanzpagination. [Reconcile](../../apps/api/src/api/tasks/reconcile.py), [Fensterlogik](../../apps/api/src/api/tasks/reading.py).

## Änderungen und Status

Einzelverschiebungen bewahren die ursprüngliche Instanzidentität. „Diese und folgende“ trennt ab einer zulässigen zukünftigen Fälligkeit und legt eine neue Zeitplanrevision an. Vergangene und abgeschlossene Instanzen bleiben erhalten. Die Änderung verlangt die erwarteten Versionen der Serie und der gewählten Instanz. [Zeitplanänderung](../../apps/api/src/api/tasks/patch.py).

Eine Instanz kann erledigt, übersprungen oder wieder geöffnet werden. Bei archivierten Serien sind neue Materialisierung und das Wiederöffnen zukünftiger Instanzen gesperrt. Archivieren storniert offene zukünftige Fälligkeiten. Endgültiges Löschen braucht ausdrücklich `confirm_history_loss: true` und entfernt die Serie samt Revisionen und Instanzen. [Zustände](../../apps/api/src/api/tasks/state.py), [Lebenszyklus](../../apps/api/src/api/tasks/lifecycle.py).

Weiter zum [Datenmodell](../architektur/datenmodell.md) und zu den [API-Tests](../../apps/api/tests/test_tasks_api.py).

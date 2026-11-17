---
type: domain
title: "Kalenderindex und ICS-Kern"
description: "Die Kalender-API liest vorhandene Indexdaten. Der Snapshot-Kern und der isolierte ICS-Adapter liefern die Bausteine für eine spätere Quellenanbindung."
tags: [calendar, ics, snapshots]
verified:
  - by: openwiki/0.7.2
    at: 2026-11-17T18:59:26.600Z
sources:
  - id: openwiki-source-e7dd4952f08cf54e63a4c942
    resource: repo://apps/api/src/api/calendar/adapters.py
  - id: openwiki-source-cfa4af73f108f9dec050192a
    resource: repo://apps/api/src/api/calendar/ics.py
  - id: openwiki-source-8a45b03cfa345cb39a681ba9
    resource: repo://apps/api/src/api/calendar/sync.py
  - id: openwiki-source-17a23f5c64c831875f9e67aa
    resource: repo://apps/api/src/api/lifespan/startup/mail_worker.py
  - id: openwiki-source-2630f0cf082479a0f6d29d0f
    resource: repo://apps/api/src/api/routers/api/v1/calendar/occurrences.py
  - id: openwiki-source-e4668865e2a09b6878e0e206
    resource: repo://apps/api/src/api/routers/api/v1/calendar/sources.py
  - id: openwiki-source-214dcc89eab83d910409879d
    resource: repo://apps/api/tests/test_calendar_routes.py
  - id: openwiki-source-e976f3260df8985d6d856fe9
    resource: repo://packages/py/db/src/db/accessors/calendar_snapshot.py
generated: { by: "codex", at: "2026-11-17T18:59:26.600Z" }
---

# Kalenderindex und ICS-Kern

## Was der Dienst bereitstellt

Die [Kalender-API](../../apps/api/openapi.json) listet vorhandene Quellen, schaltet sie aktiv oder inaktiv, entfernt sie und nimmt manuelle Abrufaufträge an. Die Instanzliste greift auf den lokalen Index aktiver Quellen zu. Das UTC-Datumsfenster umfasst höchstens 90 Tage, die Filterliste bis zu 50 Quellen. Der Seiten-Cursor kombiniert Zeit und ID. Ganztägige Termine haben ein exklusives Enddatum. Ein Termin ohne Dauer gehört zum Fenster, wenn sein Zeitpunkt am Beginn oder innerhalb liegt. [Quellen](../../apps/api/src/api/routers/api/v1/calendar/sources.py), [Instanzen](../../apps/api/src/api/routers/api/v1/calendar/occurrences.py), [Intervallregeln](../../apps/api/src/api/calendar/adapters.py).

Der API-Start registriert den Job-Handler. Der Handler verlangt einen registrierten Anbieteradapter. Der Checkout verbindet den ICS-Adapter noch nicht mit dem Handler. Planbare Quellenanlage, Agenda, periodischer Kalenderabruf und Kalenderwerkzeuge des Mailassistenten stehen aus. Ein angenommenes Job-Enqueue allein belegt keinen erfolgreichen Anbieterabruf. [Startup](../../apps/api/src/api/lifespan/startup/mail_worker.py), [Kalender-Sync](../../apps/api/src/api/calendar/sync.py), [Webrouten](../../apps/web/src/routes/_app/).

## Snapshot und Verarbeitung

Der Adapter liefert einen vollständigen Snapshot des Zielfensters. Der Dienst validiert Instanzen und Identitäten vor dem Schreiben. Der Accessor prüft Besitz des Jobs und den aktiven Status der Quelle. Berührende oder überlappende vollständige Fenster ergeben eine gemeinsame Abdeckung. Ein disjunktes Fenster ersetzt die bisherige. Die Quellenantwort meldet `stale`, wenn ein erfolgreicher Snapshot fehlt oder die Abdeckung als unvollständig geführt wird. [Snapshot-Speicherung](../../packages/py/db/src/db/accessors/calendar_snapshot.py), [Quellenstatus](../../apps/api/src/api/routers/api/v1/calendar/sources.py).

Der ICS-Kern holt begrenzte HTTPS-Feeds und wertet sie in einem separaten Prozess aus. Der Parser berücksichtigt Zeitzonen, Wiederholungen und einzelne Termin-Ausnahmen. Er behält normalisierte Ereignisse für eine erneute Expansion. Ein HTTP 304 setzt diese Daten voraus und expandiert sie für das neue Fenster. Der Prozess wird beim Timeout oder Abbruch beendet und aufgeräumt. [Abruf](../../apps/api/src/api/calendar/ics_fetch.py), [Adapter](../../apps/api/src/api/calendar/ics.py), [ICS-Tests](../../apps/api/tests/test_calendar_ics_parse.py).

Weiter zum [Datenmodell](../architektur/datenmodell.md) und zum [Kalendervertrag](../../apps/api/tests/test_calendar_routes.py).

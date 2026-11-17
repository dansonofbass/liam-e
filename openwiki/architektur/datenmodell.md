---
type: architecture
title: "Datenmodell und Persistenz"
description: "Postgres speichert den Mailindex, die Warteschlange, Chat-Kontexte und die Indizes für Kalender und Aufgaben."
tags: [postgres, persistence, migrations]
verified:
  - by: openwiki/0.7.2
    at: 2026-11-17T18:59:26.600Z
sources:
  - id: openwiki-source-f3eb51c35314748cc6f02372
    resource: repo://apps/api/src/api/tasks/reconcile.py
  - id: openwiki-source-e976f3260df8985d6d856fe9
    resource: repo://packages/py/db/src/db/accessors/calendar_snapshot.py
  - id: openwiki-source-0037095c7f4178076b9720a1
    resource: repo://packages/py/db/src/db/accessors/chat_context.py
  - id: openwiki-source-935a2178d31500729ef9ae89
    resource: repo://packages/py/db/src/db/models/chat_context.py
  - id: openwiki-source-46279e90fc7d93dd507baf8c
    resource: repo://packages/py/db/src/db/models/mail_job.py
  - id: openwiki-source-cc5f32a41db1605e19a62759
    resource: repo://packages/py/db/src/db/models/mail_message.py
  - id: openwiki-source-406f0edff776dee55e0dc686
    resource: repo://packages/py/db/src/db/models/task_occurrence.py
  - id: openwiki-source-b86f8ff3be3f88fe6c84de93
    resource: repo://tools/db.sh
generated: { by: "codex", at: "2026-11-17T18:59:26.600Z" }
---

# Datenmodell und Persistenz

## Schema und Schlüssel

| Daten | Tabellen und Zuständigkeit |
| --- | --- |
| Konten und Abruf | `mail_account`, `mail_credential`, `mail_sync_state`, `mail_job` trennen Konto, verschlüsselte Zugangsdaten, Fortschritt und ausstehende Arbeit. Offene Jobs teilen sich einen eindeutigen Deduplizierungsschlüssel. [Jobmodell](../../packages/py/db/src/db/models/mail_job.py) |
| Mailindex | `mail_message` identifiziert eine Nachricht durch Konto, Ordner und Provider-ID. Postgres indiziert Betreff, Absender und Text für die Volltextsuche. `mail_insight` enthält Kurzfassungen, `mail_action` den Zustand für „Rückgängig“. [Mailmodell](../../packages/py/db/src/db/models/mail_message.py) |
| Unterhaltung und Vorlagen | `chat_conversation` verwaltet die Unterhaltung, `chat_message` Verlauf und Vorschläge. `chat_context` hält Kontoumfang und Vorlagenbezug pro Turn fest. `prompt_template` hält die aktuelle Auswahl für die Bibliothek, `prompt_revision` nummeriert die Fassungen je Vorlage. [Chatkontext](../../packages/py/db/src/db/models/chat_context.py), [Vorlagenrevision](../../packages/py/db/src/db/models/prompt_revision.py) |
| Kalender | `calendar_source`, `calendar_event`, `calendar_occurrence` und `calendar_sync_state` halten Quelle, Ereignis, Instanz und Abdeckung. Die externe Instanz-ID gilt eindeutig je Quelle. [Kalendermodell](../../packages/py/db/src/db/models/calendar_occurrence.py) |
| Aufgaben | `task_series`, `task_schedule_revision` und `task_occurrence` trennen Aufgabe, Zeitplan und Fälligkeit. Die ursprüngliche Fälligkeit ist innerhalb ihrer Revision ein eindeutiger Schlüssel. [Fälligkeitsmodell](../../packages/py/db/src/db/models/task_occurrence.py) |

## Änderungen und Migrationen

SQLModel-Modelle beschreiben das Schema. [Accessors](../../packages/py/db/src/db/accessors/) halten die Abfragen und zustandsabhängigen Änderungen. Der Kalender schreibt Instanzen und Abdeckung gemeinsam und prüft dabei, ob der Worker den Job noch besitzt. Aufgaben speichern neu materialisierte Instanzen und den zugehörigen Fortschritt in der Transaktion des Aufrufers. Beim Löschen einer Vorlage werden ihre Revisionen und abhängigen Chat-Kontexte gemeinsam geändert. [Kalender-Snapshot](../../packages/py/db/src/db/accessors/calendar_snapshot.py), [Reconcile](../../apps/api/src/api/tasks/reconcile.py), [Vorlagen](../../packages/py/db/src/db/accessors/prompt_template.py).

Alembic verwaltet das Schema. `bunx nx run db:migrate` wendet mit `alembic upgrade heads` alle Zweige an. Die CI prüft Datenbankverträge mit einem temporären Postgres-Dienst. [Skript](../../tools/db.sh), [Workflow](../../.github/workflows/ci.yml).

Weiter zu [Laufzeit](laufzeit.md), [Kalender](../domaenen/kalender.md) oder [Aufgaben](../domaenen/aufgaben.md).

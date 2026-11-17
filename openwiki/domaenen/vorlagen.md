---
type: domain
title: "Vorlagen und Turn-Kontext"
description: "Prompt-Vorlagen verbinden die Bibliothek im Web mit revisionsgebundener Auswahl und widerrufbaren Chat-Kontexten."
tags: [prompts, chat, revisions]
verified:
  - by: openwiki/0.7.2
    at: 2026-11-17T18:59:26.600Z
sources:
  - id: openwiki-source-345f16e64e633e32b0de44e2
    resource: repo://apps/api/src/api/mail/agent.py
  - id: openwiki-source-250c5dc8c674d71e86dda78f
    resource: repo://apps/api/tests/test_chat_proposals.py
  - id: openwiki-source-0037095c7f4178076b9720a1
    resource: repo://packages/py/db/src/db/accessors/chat_context.py
  - id: openwiki-source-536c8703cc32651efea06860
    resource: repo://packages/py/db/src/db/accessors/chat_message.py
  - id: openwiki-source-b1e70c8361d8a5a4cddd7c85
    resource: repo://packages/py/db/src/db/accessors/prompt_template.py
generated: { by: "codex", at: "2026-11-17T18:59:26.600Z" }
---

# Vorlagen und Turn-Kontext

## Bibliothek und Auswahl

Die Einstellungen bieten eine Bibliothek zum Anlegen, Bearbeiten und Löschen von Vorlagen. Anlage und Bearbeitung öffnen eigene Ansichten. Eine geänderte Vorlage bekommt eine neue Revision. Eine Unterhaltung behält ihre ausgewählte Fassung, bis ihre Auswahl ausdrücklich geändert wird. Die API prüft die erwartete Version bei Bearbeitung und Löschung der Vorlage sowie beim Ändern der Unterhaltung. Standard in der Unterhaltung ist `prompt_revision_id: null`. [Bibliothek](../../apps/web/src/prompts/Library.tsx), [Auswahl](../../apps/web/src/prompts/TemplateMenu.tsx), [Vorlagenrouten](../../apps/api/src/api/routers/api/v1/prompts/route.py), [Unterhaltungsroute](../../apps/api/src/api/routers/api/v1/chat/conversations.py).

## Auflösung pro Turn

Der Server legt für einen Turn die App-Prompt-Version, Vorlagenrevision und Hash sowie die tatsächlich aufgelösten Konto-IDs ab. Vorlagentext geht als Nutzerinhalt ans Modell. Die App-Regeln bleiben Teil des Systemprompts. Eine bestehende Unterhaltung kann nicht zu einem anderen Konto auf denselben Verlauf wechseln. „Alle Konten“ bleibt als Auswahl stabil, wenn sich die vorhandenen Konten ändern. Altverläufe ohne nachgewiesenen Umfang werden als gemischt behandelt. [Kontextauflösung](../../packages/py/db/src/db/accessors/chat_context.py), [Modellaufruf](../../apps/api/src/api/mail/agent.py).

## Löschen und Widerruf

Das Löschen entfernt Vorlagen- und Revisionsinhalte, markiert die Revisionen als entfernt, setzt betroffene Unterhaltungen auf Standard und widerruft alte Kontexte. Der Agent prüft einen Widerruf vor Modellaufrufen, vor Werkzeugen und in Abständen während des Streams. Ein offener Vorschlag mit widerrufenem Kontext kann abgebrochen werden. Für Bestätigungen entscheidet der Zustand beim atomaren Übergang zu `running`. [Vorlagen-Accessor](../../packages/py/db/src/db/accessors/prompt_template.py), [Vorschlagssperre](../../packages/py/db/src/db/accessors/chat_message.py), [Kontexttests](../../apps/api/tests/test_prompt_context.py).

Weiter zum [Bestätigungsfluss](../mail/chat-und-bestaetigung.md) oder zum [Datenmodell](../architektur/datenmodell.md).

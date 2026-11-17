---
type: workflow
title: "Mail-Assistent und explizite Bestätigung"
description: "Ein Chat-Turn arbeitet auf dem Mailindex. Ein eigener Bestätigungsaufruf führt einen gespeicherten Vorschlag aus."
tags: [mail, chat, confirmation, sse]
verified:
  - by: openwiki/0.7.2
    at: 2026-11-17T18:59:26.600Z
sources:
  - id: openwiki-source-541ff2af139aeed4c55a950c
    resource: repo://apps/api/src/api/mail/actions.py
  - id: openwiki-source-a35ad249a5deff557d16c87b
    resource: repo://apps/api/src/api/mail/agent_tools.py
  - id: openwiki-source-0ba5a5af644a629ba71f52bc
    resource: repo://apps/api/src/api/mail/proposals.py
  - id: openwiki-source-984acc7fd7cc46aa1379686d
    resource: repo://apps/api/src/api/routers/api/v1/chat/stream.py
  - id: openwiki-source-4d650c0310b01fa94c7bac10
    resource: repo://apps/api/src/api/routers/api/v1/mail/messages.py
  - id: openwiki-source-250c5dc8c674d71e86dda78f
    resource: repo://apps/api/tests/test_chat_proposals.py
  - id: openwiki-source-536c8703cc32651efea06860
    resource: repo://packages/py/db/src/db/accessors/chat_message.py
generated: { by: "codex", at: "2026-11-17T18:59:26.600Z" }
---

# Mail-Assistent und explizite Bestätigung

## Chat-Turn

Das Web sendet Text, Kontoauswahl und optional einen Mailbezug. Beim Start einer Unterhaltung kann der Nutzer ein Modell und eine Vorlagenrevision wählen. Der Server löst den Kontext vor dem Turn auf. Der Streaming-Endpunkt liefert benannte SSE-Ereignisse für Beginn, Status, Text, Karten und Abschluss. Er sendet bei Wartezeit Ping-Frames und schließt den Generator bei einem Verbindungsabbruch. Der Agent speichert den sichtbaren Verlauf und die Ergebnisse seiner Werkzeugaufrufe. [Stream](../../apps/api/src/api/routers/api/v1/chat/stream.py), [Agent](../../apps/api/src/api/mail/agent.py).

Werkzeuge suchen im Index des Posteingangs und prüfen Mail- und Konto-IDs gegen den Kontoumfang des Turns. Mailinhalte kommen als fremde Daten in Werkzeugantworten. Die Werkzeugliste erlaubt Lesen, Kurzfassungen, Newsletter-Erkennung und das Anlegen von Vorschlägen. [Werkzeuge](../../apps/api/src/api/mail/agent_tools.py), [Werkzeugtests](../../apps/api/tests/test_chat_agent.py).

## Bestätigung und Ausführung

`create_draft` legt einen Entwurf für neue Mail, Antwort, Antwort an alle oder Weiterleitung ab. `propose_action` erzeugt eine Karte für Archiv, Papierkorb, Gelesen-Markierung oder Newsletter-Abbestellung. Ein neuer Vorschlag verwirft den vorherigen offenen Vorschlag derselben Unterhaltung. Die Karte sendet die ausgewählten IDs und bei bearbeitetem Versandentwurf den Text. [Vorschlagsdienst](../../apps/api/src/api/mail/proposals.py), [Karte](../../apps/web/src/chat/ProposalCard.tsx).

Die API validiert die Auswahl und beansprucht einen offenen Vorschlag atomar, solange der zugehörige Kontext gültig ist. Die Ausführung meldet je Eintrag Erfolg, Fehler oder einen manuellen Schritt. Ein erneuter Bestätigungsaufruf führt denselben Vorschlag kein zweites Mal aus. [Vorschlagsrouten](../../apps/api/src/api/routers/api/v1/chat/proposals.py), [Datenbank-Claim](../../packages/py/db/src/db/accessors/chat_message.py), [Bestätigungstests](../../apps/api/tests/test_chat_proposals.py).

Bei Einzelaktionen aus dem Posteingang löst der Nutzer die Änderung direkt aus. Die Mail-API gibt eine Aktions-ID für „Rückgängig“ zurück. Die Aktion kann nur rückgängig gemacht werden, solange der dafür erforderliche Folgezustand besteht. [Mail-Aktionsroute](../../apps/api/src/api/routers/api/v1/mail/messages.py), [Undo](../../apps/api/src/api/mail/actions.py).

Weiter zu [Vorlagen und Widerruf](../domaenen/vorlagen.md) und [Provider und Mailabruf](provider-und-sync.md).

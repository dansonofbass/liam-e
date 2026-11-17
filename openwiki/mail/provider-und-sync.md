---
type: integration
title: "Provider, Zugangsdaten und Mailabruf"
description: "Verbindungswahl, Provider-Cursor, Ablage von Zugangsdaten und dauerhafter Mailabruf."
tags: [mail, providers, sync, credentials]
verified:
  - by: openwiki/0.7.2
    at: 2026-11-17T18:59:26.600Z
sources:
  - id: openwiki-source-4274d74a4ad00e428c3ad5eb
    resource: repo://apps/api/src/api/mail/jobs.py
  - id: openwiki-source-47b0510892f550bee9e4a38c
    resource: repo://apps/api/src/api/mail/original.py
  - id: openwiki-source-8b314b0b263b8a98784b1887
    resource: repo://apps/api/src/api/mail/service.py
  - id: openwiki-source-3c43214ccc4ed561e0e13395
    resource: repo://apps/api/src/api/mail/sync.py
  - id: openwiki-source-1c959c42592738579f110589
    resource: repo://apps/api/src/api/routers/api/v1/mail/accounts.py
  - id: openwiki-source-3b09b0b54c0548f2dd26db5f
    resource: repo://apps/web/src/accounts/ConnectPanel.tsx
  - id: openwiki-source-afb363923392e4e010c70124
    resource: repo://docs/superpowers/probes/2026-11-13-studio-proben.md
  - id: openwiki-source-46279e90fc7d93dd507baf8c
    resource: repo://packages/py/db/src/db/models/mail_job.py
generated: { by: "codex", at: "2026-11-17T18:59:26.600Z" }
---

# Provider, Zugangsdaten und Mailabruf

## Verbindung und Nachweis

Gmail und Outlook erscheinen im Verbindungsformular, wenn die App einen passenden Connector oder ein konfiguriertes OAuth-Verfahren meldet. Ein gelisteter Connector hat im Formular Vorrang. Die Connector-Implementierung verwendet für Abruf und Aktionen Gmail-Werkzeugformate. Die Studio-Leseprobe vom 13.11.2026 zeigt Gmail-Formate und dokumentierte Werkzeuge. Die Outlook-Werkzeugliste lieferte damals HTTP 401. Die [Matrix im Betriebshandbuch](../../docs/provider-und-betrieb.md) hält die Grenzen je Anbieter fest. [Optionen](../../apps/api/src/api/routers/api/v1/mail/accounts.py), [Formular](../../apps/web/src/accounts/ConnectPanel.tsx), [Studio-Proben](../../docs/superpowers/probes/2026-11-13-studio-proben.md).

Für iCloud, Yahoo und weitere IMAP-Anbieter speichert der IMAP-Pfad mit dem Konto die freigegebenen Serverdaten und bevorzugt im Formular eine Workspace-Secret-Referenz. Die API akzeptiert alternativ ein App-Passwort. Fernet verschlüsselt Credential-Payloads und erneuerte OAuth-Tokens. Der Connector nutzt den eigenen Zugang der App zu Studio. Das Original einer Mail kann für direkt angebundene OAuth- und IMAP-Konten nachgeladen werden. Für Connector- und Seed-Konten fehlt die Originalansicht. [Credential-Service](../../apps/api/src/api/mail/service.py), [Originalansicht](../../apps/api/src/api/mail/original.py).

## Vom Job zum Index

Manuelle oder periodische Abrufe reihen deduplizierte Kontojobs ein. Der Worker verarbeitet sie im API-Prozess. Automatische Abrufe überspringen Konten mit abgelaufener Anmeldung. Der Abruf konzentriert sich auf den Posteingang. Gmail OAuth verwendet Gmail History, Outlook OAuth einen Graph-Delta-Link, IMAP UID und UIDVALIDITY. Gmail-Connectoren nutzen Thread-Suche und Zeitmarken. Der Worker speichert normalisierte Textfassungen, Metadaten und Cursor in Postgres. [Worker](../../apps/api/src/api/mail/jobs.py), [Sync-Dienst](../../apps/api/src/api/mail/sync.py), [Gmail OAuth](../../apps/api/src/api/mail/sync_gmail.py), [Graph](../../apps/api/src/api/mail/sync_graph.py), [IMAP](../../apps/api/src/api/mail/sync_imap.py), [Connector](../../apps/api/src/api/mail/sync_connector.py).

Neue Nachrichten stoßen das Auffüllen fehlender Kurzfassungen an. Nach einer Änderung der Textextraktion liest der Sync alte Textversionen in kleinen Chargen nach. Scheitert das Nachlesen, pausieren weitere Versuche für die betroffene Zeile. Ändert sich die gespeicherte Textfassung, verliert die alte Kurzfassung ihre Gültigkeit. [Nachlesen und Invalidierung](../../apps/api/src/api/mail/sync.py), [Sync-Tests](../../apps/api/tests/test_mail_sync.py).

Weiter zu [Laufzeit](../architektur/laufzeit.md), [Datenmodell](../architektur/datenmodell.md) und [Bestätigung](chat-und-bestaetigung.md).

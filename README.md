# liam-e

liam-e bündelt mehrere Mailkonten in einem Posteingang. Ein KI-Assistent durchsucht den
Mailindex, fasst Nachrichten zusammen und entwirft Antworten. Du prüfst seine Vorschläge
im Chat und entscheidest, welche ausgeführt werden. Die App hat eine deutsche Oberfläche
und ist für eine Person pro Installation ausgelegt.

## Was du nutzen kannst

| Bereich | Aktueller Stand |
| --- | --- |
| **Posteingang und Konten** | Mails im Posteingang suchen, filtern, lesen und bearbeiten. Kurzfassungen und erkannte Fristen erscheinen an der Mail. Verbindungswege und Aktionen hängen vom Anbieter ab. [Provider-Matrix](docs/provider-und-betrieb.md) |
| **Chat** | Ein Konto oder alle Konten durchsuchen, eine Mail als Bezug mitgeben, das Modell wählen und Antworten im Stream lesen. Senden, Antworten, Weiterleiten und Änderungen durch den Assistenten brauchen eine explizite Bestätigung. Eigene Einzelaktionen im Posteingang wirken direkt. [Chat und Bestätigungsfluss](docs/architektur.md#vom-mailabruf-bis-zur-bestätigung) |
| **Vorlagen** | Eigene Anweisungen in den Einstellungen verwalten und im Chat auswählen. Eine Unterhaltung kann an einer bestimmten Vorlagenrevision bleiben. [Vorlagen](docs/architektur.md) |
| **Aufgaben** | Die API unterstützt Einzel- und Serienaufgaben, Fälligkeiten, Vorschau und Statuswechsel. Eine Aufgabenansicht und Chat-Werkzeuge für Aufgaben sind noch nicht angebunden. [API-Vertrag](apps/api/openapi.json) |
| **Kalender** | Die API liest den Kalenderindex und verwaltet vorhandene Quellen. Die Agenda und das Anbinden neuer Quellen fehlen. Ein ICS-Adapter ist implementiert und getestet, aber noch nicht im laufenden Dienst registriert. [Kalenderkern](docs/architektur.md) |

Für Gmail und Outlook gibt es Pfade über Studio-Connectoren und eigenes OAuth2. iCloud,
Yahoo und weitere Anbieter lassen sich über IMAP/SMTP anbinden, wenn der Anbieter
App-Passwörter und die nötigen Mailprotokolle unterstützt. Der
[Provider- und Betriebsleitfaden](docs/provider-und-betrieb.md) zeigt, welche Fähigkeiten
lokal belegt sind und wofür ein Studio-Nachweis aussteht. Für den Modellchat brauchst du
einen serverseitig konfigurierten Mistral-Zugang.

## Lokal starten

Die Referenzumgebung nutzt Bun 1.4.0, Node.js 24, uv, Python 3.14 und Postgres mit pgvector.
Installiere die Abhängigkeiten vom Repository-Root mit `bun run install-all` und folge der
Anleitung zur [lokalen Entwicklung](docs/lokale-entwicklung.md) für Konfiguration und
Migrationen. Mit dem synthetischen Seed siehst du die Oberfläche ohne Anbieter-Zugänge
oder echte Mails.

Nach der Einrichtung startest du API und Web in zwei Terminals aus dem Repository-Root.

```bash
MAIL_WORKER_ENABLED=false MISTRAL_SECRETS_ENABLED=false TELEMETRY_ENABLED=false bunx nx run api:serve
VITE_API_URL=http://127.0.0.1:3000 bun run dev:web
```

Die Oberfläche läuft unter [localhost:3001](http://localhost:3001). Den
[Healthcheck](http://127.0.0.1:3000/api/health) erreichst du direkt an der API.

## Weiterführende Dokumentation

- [Architektur und Domänen](docs/architektur.md)
- [Provider, Synchronisierung und Studio-Deployment](docs/provider-und-betrieb.md)
- [Lokale Entwicklung und Prüfungen](docs/lokale-entwicklung.md)
- [OpenWiki](openwiki/quickstart.md)
- [Mitarbeit](CONTRIBUTING.md) und [Sicherheitsmeldungen](SECURITY.md)

Die [minimale Mistral-Chat-App](apps/chat-app/README.md) ist eine separate Teilanwendung.
Die Mail-App nutzt [`apps/web`](apps/web/) und [`apps/api`](apps/api/).

## Lizenz

Für liam-e liegt keine projektweite Lizenzdatei vor. Die Lizenzentscheidung liegt beim
Owner. Übernommene Komponenten können eigene Lizenzbedingungen haben. Den Stand zur
geplanten Veröffentlichung hält die [Veröffentlichungscheckliste](docs/veroeffentlichung.md) fest.

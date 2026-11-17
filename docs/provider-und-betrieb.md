# Mailanbieter und Betrieb

## Verbindungswege

Die Kontenansicht bietet Gmail und Outlook an, sobald der passende Studio-Connector gelistet
oder die eigene OAuth-Anmeldung eingerichtet ist. Ein gelisteter Connector hat im Formular
Vorrang. Die Liste zeigt seine Existenz an. Anmeldung und Werkzeugumfang hängen von der
Verbindung in Studio ab. iCloud, Yahoo und weitere IMAP-Anbieter erreichst du über „Anderer
Anbieter“. [Kontenformular](../apps/web/src/accounts/ConnectPanel.tsx),
[API für Konten](../apps/api/src/api/routers/api/v1/mail/accounts.py).

| Anbieter und Zugang | Durch Code und isolierte Tests belegt | Nachweis in Studio oder beim Anbieter |
| --- | --- | --- |
| Gmail über Studio (`gmail`, `google_mail`) | Abruf über Suche und vollständigen Verlauf. Lese- und Ordneraktionen über Labels. Versand über `send_email`, Antworten mit `replyToMessageId`. Originalansicht fehlt. Ohne Reply-To geht die Antwort an den Absender. `CATEGORY_PROMOTIONS` kann einen Newsletter kennzeichnen. | Die Leseprobe vom 13.11.2026 belegt das Antwortformat, die dokumentierten System-Labels und den Parameter `replyToMessageId`. Erfolgreicher Versand und Änderungen wie Papierkorb oder Spam brauchen einen separaten Live-Nachweis. |
| Gmail über eigenes Google-OAuth2 | Inkrementeller Abruf über Gmail History, Lese- und Ordneraktionen über Labels bzw. Gmail-Papierkorb, Versand über Gmail API und lesende Originalansicht. | Registrierter OAuth-Client mit passender Callback-URL und freigegebenen Scopes. Anmeldung, Token-Erneuerung und Mailaktionen im vorgesehenen Konto prüfen. |
| Outlook über eigenes Microsoft-OAuth2 | Microsoft Graph Delta für den Posteingang, Lese- und Ordneraktionen über Graph, Versand über Graph einschließlich Antwort- oder Weiterleitungsentwurf beim Anbieter, lesende Originalansicht. | Registrierter OAuth-Client mit passender Callback-URL. Anmeldung, Einwilligung und Mailaktionen hängen vom Konto und dessen Tenant-Regeln ab. |
| Outlook über Studio (`outlook`) | Auflistung und Registrierung sind implementiert. Abruf, Versand und Labels verwenden den gemeinsamen Connector-Pfad mit dem für Gmail belegten Werkzeugformat. | Die Werkzeugliste antwortete am 13.11.2026 mit HTTP 401. Authentifizierung und kompatibler Werkzeugumfang für diesen Weg sind damit offen. |
| iCloud und Yahoo über IMAP/SMTP | Host-Voreinstellungen und gemeinsamer IMAP/SMTP-Pfad. Abruf über IMAP-UIDs, Lese- und Ordneraktionen über IMAP, Versand über SMTP und lesende Originalansicht. | App-Passwort und Freigaben des jeweiligen Kontos prüfen. Die Tests verwenden einen IMAP-Fake und simulieren den TLS-/SMTP-Transport. |
| Andere IMAP/SMTP-Anbieter | Derselbe IMAP/SMTP-Pfad mit eigenen freigegebenen Hosts. Abweichende Ports und SMTP-STARTTLS sind über die API konfigurierbar. Ordneraktionen hängen von den erkennbaren Systemordnern und Serverfähigkeiten ab. | Host-Freigabe, öffentliche DNS-Auflösung, TLS, Login und Ordnerverhalten beim jeweiligen Anbieter prüfen. |

Die [Provider-Registry](../apps/api/src/api/mail/providers.py) definiert die OAuth-Scopes und
Host-Voreinstellungen. Die gemeinsamen Pfade für
[Mailaktionen](../apps/api/src/api/mail/action_backends.py),
[Versand](../apps/api/src/api/mail/send.py) und
[Originalansicht](../apps/api/src/api/mail/original.py) sind mit
[Sync-Tests](../apps/api/tests/test_mail_sync.py),
[Aktionstests](../apps/api/tests/test_mail_action_backends.py),
[Versandtests](../apps/api/tests/test_mail_send_replies.py) und
[Tests zur Originalansicht](../apps/api/tests/test_mail_original.py) belegt.
Die [Studio-Proben vom 13.11.2026](superpowers/probes/2026-11-13-studio-proben.md) dokumentieren
einzelne Messungen in einer Test-App. Sie gelten für den damaligen Stand.

Die Abrufadapter holen den Posteingang. Die Einstellung `MAIL_SYNC_FOLDERS` erweitert
ihren Abrufumfang derzeit nicht. Die Weboberfläche listet den Posteingang. Die Listen-API
kann zusätzlich Archiv und Papierkorb aus dem lokalen Index abfragen. Spam ist eine
Mailaktion und ein gespeicherter Zustand ohne eigenen Listenfilter. Für Aktionen direkt
beim Anbieter ist der Abgleich je nach Adapter begrenzt. Beim Gmail-Connector fehlen
die Abbestell-Kopfzeilen.
Automatisches Abbestellen benötigt die One-Click-Kopfzeilen oder einen unterstützten
`mailto:`-Link und eine bestätigte Vorschlagskarte.
[Listen-API](../apps/api/src/api/routers/api/v1/mail/messages.py),
[Connector-Abruf](../apps/api/src/api/mail/sync_connector.py),
[Newsletter](../apps/api/src/api/mail/newsletters.py).

## Zugangsdaten und Konfiguration

- **Studio-Connector.** Melde das Mailkonto unter „Auth“ am Connector in Studio an. Das API-Modul
  ruft die Werkzeuge mit seinem eigenen Mistral-Zugang auf, regulär über `MISTRAL_API_KEY`.
  Das Konto erhält lokal keinen Eintrag in `mail_credential`. Ein abgelaufener Connector-Zugang
  wird in Studio erneuert. [Connector-Client](../apps/api/src/api/mail/connectors.py),
  [Mistral-Zugang](../packages/py/utils/src/utils/mistral.py).
- **Eigenes OAuth2.** Hinterlege die Client-ID und das Client-Secret als
  `MAIL_OAUTH_GOOGLE_CLIENT_ID` und `MAIL_OAUTH_GOOGLE_CLIENT_SECRET` oder als die
  entsprechenden `MAIL_OAUTH_MICROSOFT_*`-Variablen. Setze
  `MAIL_OAUTH_REDIRECT_BASE_URL` auf die Basis-URL der App. Registriere beim Anbieter die
  Callback-URL nach dem Muster `<App-Basis-URL>/api/v1/mail/accounts/oauth/<provider>/callback`
  mit `google` bzw. `microsoft`. liam-e verschlüsselt OAuth-Tokens und speichert auch
  erneuerte Tokens verschlüsselt. [OAuth-Routen](../apps/api/src/api/routers/api/v1/mail/accounts.py),
  [Credential-Service](../apps/api/src/api/mail/service.py).
- **IMAP/SMTP.** Lege pro Konto ein Workspace-Secret mit dem App-Passwort an, zum Beispiel
  `yahoo-app-password`. Im Formular steht der Secret-Name. liam-e speichert ihn zusammen mit
  der Serverkonfiguration verschlüsselt und liest das Passwort bei Bedarf. Ein neuer Wert
  unter demselben Namen wirkt beim nächsten Zugriff. Die API akzeptiert alternativ
  `password` als verschlüsselt gespeichertes App-Passwort. Eigene Servernamen kommen
  kommagetrennt in die Laufzeitvariable `MAIL_IMAP_ALLOWED_HOSTS`. Die Anwendung prüft den
  Host gegen die Freigabeliste und auf öffentliche DNS-Adressen. Der Transport prüft die
  TLS-Zertifikate. [Secret-Auflösung](../apps/api/src/api/mail/secrets.py),
  [Mailtransport](../apps/api/src/api/mail/transport.py).
- **Fernet-Schlüssel.** `MAIL_TOKEN_ENCRYPTION_KEY` schützt die Credential-Payloads und wird
  für die Signatur des OAuth-States verwendet. Halte denselben Schlüssel bei Updates
  verfügbar. Ein Wechsel macht die bereits damit verschlüsselten Daten unlesbar.
  [Fernet-Verwendung](../apps/api/src/api/mail/crypto.py),
  [OAuth-State](../apps/api/src/api/mail/providers.py).

Für die in den Settings mit `WorkspaceSecret` markierten Felder kann die API beim Start
Workspace-Secrets laden. Setze dazu im API-Modul `MISTRAL_SECRETS_ENABLED=true` und
`MISTRAL_API_KEY` aus demselben Workspace mit Zugriff auf Secret-Werte. Die Workspace-Secrets
heißen dort zum Beispiel `mail_token_encryption_key` und `mail_oauth_google_client_secret`.
Nichtleere Laufzeitwerte und die lokale `.env` haben Vorrang. `MAIL_IMAP_ALLOWED_HOSTS` und
`MAIL_OAUTH_REDIRECT_BASE_URL` sind gewöhnliche Laufzeitvariablen. Die Passwort-Referenz eines
IMAP-Kontos wird über einen eigenen Abrufpfad zur Laufzeit aufgelöst.
[Mail-Settings](../packages/py/env/src/env/mail.py),
[Konfigurationsreihenfolge](../packages/py/env/src/env/_base.py),
[Workspace-Secrets](../packages/py/env/src/env/_mistral_secrets.py).

## Abruf und Datenhaltung

Ein manueller Abruf stellt einen Job in Postgres ein. Die Antwort `202` bedeutet, dass der
Auftrag angenommen wurde. Offene Jobs für dasselbe Konto werden zusammengefasst. Der Worker
läuft im API-Prozess. Standardmäßig wartet er bei leerer Warteschlange zwei Sekunden und
stellt alle fünf Minuten fällige Abrufe aktiver Konten ein. Der periodische Abruf überspringt
Konten, deren letzter Abruf weniger als ein halbes Intervall zurückliegt, sowie Konten mit
`auth_expired`. Ein manueller Abruf oder eine erneute OAuth-Anmeldung kann sie wieder
einreihen. `MAIL_SYNC_INTERVAL_MINUTES=0` schaltet den periodischen Abruf aus.
`MAIL_WORKER_ENABLED=false` stoppt die Ausführung der Jobs.
[Worker-Start](../apps/api/src/api/lifespan/startup/mail_worker.py),
[Job-Schleife](../apps/api/src/api/mail/jobs.py),
[Postgres-Warteschlange](../packages/py/db/src/db/accessors/mail_job.py).

Der Abruf speichert den Provider-Cursor und den letzten Zustand je Konto. Der Index hält
Metadaten, gekürzte Textfassungen und Metadaten zu Anhängen. Die Originalansicht holt die
unterstützten Originale auf Anfrage lesend beim Anbieter und speichert sie nicht. Ein
erfolgreicher Abruf mit neuen Mails reiht einen Job für fehlende KI-Kurzfassungen ein. Der
Mailindex und Chat-Verlauf sind Anwendungsdaten in Postgres. Fernet ist auf
Credential-Payloads begrenzt. Das Entfernen eines Kontos löscht lokal die Zugangsdaten,
indizierten Mails, Kurzfassungen, Aktionen, Jobs und den Abrufstand. Beim Anbieter bleiben
die Mails erhalten. [Sync](../apps/api/src/api/mail/sync.py),
[Mailmodell](../packages/py/db/src/db/models/mail_message.py),
[Konto entfernen](../apps/api/src/api/routers/api/v1/mail/accounts.py).

Jobs bleiben in der Datenbank, auch wenn der API-Prozess stoppt. Während eines Stopps
pausiert die Verarbeitung. Nach `MAIL_SYNC_STALE_MINUTES` (Standard zehn Minuten) kann
ein Worker einen verwaisten Job erneut beanspruchen. In der Studio-Probe am 13.11.2026 lief
derselbe Prozess am Ende des 31-minütigen Leerlauffensters weiter.
[Messwerte](superpowers/probes/2026-11-13-studio-proben.md).

## Deployment in Mistral Studio

1. Prüfe den freigegebenen Commit und pushe ihn auf das als `origin` konfigurierte GitHub-Repository.
   Die Mistral GitHub App benötigt Zugriff auf das Repository. Der Checkout muss sauber sein.
   Die GitHub-Actions in diesem Repository prüfen Code, Tests und Geheimnisse.
   [CI](../.github/workflows/ci.yml).
2. Richte Laufzeitwerte und Secrets in Studio ein. Beim Git-Deployment stammt die
   Laufzeitkonfiguration aus Studio. Prüfe insbesondere den Zugriff auf das API-Modul
   und den vorgesehenen Studio-Workspace. liam-e ist für einen einzelnen Nutzer ausgelegt.
   Die versionierte API verlässt sich auf die Anmeldung und Zugriffsbeschränkung des
   Gateways. [API-Zugriffsregel](../apps/api/src/api/routers/api/v1/__init__.py),
   [Sicherheitsrichtlinie](../SECURITY.md).
3. Führe im Repo-Root `mistral login` und `mistral deploy` aus. Die CLI baut den gepushten
   Commit. Der Block `deployment` in `mistral.json` bindet den Checkout an
   `<organization-id>`, `<workspace-id>` und `<app-id>`. Prüfe das angezeigte Ziel vor dem
   Start. Bei einer Ersteinrichtung ohne Bindung legt die CLI eine App an und schreibt
   die Bindung in das Manifest. Der vorhandene Block gehört zur bereits gebundenen App.
   Verwende für eine separate Installation eine eigene Bindung.
   [Manifest](../mistral.json), [Studio-Deployment](https://docs.mistral.ai/studio/apps/deploy),
   [Regeln zur Veröffentlichung](veroeffentlichung.md).
4. Studio stellt über das Manifest die API unter `/api`, das Web unter `/` und verwaltetes
   Postgres bereit. Das API-Modul übernimmt die injizierten `POSTGRES_*`-Werte, sofern kein
   `DATABASE_URL` gesetzt ist. Sein Pre-Start-Schritt wartet auf Postgres und führt Alembic
   bis `heads` aus. Prüfe den Modulstatus in Studio, die API-Startlogs mit
   `mistral apps logs api` und `/api/health` am angemeldeten Gateway. Teste Web, Abruf und
   bestätigte Aktionen mit synthetischen Daten in einem dafür vorgesehenen Test-Workspace.
   [DB-Settings](../packages/py/env/src/env/db.py),
   [Pre-Start](../packages/py/cli/src/cli/commands/pre_start.py),
   [Migrationen beim Start](../packages/py/cli/src/cli/commands/migrations.py),
   [Health](../apps/api/src/api/routers/api/internal/health.py).

Studio stellt die App und deren API bereit. Das Freigeben von Operationen als MCP-Tools ist
ein eigener Schritt. Die vollständige OpenAPI enthält auch Operationen, die Aktionen
ausführen. Halte dich für HTTP-Connectoren an die lesende Freigabeliste in den
[Agentenregeln](../AGENTS.md#sicherheit) und die
[MCP-Inventur](../apps/api/tests/test_mcp_exposure.py).

# liam-e — universelle Mail-App in Mistral Studio

Eine Mistral-App (siehe `mistral.json`), mit der **alle Mail-Konten an einer Stelle** verwaltet
werden — Gmail, Outlook, iCloud, Yahoo und beliebige andere Provider — und über die per **Chat
mit einem KI-Agenten** über alle Konten hinweg gesucht, gelesen, zusammengefasst und (nach
Bestätigung) geantwortet/versendet werden kann.

## Beschlossene Anforderungen (mit dem Nutzer abgestimmt am 2026-11-13)

| Thema | Entscheidung |
| --- | --- |
| Anbindung der Provider | Provider, die als **Mistral-Studio-Connector** existieren (z.B. `gmail`), werden über den bestehenden Connector angebunden (`api/mail/connectors.py`, REST `/v1/connectors/...` mit dem App-Key — die OAuth-Credentials liegen in Mistral, keine eigene OAuth-App nötig). Übrige: Gmail & Outlook per **eigenem OAuth2**, iCloud, Yahoo und alle anderen per **IMAP/SMTP mit App-Passwort** |
| Datenhaltung | **Sync in die managed Postgres**: Credentials verschlüsselt at rest, Mail-Index (Metadaten + Body-Texte), Chat-Verlauf |
| Senden von Mails | Agent darf frei suchen/lesen/zusammenfassen; **Senden/Antworten/Weiterleiten nur nach expliziter Bestätigung** des Entwurfs im Chat |
| Scope | Feature in `apps/api` + `apps/web`; Deploy über das bestehende `mistral.json` nach Mistral Studio; **Einzel-Nutzer**; UI auf Deutsch |

## Architektur

```
apps/web  (TanStack Start, Port 3001)                   Browser-UI: /, /chat/$conversationId, /mail, /accounts
   │  typisierter hey-api-Client (src/api/generated, generiert — nie per Hand editieren)
   ▼  same-origin /api
apps/api  (FastAPI, Port 3000, Route "/api")            Router-Baum = URL-Baum, Gruppen mit Access-Rule
   │  api/mail/                                         Mail-, Chat- und Worker-Logik
   ▼
packages/py/db   SQLModel-Modelle (drop-in in db/models/) + Accessors (db/accessors/) + Alembic
packages/py/env  Settings-Module (env/<name>.py), Workspace-Secrets via WorkspaceSecret
managed Postgres (Modul in mistral.json)                Mail-Index, Credentials, Chat-Verlauf
```

### Oberflächenrouten

- `/` — Chat-Start mit Begrüßung, Kontostand, Schnellaktionen und Composer; optional mit Mailbezug.
- `/chat/$conversationId` — Unterhaltung mit Verlauf, Antworten und Vorschlagskarten.
- `/mail` — Posteingang mit Liste und Filtern; `/mail/$messageId` — geöffnete Mail mit Lesebereich.
- `/accounts` — Kontenübersicht, Verbinden, erneutes Anmelden und Entfernen.

### Mail-Domäne (`apps/api/src/api/mail/`)

- `agent.py` — gestreamter Chat-Turn, Tool-Loop und gespeicherter Verlauf.
- `agent_tools.py` — lesende Agentenwerkzeuge und Erstellen von Vorschlägen.
- `agent_prompt.py` — deutsche Systemanweisungen für den Agenten.
- `chat_events.py` — typisierte Streaming-Ereignisse; `chat_schemas.py` — Chat-Ausgabemodelle.
- `actions.py` — Indexänderungen und einmaliges Rückgängigmachen; `action_backends.py` — Provider-Aktionen.
- `proposals.py` — Vorschläge speichern, bestätigen, abbrechen und nach Bestätigung ausführen.
- `newsletters.py` — Newsletter erkennen und unterstützte Abbestellwege ausführen.
- `insights.py` — Kurzfassungen und Fristen erzeugen und zwischenspeichern.
- `original.py` — Kopfzeilen und Quelltext einer Mail lesend beim Anbieter abrufen; nichts davon wird gespeichert.
- `jobs.py` — dauerhafte Jobs und periodisches Einreihen von Abrufen.
- `sync.py` — inkrementelle Änderungen im Index anwenden; `sync_connector.py`, `sync_gmail.py`,
  `sync_graph.py`, `sync_imap.py` — Abruf und Parsing je Provider; `sync_types.py` — gemeinsame Sync-Typen und Helfer.
- `send.py` — Versand über SMTP, Gmail, Graph oder Connector nach Bestätigung.
- `connectors.py` — Zugriff auf Mistral-Studio-Connectoren und deren Werkzeuge.
- `providers.py` — Provider-Registry, OAuth-Endpunkte und IMAP/SMTP-Voreinstellungen.
- `service.py` — Konten- und Credential-Verwaltung; `crypto.py` — Fernet-Verschlüsselung.
- `secrets.py` — Workspace-Secrets zur Laufzeit auflösen.
- `netguard.py` — ausgehende HTTPS-Aufrufe gegen private Ziele und DNS-Rebinding absichern.
- `transport.py` — Mail-Host-Policy und TLS-Transporte.
- `headers.py` — Adress- und Abbestell-Header verarbeiten.
- `state.py` — Kontostatus und Farben aus Konten, Sync-Status und Jobs ableiten.
- `models_catalog.py` — verfügbare Chat-Modelle kurzzeitig cachen.
- `dev_seed.py` — lokale Datenbank mit den Beispieldaten der Designboards füllen. Seed-Konten erreichen nie einen Anbieter: Senden und Abbestellen werden abgelehnt, Aktionen ändern nur den Index, Abrufe werden übersprungen, und Kurzfassungen entstehen nie per Modell (nur die gesäten sind abrufbar, sonst `503 insight_unavailable`).

Datenfluss: Ein Konto wird per Connector, OAuth2-Redirect oder IMAP-App-Passwort verbunden.
OAuth-Credentials bzw. die IMAP-Secret-Referenz landen **Fernet-verschlüsselt** in
`mail_credential`; Connector-Konten brauchen dort keinen Credential-Eintrag. Ein Abruf-Job füllt
`mail_message`. `POST /api/v1/chat` oder `/api/v1/chat/stream` lässt den Agenten auf dem Index
arbeiten. Er legt für Veränderungen und Versand Vorschläge an; `POST /api/v1/chat/proposals/{proposal_id}/confirm`
führt ausgewählte Einträge nach Bestätigung aus, `.../cancel` verwirft sie. Der Agent verändert
oder versendet nichts ohne bestätigte Karte. Vom Nutzer selbst ausgelöste Einzelaktionen im
Posteingang laufen dagegen direkt über die Mail-Aktionsendpunkte.

### API-Endpunkte

Inventar aus `apps/api/openapi.json`; jede Zeile nennt Methode, Pfad und `operation_id`.

| Routergruppe | Methode | Pfad | `operation_id` |
| --- | --- | --- | --- |
| Health | GET | `/api/health` | `health` |
| Chat | POST | `/api/v1/chat` | `chat_turn` |
| Chat | POST | `/api/v1/chat/stream` | `chat_stream` |
| Chat | GET | `/api/v1/chat/conversations` | `chat_conversations_list` |
| Chat | PATCH | `/api/v1/chat/conversations/{conversation_id}` | `chat_conversation_update` |
| Chat | GET | `/api/v1/chat/history` | `chat_history` |
| Chat | GET | `/api/v1/chat/models` | `chat_models_list` |
| Chat | POST | `/api/v1/chat/proposals/{proposal_id}/confirm` | `chat_proposal_confirm` |
| Chat | POST | `/api/v1/chat/proposals/{proposal_id}/cancel` | `chat_proposal_cancel` |
| Mail / Konten | GET | `/api/v1/mail/accounts` | `mail_accounts_list` |
| Mail / Konten | POST | `/api/v1/mail/accounts/imap` | `mail_account_connect_imap` |
| Mail / Konten | GET | `/api/v1/mail/accounts/oauth/{provider}/authorize` | `mail_account_oauth_authorize` |
| Mail / Konten | GET | `/api/v1/mail/accounts/oauth/{provider}/callback` | `mail_account_oauth_callback` |
| Mail / Konten | GET | `/api/v1/mail/accounts/options` | `mail_account_options` |
| Mail / Konten | DELETE | `/api/v1/mail/accounts/{account_id}` | `mail_account_delete` |
| Mail / Konten | PATCH | `/api/v1/mail/accounts/{account_id}` | `mail_account_update` |
| Mail / Konten | POST | `/api/v1/mail/accounts/{account_id}/sync` | `mail_account_sync` |
| Mail / Aktionen | POST | `/api/v1/mail/actions/undo` | `mail_actions_undo` |
| Mail / Connectoren | GET | `/api/v1/mail/connectors` | `mail_connectors_list` |
| Mail / Connectoren | POST | `/api/v1/mail/connectors/{name}/connect` | `mail_account_connect_connector` |
| Mail / Connectoren | GET | `/api/v1/mail/connectors/{name}/tools` | `mail_connector_tools_list` |
| Mail / Nachrichten | GET | `/api/v1/mail/messages` | `mail_messages_list` |
| Mail / Nachrichten | GET | `/api/v1/mail/messages/{message_id}` | `mail_message_get` |
| Mail / Nachrichten | POST | `/api/v1/mail/messages/{message_id}/actions` | `mail_message_action` |
| Mail / Nachrichten | GET | `/api/v1/mail/messages/{message_id}/insight` | `mail_message_insight` |
| Mail / Nachrichten | GET | `/api/v1/mail/messages/{message_id}/original` | `mail_message_original` |
| Mail / Übersicht | GET | `/api/v1/mail/summary` | `mail_summary` |
| Mail / Abruf | POST | `/api/v1/mail/sync` | `mail_sync_all` |

## Domänenmodell (Tabellen in Postgres)

- `mail_account` — verbundenes Konto: `provider` z.B. `google`, `microsoft`, `imap` oder Connector-Name wie `gmail`; `auth_type` ist `oauth2`, `imap_password` oder `mistral_connector`.
- `mail_credential` — verschlüsseltes Payload pro Konto+Art (`oauth2_tokens` | `imap_password`), unique (`account_id`, `kind`).
- `mail_message` — Mail-Index mit `folder`, `provider_uid`, `thread_id`, `subject`, `sender`, `sender_address`, `recipients_json`, `cc_json`, `reply_to_json` (Reply-To-Adressen; Antworten gehen daran statt an den Absender, der Gmail-Connector liefert sie nicht), `snippet`, `body_text`, `internal_date`, Lese-/Prioritätsflags, `labels_json`, `attachments_json`, `list_unsubscribe` und `list_unsubscribe_post`; unique (`account_id`, `folder`, `provider_uid`), Volltextindex `search_tsv`.
- `mail_sync_state` — Cursor, Status, Fehler und letzter Abruf je Konto.
- `mail_action` — ausgeführte Aktion mit `previous_json` und `undone_at` für Rückgängig.
- `mail_insight` — Kurzfassung (`points_json`), Frist, Antwortbedarf, Folgevorschläge und Modell je Mail.
- `mail_job` — dauerhafte Sync-/Insight-Warteschlange mit Status, Deduplizierung, Versuchen und Sperrzeit.
- `chat_conversation`, `chat_message` — Verlauf; Vorschläge in `proposal_json` mit `proposal_status`, Mailreferenzen/Vorschläge/Modell in `extras_json`; ältere Entwürfe tragen `draft_json`.

## Worker und periodischer Abruf

`api/mail/jobs.py` verarbeitet die dauerhafte Warteschlange `mail_job` im **API-Prozess**.
`MAIL_WORKER_ENABLED` (Standard `true`) startet den Worker beim API-Start;
`MAIL_WORKER_POLL_SECONDS` (Standard `2`) regelt die Wartezeit zwischen Prüfungen.
`MAIL_SYNC_INTERVAL_MINUTES` (Standard `5`, bei `0` kein periodischer Abruf) steuert das
Einreihen aktiver Konten; kürzlich abgerufene Konten und Konten mit letztem Fehler
`auth_expired` werden dabei übersprungen. Manueller Abruf und der OAuth-Callback nach erneutem
Verbinden reihen auch solche Konten ein; zur Ausführung muss der Worker laufen. `MAIL_SYNC_STALE_MINUTES` (Standard
`10`) bestimmt, wann ein gesperrter Job als veraltet gilt. Nach einem erfolgreichen Abruf mit
neuen Mails wird ein Insight-Job eingereiht, der fehlende Kurzfassungen auffüllt.

Stoppt Studio eine inaktive Instanz, pausiert auch der Worker und damit das Polling, bis eine
neue Anfrage die Instanz wieder startet. Gemessen wurden 31 Minuten Leerlauf **ohne** Stopp;
für längere Zeit ist das Verhalten nicht gemessen.

## Studio-Proben

Details und Messwerte: [Studio-Proben vom 13.11.2026](docs/superpowers/probes/2026-11-13-studio-proben.md).
Apps werden nicht automatisch zu MCP-Tools; erst der OpenAPI-Import als HTTP-Connector macht
Operationen zu Tools. App-Module haben keine Zeitpläne (Workflows schon). Bei jeweils 20 Aufrufen
lief dieselbe Instanz, auch nach 31 Minuten Leerlauf; ein späterer Stopp wurde nicht geprüft.
SSE kam durch das Gateway vor Ende des Streams an, mit einer einmaligen kurzen Stockung in der
ersten Messung. Der Gmail-Connector liefert bei `get_thread` keine vollständigen Kopfzeilen;
Newsletter-Erkennung nutzt daher bei Connector-Konten auch das Label `CATEGORY_PROMOTIONS` (`CATEGORY_UPDATES` zählt nicht, es enthält auch Bestellbestätigungen und Kontohinweise). `TRASH` ist als
System-Label unterstützt, `send_email` nimmt `replyToMessageId`; der Outlook-Connector lieferte
in der Probe HTTP 401.

## Stack & Befehle

- **Python:** `uv`-Workspace (Root `pyproject.toml`), FastAPI + SQLModel/Alembic. Tests: `bash tools/uv.sh run --no-sync pytest <pfad>`; Live-PG-Suiten: `bunx nx run db:test-pg-contract`
- **TypeScript:** bun 1.4 + Nx + TanStack Start/Router/Query + Tailwind 4, Vite 8
- Wichtigste Kommandos (Root):
  - `bun run install-all` — installiert alles inkl. generierten API-Client (`tools/gen-types.sh`)
  - `bunx nx run api:serve` — API lokal starten; `bun run dev:web` — Web lokal (Port 3001)
  - `bun run build` / `bun run test` / `bun run check` — Nx über alle Projekte
  - `bunx nx run api:gen-openapi` + `bash tools/gen-types.sh` — OpenAPI-Spec + TS-Client neu generieren (nach jeder API-Änderung; `gen-types.sh --check` ist der Drift-Gate)
  - `bunx nx run db:revision --message "..."` — Alembic-Revision autogenerieren; `bunx nx run db:migrate` — anwenden (`heads`, nicht `head`)
  - `bash tools/uv.sh run --no-sync python -m api.mail.dev_seed` — lokale Datenbank mit den Beispieldaten der Designboards füllen. Der Seed verweigert Datenbank-Hosts außer `localhost`, `127.0.0.1` und `::1`; Wiederholungen ersetzen nur Seed-Zeilen und zugehörige Insight-/Sync-/Chat-Zeilen. Beim visuellen Prüfen die API mit `MAIL_WORKER_ENABLED=false` starten, damit die Seed-Konten nicht abgerufen werden.

## Konventionen

### Python
- **Settings:** neue Settings als eigenes Modul `packages/py/env/src/env/<name>.py` (`class Env(BaseEnv)` + `env = Env()`); jeder Name **leer** in der Root-`.env.example` deklarieren. Secrets mit `Annotated[str | None, WorkspaceSecret()] = None` markieren (in Studio aus den Workspace-Secrets, lokal aus `.env`).
- **DB:** ein Model pro Datei in `packages/py/db/src/db/models/<table>.py` (drop-in, Loader entdeckt automatisch; **keine Cross-Table-Foreign-Keys**, Referenzen als String-Spalten), ein Accessor-Modul pro Tabelle in `db/accessors/` — ORM-Queries nur in Accessors. Migrationen: eine Branch pro Owner, `branch_labels` gesetzt, `down_revision = None` an der Wurzel.
- **Router:** Verzeichnisbaum = URL-Baum unter `apps/api/src/api/routers/`. Jedes Modul mit `router` serviert; jedes Paket braucht eine Access-Rule (`dependencies` in der `__init__.py`, `()` = anonym — nie weglassen, sonst Import-Fehler). `operation_id` ist eindeutig und wird in Studio zum MCP-Toolnamen. `[name]` in Datei/Verzeichnis = Pfadparameter `{name}`; `route.py` = Index.
- **Code/Kommentare/Docstrings auf Englisch** (Repo-Konvention); **UI-Texte auf Deutsch**.
- nie Secrets loggen oder committen; `.env` ist gitignored.

### TypeScript (apps/web)
- TanStack Router: eine Datei pro Route unter `src/routes/`; Landing-Page über `staticData: { landing: <rank> }` claimen. Nach neuen Routen `bunx nx run web:gen-routes`.
- API-Zugriff nur über den generierten Client (`src/api/generated/`, git-committed, nie manuell editieren) + `unwrap`/`dataOr404` aus `src/api/unwrap.ts`; `VITE_API_URL` konfiguriert die Base-URL. Aufrufe, deren Ergebnis vom HTTP-Status abhängt (404/409/502 bei Mail-Aktionen, Abrufen und Konten), dürfen den generierten Client ohne `unwrap` aufrufen und selbst nach Status verzweigen.
- Styling mit Tailwind 4; Pfade/englische Literale mit `// i18n-exempt` markieren. Tests: `bun test` (jsdom-Setup in `src/test/setup.js`).

## Sicherheit
- OAuth-Client-Secrets und `MAIL_TOKEN_ENCRYPTION_KEY` sind **Workspace-Secrets** (`WorkspaceSecret`), nie im Code; lokal nur in `.env`. **Secret-Namen in Mistral Studio sind lowercase** — die Auflösung ist case-insensitiv: Secret `mail_token_encryption_key` füllt `MAIL_TOKEN_ENCRYPTION_KEY` (siehe Docstring von `env/_mistral_secrets.py`).
- **Pro IMAP-Konto (iCloud, Yahoo, …) genau ein eigenes Workspace-Secret** mit dem App-Passwort, z.B. `yahoo-app-password`, `icloud-app-password` (lowercase). Beim Connect wird statt des Passworts der Secret-Name übergeben (`password_secret`); die App löst ihn zur Laufzeit über `GET /v1/secrets/values` auf (`api/mail/secrets.py`) und speichert in `mail_credential` nur die **Referenz** (verschlüsselt), nie den Wert — Rotation in Studio wirkt ohne Reconnect.
- Mail-Credentials werden vor dem Schreiben in `mail_credential` mit Fernet verschlüsselt (`api/mail/crypto.py`); der Key wird nie persistiert.
- Der Agent verändert oder sendet **nie ohne Bestätigung**: `create_draft` und Aktionswerkzeuge erzeugen Vorschläge; erst `POST /api/v1/chat/proposals/{proposal_id}/confirm` führt die Auswahl aus. `.../cancel` verwirft sie.
- CORS bleibt auf die eigene Origin beschränkt (`CORS_ORIGIN`).
- liam-e nie als HTTP-Connector in Studio importieren, oder nur mit den lesenden Operationen: `chat_conversations_list`, `chat_history`, `chat_models_list`, `health`, `mail_account_options`, `mail_accounts_list`, `mail_connector_tools_list`, `mail_connectors_list`, `mail_message_get`, `mail_message_insight`, `mail_message_original`, `mail_messages_list`, `mail_summary`
  `mail_message_insight` erzeugt eine fehlende Kurzfassung mit dem Modell und speichert sie in `mail_insight` (Modellkosten, keine Änderung an Mails; für Seed-Konten nie, dort gibt es nur gesäte Kurzfassungen).
  `mail_message_original` ruft die Mail beim Anbieter ab (lesend, ohne sie als gelesen zu markieren) und speichert nichts.
  Jeder Import der OpenAPI macht aus jeder Operation ein MCP-Tool; ein Studio-Agent könnte sonst Vorschläge bestätigen, Aktionen ausführen oder Konten verbinden, ohne dass der Eigentümer es sieht — einzelne Tools lassen sich in Studio nach dem Import abschalten.
  Neue verändernde Operationen gehören bewusst in `MUTATING_OPERATIONS` in `apps/api/tests/test_mcp_exposure.py`, sonst scheitert der Inventur-Test.

## Arbeitsweise für Agents
- Vor jeder Arbeit an der Oberfläche (`apps/web`, Texte, auch Antworttexte des Assistenten) `DESIGN.md` lesen; sie regelt Tokens, Bausteine, Responsive-Verhalten und wie Texte klingen.
- Minimale Diffs, bestehende Patterns kopieren (siehe Modul-Docstrings — sie dokumentieren die Konventionen jeweils lokal).
- Nach API-Änderungen immer `gen-types` laufen lassen und `apps/api/openapi.json` + `apps/web/src/api/generated` mit committen.
- Änderungen an Tabellen immer mit Migration (`db:revision` + `db:migrate`), nie von Hand editierte `versions/`-Dateien.
- Vor dem Commit: `bun run check` (baut alles und prüft den generierten Client) und die betroffenen Test-Suiten laufen lassen.

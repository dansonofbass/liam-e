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
- `/settings` und `/settings/prompts` — Einstellungen mit Vorlagenbibliothek; `settingsSections` ist der Navigationseinstieg für weitere implementierte Bereiche.
- `/settings/prompts/new` und `/settings/prompts/$promptId` — Vorlage anlegen oder bearbeiten, auf allen Bildschirmgrößen als eigene Ansicht.

### Mail-Domäne (`apps/api/src/api/mail/`)

- `agent.py` — gestreamter Chat-Turn, Tool-Loop und gespeicherter Verlauf.
- `agent_tools.py` — lesende Agentenwerkzeuge und Erstellen von Vorschlägen.
- `agent_prompt.py` — deutsche Systemanweisungen für den Agenten.
- `chat_events.py` — typisierte Streaming-Ereignisse; `chat_schemas.py` — Chat-Ausgabemodelle.
- `actions.py` — Indexänderungen und einmaliges Rückgängigmachen; `action_backends.py` — Provider-Aktionen.
- `proposals.py` — Vorschläge speichern, bestätigen, abbrechen und nach Bestätigung ausführen.
- `newsletters.py` — Newsletter erkennen und unterstützte Abbestellwege ausführen.
- `insights.py` — Kurzfassungen und Fristen erzeugen und zwischenspeichern; ohne Mailtext gibt es keinen Modellaufruf, sondern eine leere Kurzfassung.
- `original.py` — Kopfzeilen und Quelltext einer Mail lesend beim Anbieter abrufen; nichts davon wird gespeichert.
- `jobs.py` — dauerhafte Jobs und periodisches Einreihen von Abrufen.
- `sync.py` — inkrementelle Änderungen im Index anwenden und veraltete Body-Texte nachlesen; `sync_connector.py`, `sync_gmail.py`,
  `sync_graph.py`, `sync_imap.py` — Abruf, Parsing und Nachlesen (`fetch_bodies`) je Provider; `sync_types.py` — gemeinsame Sync-Typen und Helfer,
  darunter `body_text`/`html_to_text` (eine Textfassung für alle Provider: `text/plain` zuerst, außer es ist nur ein kurzer
  Platzhalter neben längerem HTML; sonst HTML ohne Stile, Skripte, Kommentare und unsichtbare Füllzeichen, mit Absätzen und
  Listenpunkten), `BODY_VERSION` und `reread_http` (Nachlesen über REST, je Mail ausgewertet).
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
| Kalender | GET | `/api/v1/calendar/sources` | `calendar_sources_list` |
| Kalender | PATCH | `/api/v1/calendar/sources/{source_id}` | `calendar_source_update` |
| Kalender | DELETE | `/api/v1/calendar/sources/{source_id}` | `calendar_source_delete` |
| Kalender | POST | `/api/v1/calendar/sources/{source_id}/sync` | `calendar_source_sync` |
| Kalender | GET | `/api/v1/calendar/occurrences` | `calendar_occurrences_list` |
| Kalender | GET | `/api/v1/calendar/occurrences/{occurrence_id}` | `calendar_occurrence_get` |
| Vorlagen | GET | `/api/v1/prompts` | `prompts_list` |
| Vorlagen | POST | `/api/v1/prompts` | `prompt_create` |
| Vorlagen | GET | `/api/v1/prompts/{id}` | `prompt_get` |
| Vorlagen | PATCH | `/api/v1/prompts/{id}` | `prompt_update` |
| Vorlagen | DELETE | `/api/v1/prompts/{id}` | `prompt_delete` |
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
| Aufgaben | POST | `/api/v1/tasks` | `tasks_create` |
| Aufgaben | GET | `/api/v1/tasks/occurrences` | `tasks_occurrences_list` |
| Aufgaben | POST | `/api/v1/tasks/occurrences/{occurrence_id}/complete` | `tasks_occurrence_complete` |
| Aufgaben | POST | `/api/v1/tasks/occurrences/{occurrence_id}/skip` | `tasks_occurrence_skip` |
| Aufgaben | POST | `/api/v1/tasks/occurrences/{occurrence_id}/reopen` | `tasks_occurrence_reopen` |

## Aufgabendomäne

`api/tasks/` enthält die Serienanlage, RRULE-Auswertung, Reconcile und Zustandswechsel. Die
Aufgabenrouter legen Serien an und materialisieren dabei die erste begrenzte Reconcile-Seite
in derselben Transaktion. Weitere Seiten werden nicht automatisch abgerufen. Serienrevision,
Archivieren und Löschen sind noch offen.

## Kalenderdomäne

`api/calendar/` enthält Adaptervertrag, Snapshot-Dispatch und eine Quellen-Scope-Prüfung. Der
Kalenderindex speichert Quellen, Ereignisse, Instanzen und Abdeckung; Anbieteradapter müssen
vollständige Snapshots liefern. Die lesenden Endpunkte greifen ausschließlich auf den Index zu.
`GET /api/v1/calendar/occurrences` nimmt ein Fenster von höchstens 90 Tagen und beliebig viele
`source_ids` (höchstens 50) und liefert die Instanzen zeitlich geordnet; Ganztägiges zählt ab
Mitternacht UTC seines ersten Tages. Der Cursor trägt Startzeit und ID der letzten Instanz.
Vollständige Snapshot-Fenster erweitern die Abdeckung nur, wenn sie die bisherige Abdeckung
überlappen oder berühren; sonst ersetzen sie sie. Jede gespeicherte Instanz überlappt die
Abdeckung (auch wenn sie über deren Rand hinausreicht); andere Instanzen werden entfernt.
Ereignisse werden nur entfernt, wenn sie im aktuellen Snapshot fehlen und keine verbliebene
Instanz sie referenziert; enthaltene Ereignisse bleiben auch ohne Instanzen erhalten. `stale` bedeutet, dass noch kein erfolgreicher
Snapshot vorliegt oder der Index unvollständig ist; ohne periodischen Abruf sagt das Alter des
letzten Erfolgs allein nichts über die Aktualität beim Anbieter aus.

## Domänenmodell (Tabellen in Postgres)

- `calendar_source`, `calendar_event`, `calendar_occurrence`, `calendar_sync_state` — Kalenderquelle mit Verbindungsreferenz und Freigabe (`is_active`), Serienstamm je Quelle, Instanz als halboffenes Intervall (ganztägig als Datum, sonst UTC mit Zeitzone; eindeutig je Quelle und `external_id`) sowie Abdeckung, letzter Erfolg und Unvollständigkeit je Quelle.
- `task_series`, `task_schedule_revision`, `task_occurrence` — Aufgabenserie, Zeitplanrevision und materialisierte Fälligkeit; Erstellungskennung und Instanzschlüssel sind eindeutig.
- `mail_account` — verbundenes Konto: `provider` z.B. `google`, `microsoft`, `imap` oder Connector-Name wie `gmail`; `auth_type` ist `oauth2`, `imap_password` oder `mistral_connector`.
- `mail_credential` — verschlüsseltes Payload pro Konto+Art (`oauth2_tokens` | `imap_password`), unique (`account_id`, `kind`).
- `mail_message` — Mail-Index mit `folder`, `provider_uid`, `thread_id`, `subject`, `sender`, `sender_address`, `recipients_json`, `cc_json`, `reply_to_json` (Reply-To-Adressen; Antworten gehen daran statt an den Absender, der Gmail-Connector liefert sie nicht), `snippet`, `body_text`, `body_version` (Version der Textfassung, 0 = vor der Versionierung), `internal_date`, Lese-/Prioritätsflags, `labels_json`, `attachments_json`, `list_unsubscribe` und `list_unsubscribe_post`; unique (`account_id`, `folder`, `provider_uid`), Volltextindex `search_tsv`.
- `mail_sync_state` — Cursor, Status, Fehler und letzter Abruf je Konto.
- `mail_action` — ausgeführte Aktion mit `previous_json` und `undone_at` für Rückgängig.
- `mail_insight` — Kurzfassung (`points_json`), Frist, Antwortbedarf, Folgevorschläge und Modell je Mail.
- `mail_job` — dauerhafte Sync-/Insight-Warteschlange mit Status, Deduplizierung, Versuchen und Sperrzeit.
- `chat_conversation`, `chat_message` — Verlauf; Vorschläge in `proposal_json` mit `proposal_status`, Mailreferenzen/Vorschläge/Modell in `extras_json`; ältere Entwürfe tragen `draft_json`.

## Vorlagen und Turn-Kontext

Vorlagen gehören dem festen serverseitigen Scope `installation`; der Zugriff auf die
Single-Owner-App wird vom Deployment beschränkt, nicht durch eine neue App-Identität.
`prompt_template` hält Name, Version und aktuelle Revision; Bearbeiten erzeugt eine neue
`prompt_revision`. Auswahlen in `chat_conversation.prompt_revision_id` bleiben angeheftet.
Conversation-PATCH benötigt `expected_version`; `null` als Revision wählt den Standard.
Vorlagen-POST nimmt `name` und `text`, PATCH zusätzlich `expected_version`, DELETE
`expected_version` als Queryparameter. GET einer Vorlage liefert auch `revisions`
(neueste zuerst), damit ältere Revisionen ausdrücklich gewählt werden können.
Neue Turns speichern Revisionsreferenz/Hash, App-Prompt-Version und den aufgelösten
Kontoumfang in `chat_context`; `chat_message.context_id` verbindet den Verlauf damit.
Der JSON-Kontoumfang enthält `account_ids`, `selection` (Konto-ID oder `null` für alle)
und bei unbelegtem Altverlauf `legacy_mixed: true`.
`preference_revision_id` bleibt als Erweiterungspunkt leer. Text wird nur als
Nutzerinhalt an das Modell gegeben, nie als App-Regel oder Chat-Extra gespeichert.
Löschen entfernt Vorlageninhalt und Revisionsinhalt, hinterlässt `removed`-Markierungen,
widerruft Kontexte und setzt aktive Auswahlen zurück. Bereits gesendete Modellanfragen
lassen sich nicht zurückholen. Vorschläge widerrufener Kontexte bleiben offen und können abgebrochen,
aber nicht bestätigt werden (`409 proposal_context_revoked`). Entscheidend ist der atomare Claim:
Ein danach wirksamer Widerruf macht eine bereits angenommene Bestätigung nicht rückgängig.
Der Agent prüft den Widerruf unmittelbar vor jedem Modellaufruf und Werkzeug sowie während des
Streams nach jeweils zehn Deltas; ein widerrufener Stream wird geschlossen und meldet `context_revoked`.
Für einen Verlauf werden die zugehörigen Kontexte jeweils in einer Datenbankabfrage geladen.
Rückgängig-Anfragen im Posteingang werden nach 15 Sekunden abgebrochen; bei unklarem Ergebnis
bleibt die Aktion für einen erneuten Versuch noch zehn Sekunden verfügbar.
Kontowechsel mit Verlauf benötigen eine neue Unterhaltung; „Alle Konten“ bleibt dieselbe Auswahl, auch wenn Konten hinzukommen oder wegfallen.

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

Ändert sich die Textfassung (`body_text` in `sync_types.py`), wird `BODY_VERSION` erhöht. Jeder
Abruf liest danach bis zu 25 INBOX-Mails mit älterer Version beim Anbieter nach (ohne sie als
gelesen zu markieren) und überschreibt Text und Vorschau in derselben Zeile; ihre Kurzfassung wird
verworfen, wenn sich der Text ändert oder leer bleibt. Kennt der Anbieter die Mail nicht mehr oder
liefert er sie unter anderer Message-ID, bleibt der alte Text und nur die Version steigt. Eine Mail,
die gerade nicht lesbar ist (Serverfehler, Ratenlimit, Verbindungsabbruch), wird später erneut
gefragt, die übrigen gelten trotzdem. Ihre Wartezeit verdoppelt sich je Fehlschlag, von einer Stunde
bis zu einem Tag (im API-Prozess gemerkt, ein Neustart vergisst sie), damit wenige unlesbare Mails
die übrigen nicht aufhalten. Eine Kurzfassung wird nur gespeichert, solange die Mail noch den Text hat,
den das Modell gelesen hat; neuer Text und das Verwerfen der alten Kurzfassung gehen in einer
Transaktion. Ein Fehler beim Nachlesen lässt den Abruf selbst erfolgreich.

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
- Tooltips und Menüs hängen im `<body>` und werden nie per CSS positioniert oder über einen Vorfahren gestaltet (kein `top`/`left`/`right`/`bottom` an `.le-menu`/`.le-tooltip`, kein `.le-x .le-menu`); die Lage kommt aus `src/ds/floating.ts` (`pos` bzw. `placement` ist nur die Wunschseite). `src/ds/floating.test.tsx` prüft das. Siehe DESIGN.md §5, „Schwebendes“.

## Sicherheit
- OAuth-Client-Secrets und `MAIL_TOKEN_ENCRYPTION_KEY` sind **Workspace-Secrets** (`WorkspaceSecret`), nie im Code; lokal nur in `.env`. **Secret-Namen in Mistral Studio sind lowercase** — die Auflösung ist case-insensitiv: Secret `mail_token_encryption_key` füllt `MAIL_TOKEN_ENCRYPTION_KEY` (siehe Docstring von `env/_mistral_secrets.py`).
- **Pro IMAP-Konto (iCloud, Yahoo, …) genau ein eigenes Workspace-Secret** mit dem App-Passwort, z.B. `yahoo-app-password`, `icloud-app-password` (lowercase). Beim Connect wird statt des Passworts der Secret-Name übergeben (`password_secret`); die App löst ihn zur Laufzeit über `GET /v1/secrets/values` auf (`api/mail/secrets.py`) und speichert in `mail_credential` nur die **Referenz** (verschlüsselt), nie den Wert — Rotation in Studio wirkt ohne Reconnect.
- Mail-Credentials werden vor dem Schreiben in `mail_credential` mit Fernet verschlüsselt (`api/mail/crypto.py`); der Key wird nie persistiert.
- Der Agent verändert oder sendet **nie ohne Bestätigung**: `create_draft` und Aktionswerkzeuge erzeugen Vorschläge; erst `POST /api/v1/chat/proposals/{proposal_id}/confirm` führt die Auswahl aus, sofern der Turn-Kontext beim Claim nicht widerrufen ist. `.../cancel` verwirft sie auch nach Widerruf.
- CORS bleibt auf die eigene Origin beschränkt (`CORS_ORIGIN`).
- liam-e nie als HTTP-Connector in Studio importieren, oder nur mit den lesenden Operationen: `calendar_occurrence_get`, `calendar_occurrences_list`, `calendar_sources_list`, `chat_conversations_list`, `chat_history`, `chat_models_list`, `health`, `mail_account_options`, `mail_accounts_list`, `mail_connector_tools_list`, `mail_connectors_list`, `mail_message_get`, `mail_message_insight`, `mail_message_original`, `mail_messages_list`, `mail_summary`, `prompt_get`, `prompts_list`, `tasks_occurrences_list`
  `mail_message_insight` erzeugt eine fehlende Kurzfassung mit dem Modell und speichert sie in `mail_insight` (Modellkosten, keine Änderung an Mails; für Seed-Konten nie, dort gibt es nur gesäte Kurzfassungen).
  `mail_message_original` ruft die Mail beim Anbieter ab (lesend, ohne sie als gelesen zu markieren) und speichert nichts.
  Jeder Import der OpenAPI macht aus jeder Operation ein MCP-Tool; ein Studio-Agent könnte sonst Vorschläge bestätigen, Aktionen ausführen oder Konten verbinden, ohne dass der Eigentümer es sieht — einzelne Tools lassen sich in Studio nach dem Import abschalten.
  Neue verändernde Operationen gehören bewusst in `MUTATING_OPERATIONS` in `apps/api/tests/test_mcp_exposure.py`, sonst scheitert der Inventur-Test.

## Veröffentlichung und private Daten

liam-e soll veröffentlicht werden können. Alles, was in Git landet (Dateien und
Commit-Nachrichten), und alles auf GitHub (Issues, PRs, Reviews, Kommentare) gilt deshalb schon
jetzt als öffentlich.

- **Nichts über den Owner oder seine Umgebung:** keine echten Namen, Mailadressen, Mail- oder
  Kalenderinhalte, Kontakte, Hostnamen, internen Domains, IP-Adressen, absoluten lokalen Pfade,
  Benutzer- oder Gerätenamen und keine Namen der eigenen Infrastruktur oder Werkzeuge. Pfade
  relativ zum Repo angeben.
- **Mistral-Tenant:** Organisations-, Workspace- und App-ID stehen nur in `mistral.json`, weil
  `mistral deploy` sie dort braucht. Überall sonst `<organization-id>`, `<workspace-id>` und
  `<app-id>`; App- und Gateway-URLs des Deployments nicht aufschreiben.
- **Keine Links auf private Ressourcen:** Claude-Artefakte, Sitzungen und private Dokumente beim
  Namen nennen statt verlinken (etwa Design-System „liam-e“). Ausgenommen ist nur die
  Attributionszeile `Claude-Session` in Commits und PR-Beschreibungen.
- **Testdaten sind synthetisch:** Adressen unter `example.org`, `example.com`, `example.net`,
  `*.example` oder `*.test`, erfundene Namen und Inhalte. Provider-Voreinstellungen (`gmail.com`,
  `icloud.com` …) sind Konfiguration; Tests dazu nehmen Platzhalter wie `me@` oder `x@`. Nie eine
  echte Mail, einen echten Termin oder echte Kopfzeilen als Fixture übernehmen, auch nicht
  gekürzt. Screenshots nur mit den Seed-Daten aus `api.mail.dev_seed`.
- **Credentials nie im Klartext:** keine Passwörter, App-Passwörter, Tokens, API-Keys,
  OAuth-Codes, Cookies oder Fernet-Schlüssel, weder in Code, Tests, Doku, `.env.example`,
  Issues, PRs, Commit-Nachrichten und Logs noch in Aufträgen an andere Modelle. Werte gibt es nur
  als Workspace-Secret in Studio oder lokal in `.env` (gitignored). Agents lesen `.env` nicht und
  geben keine Werte daraus aus; Secret-*Namen* wie `yahoo-app-password` sind unkritisch. Tests
  nehmen sichtbare Wegwerfwerte (`test-only`) oder zur Laufzeit erzeugte Schlüssel.
- **Ein committetes Geheimnis gilt als verbrannt:** zuerst rotieren, dann entfernen; die
  Historie behält es. Nie über eine Allowlist in `.gitleaks.toml`, über `.gitleaksignore` oder
  einen Kommentar `gitleaks:allow` „lösen“ (die CI ignoriert solche Kommentare).
- **Logs und Fehlertexte** enthalten keine Mailinhalte, Adressen, Vorlagentexte, Tokens oder
  Secret-Werte.
- **Lokaler Agent-Zustand** (`.superpowers/`, `.codegraph/`, `.remember/`,
  `.claude/settings.local.json`, `.claude/worktrees/`, Playwright-Ausgaben) bleibt ungetrackt;
  `.gitignore` deckt ihn ab.
- **Durchsetzung:** CI-Job `secrets` (gitleaks über die ganze Historie mit `.gitleaks.toml`) und
  `tests/test_public_repo_hygiene.py` (Tenant-IDs außerhalb von `mistral.json`, private Links,
  Home-Pfade, echt wirkende Mailadressen). Die Allowlist ist leer; eine Ausnahme braucht einen
  geprüften Fehlalarm, gilt nur für die Regel, die Datei und den konkreten Wert und nennt die
  Begründung im Eintrag. CI-Actions sind auf Commit-SHAs gepinnt.
- Was vor einer Veröffentlichung noch zu tun ist, steht in
  [docs/veroeffentlichung.md](docs/veroeffentlichung.md).

## Arbeitsweise für Agents
- Vor jeder Arbeit an der Oberfläche (`apps/web`, Texte, auch Antworttexte des Assistenten) `DESIGN.md` lesen; sie regelt Tokens, Bausteine, Responsive-Verhalten und wie Texte klingen.
- Minimale Diffs, bestehende Patterns kopieren (siehe Modul-Docstrings — sie dokumentieren die Konventionen jeweils lokal).
- Nach API-Änderungen immer `gen-types` laufen lassen und `apps/api/openapi.json` + `apps/web/src/api/generated` mit committen.
- Änderungen an Tabellen immer mit Migration (`db:revision` + `db:migrate`), nie von Hand editierte `versions/`-Dateien.
- Vor dem Commit: `bun run check` (baut alles, prüft die Typen der Oberfläche mit `tsc` und den generierten Client) und die betroffenen Test-Suiten laufen lassen.
- Issues und PRs über die Vorlagen in `.github/` (`ISSUE_TEMPLATE/`, `pull_request_template.md`). Eine Aufgabe ergibt
  genau einen Branch und einen PR, auch wenn sie mehrere Issues umfasst; jedes Issue bekommt eigene Commits und ein
  eigenes Schließwort (`Closes #12. Closes #13.`). Was nicht geprüft wurde, steht im PR ausdrücklich als nicht geprüft.

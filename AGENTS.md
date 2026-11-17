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
- `/tasks` und `/tasks/$taskId` — Aufgabenliste, manuelle Anlage und Fälligkeiten mit Verlauf.
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
| Agent-Lesefassade | GET | `/api/agent-read/v1/mail/accounts` | `liam_mail_accounts` |
| Agent-Lesefassade | GET | `/api/agent-read/v1/mail/messages` | `liam_mail_search` |
| Agent-Lesefassade | GET | `/api/agent-read/v1/mail/messages/{message_id}` | `liam_mail_read` |
| Agent-Lesefassade | GET | `/api/agent-read/v1/mail/summary` | `liam_mail_summary` |
| Kalender | POST | `/api/v1/calendar/feeds/validate` | `calendar_feed_validate` |
| Kalender | POST | `/api/v1/calendar/feeds` | `calendar_feed_subscribe` |
| Kalender | DELETE | `/api/v1/calendar/feeds/validations/{validation_id}` | `calendar_feed_validation_discard` |
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
| Einstellungen | GET | `/api/v1/settings/ui` | `settings_ui_get` |
| Einstellungen | PATCH | `/api/v1/settings/ui` | `settings_ui_update` |
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
| Aufgaben | GET | `/api/v1/tasks` | `tasks_list` |
| Aufgaben | GET | `/api/v1/tasks/{series_id}` | `tasks_get` |
| Aufgaben | PATCH | `/api/v1/tasks/{series_id}` | `tasks_update` |
| Aufgaben | POST | `/api/v1/tasks/{series_id}/archive` | `tasks_archive` |
| Aufgaben | DELETE | `/api/v1/tasks/{series_id}` | `tasks_delete` |
| Aufgaben | POST | `/api/v1/tasks` | `tasks_create` |
| Aufgaben | POST | `/api/v1/tasks/preview` | `tasks_preview` |
| Aufgaben | POST | `/api/v1/tasks/reconcile` | `tasks_reconcile` |
| Aufgaben | GET | `/api/v1/tasks/occurrences` | `tasks_occurrences_list` |
| Aufgaben | POST | `/api/v1/tasks/occurrences/{occurrence_id}/complete` | `tasks_occurrence_complete` |
| Aufgaben | POST | `/api/v1/tasks/occurrences/{occurrence_id}/skip` | `tasks_occurrence_skip` |
| Aufgaben | POST | `/api/v1/tasks/occurrences/{occurrence_id}/reopen` | `tasks_occurrence_reopen` |

## Agent-Lesefassade

`api/mcp/registry.py` zählt die vier ausdrücklich freigegebenen Mail-Leseoperationen auf;
`api/mcp/mail.py` liest ausschließlich den vorhandenen INBOX-Index über Accessors. Der Scope
stammt aus einem `ReadGrant`, nie aus Requestparametern. Der Standard-Verifier in
`api/mcp/access.py` lehnt alle Anfragen mit 401 ab. Ein späterer nativer Transport muss nach
positivem Zugriffsnachweis einen eigenen `ReadAccessVerifier` an `get_read_access_verifier`
anbinden und dieselben Services mit dessen geprüftem Grant aufrufen. Grants sind auf 100
Konto-IDs begrenzt; fremde Auswahlen ergeben 403, unbekannte und fremde Mail-IDs jeweils 404.
Auch das Lesen per ID bleibt im INBOX-Index: Eine inzwischen verschobene Mail antwortet wie eine
fehlende. Ein leerer Grant liefert leere Ergebnisse, nie alle Konten.
Relative Links `/mail/<uuid>` vermeiden eine unkonfigurierte externe Origin. Maildaten sind
fremder Inhalt, keine Anweisungen. Der Indexstand wird ausgewiesen, Provideraktualität bleibt
unbekannt. Ein erfolgreicher Abruf kann nur eine begrenzte Seite enthalten; ohne gespeicherten
Vollständigkeitsmarker bleibt der Index auch bei Status `ok` konservativ unvollständig. Der
Zeitstempel bezeichnet den letzten Versuch, nicht zwingend einen Erfolg. Die reduzierte Spec ist
keine Runtime-Autorisierung; produktive Exposition bleibt
bis zum Zugriffsnachweis gesperrt. Der Uvicorn-Access-Log entfernt Querystrings dieser
Routen, auch wenn sich das Format des Logeintrags ändert; Gateway- und Proxy-Logs müssen vor einer Freischaltung unabhängig ebenso geschützt werden.
Der Export wird mit `bunx nx run api:gen-agent-openapi` reproduziert.

## Aufgabendomäne

Die Oberfläche unter `apps/web/src/tasks/` verwendet die generierten Task-Endpunkte. Die
Anlage zeigt eine serverseitige Vorschau; `reconcile.ts` begrenzt jeden Abruf auf einen
festen Horizont und setzt den gespeicherten Fortschritt beim nächsten Öffnen fort.

`api/tasks/` enthält die Serienanlage, RRULE-Auswertung, Reconcile und Zustandswechsel. Die
Aufgabenrouter legen Serien an und materialisieren dabei die erste begrenzte Reconcile-Seite
in derselben Transaktion. Weitere Seiten werden ausdrücklich über `POST /tasks/reconcile`
abgerufen. PATCH unterstützt Einzeländerungen und neue Zeitplanrevisionen.

`PATCH /tasks/{series_id}` benötigt die Serienversion `expected_version`, die gewählte
`occurrence_id`, deren `expected_occurrence_version`, `scope` und den neuen lokalen
Start `start`. Das aktuelle Schema bearbeitet Fälligkeiten, nicht Titel oder Notizen;
Textfelder werden abgelehnt, damit historische Instanzen nicht implizit umbenannt werden.
`scope=occurrence` verschiebt nur eine offene Instanz und erhält deren ursprünglichen
Schlüssel; Genauigkeit (Datum/Uhrzeit), Zeitzone und Regel bleiben gleich. Beide Versionen
steigen. `scope=this_and_following` wählt eine zukünftige offene Instanz der aktuellen
Revision; ihre tatsächliche Fälligkeit und ihr ursprünglicher Schlüssel müssen noch in
der Zukunft liegen. Bereits fällige Instanzen werden nicht als Trennstelle verwendet.
Der gespeicherte Abruffortschritt muss die Vollständigkeit der alten Revision bis zur
exklusiven Trennstelle belegen; sonst wird die Teilung mit `409 task_version_conflict`
abgelehnt und muss nach weiterem Reconcile erneut versucht werden. Die alte Regel endet exklusiv vor dem
ursprünglichen Schlüssel; offene zukünftige Instanzen ab dort werden ersetzt. Vergangene,
erledigte und übersprungene Instanzen bleiben erhalten, auch bereits verschobene
Vergangenheitsausnahmen. Die neue Revision darf Datum/Uhrzeit und Zeitzone ändern,
startet aber nicht vor dem lokalen Trenn-Tag; der Start muss zur neuen Regel passen.
Ohne `rrule` bleibt die alte Regel;
explizites `rrule: null` erzeugt eine Einzelaufgabe. Eine neue Revision braucht eine
Zeitzone, auch wenn die alte Datumsrevision noch `null` trägt.
Kollisionen mit erledigten Instanzen werden mit derselben COUNT-/DST-Auswertung wie bei
der Materialisierung geprüft, auch außerhalb der ersten Abrufseite; sie liefern
`409 task_revision_conflict` ohne Aufgabenänderung. Andere Versions-/Zustandskonflikte
liefern `409 task_version_conflict`. Alle Änderungen und die erste neue Reconcile-Seite
liegen in der Transaktion des Aufrufers; alte Revisionscursor werden zurückgewiesen.

Archivieren und endgültiges Löschen benötigen `expected_version` der Serie.
Archivieren sperrt neue Materialisierung und storniert in einem bedingten Update nur
offene zukünftige Instanzen; heute fällige Datumsaufgaben sowie bereits fällige und
abgeschlossene Instanzen bleiben erhalten. Wiederöffnen zukünftiger Instanzen einer
archivierten Serie ist gesperrt. DELETE benötigt zusätzlich ausdrücklich
`confirm_history_loss: true` im JSON-Body und entfernt Serie, Revisionen und Instanzen
in derselben Transaktion. Beide Dienste nehmen eine Session und committen nicht selbst.
Seriensperren serialisieren diese Aktionen mit Reconcile und Zustandswechseln;
veraltete Versionen ergeben 409, fehlende Serien 404.

`GET /tasks` und `GET /tasks/{series_id}` lesen ausschließlich gespeicherte Daten im
serverseitigen Scope `app`. Beide benötigen das inklusive lokale Datumsfenster
`due_from`/`due_to` (höchstens 366 Tage). Die Liste ist nach Serien-ID paginiert
(`limit` 1–100, `cursor`) und filtert `status=active|archived` sowie
`source=all|unlinked|account`; `account` braucht `source_account_id`, `unlinked`
bedeutet ohne Quellmail. Quellreferenzen werden nicht mit lebenden Mail-/Kontenzeilen
verknüpft: Entfernte Quellen lassen Aufgaben und ihre Filterzuordnung bestehen.
Die Liste enthält Serien mit überlappender Regelgültigkeit oder gespeicherter Fälligkeit
im Fenster; eine passende Serie muss nicht an jedem Tag eine Fälligkeit haben.
Das Detail liefert die aktuelle Revision und eine eigene paginierte Instanzliste,
optional mit Instanzstatus. `complete` gilt je Serie ausschließlich für das ausgewiesene
Fenster, unabhängig von der Instanz-Pagination oder dem Statusfilter. Es wird konservativ
aus gespeichertem Fortschritt abgeleitet; ein zeitgebundener Tag gilt erst vollständig,
wenn der ganze lokale Tag abgedeckt ist. GET materialisiert nichts und ruft kein Modell auf.

Reconcile nimmt eine Serien-ID, optional Revisions-ID und Cursor, `limit` (1–100) und
`advance`. Ohne Cursor setzt der Aufruf unter Sperre den gespeicherten Fortschritt fort;
ein mitgelieferter veralteter Cursor ergibt 409. Die Antwort nennt Revisions-ID, Cursor,
Zielzeitpunkt und `complete` (nur für das feste Fenster ab Serienbeginn bis zum Ziel).
`advance: true` startet erst nach Abschluss mit dessen exaktem Cursor einen neuen Lauf
bis Serverzeit plus 30 Tage. Die letzte geprüfte Position bleibt im Abschlusscursor;
Fortschritt und Einfügen erfolgen gemeinsam in der Transaktion des Aufrufers.

`POST /tasks/preview` schreibt nichts und benötigt Start, Ende und Zeitzone. Das Fenster
ist auf 366 Tage und die Seite auf 100 Kandidaten begrenzt; `complete: false` bedeutet,
dass die Vorschau nicht das ganze Fenster zeigt. Sie nennt entfallene lokale Uhrzeiten
und unmögliche Monatstage monatlicher Regeln. Auch dieser lesende POST bleibt gemäß
der MCP-Inventur außerhalb freigegebener Agentenoberflächen.

`COUNT` zählt nach RFC 5545 nur existierende Fälligkeiten: Nicht existierende lokale
Uhrzeiten verbrauchen keinen Zählerplatz. Vorschau und Persistenz verwenden denselben
Parser. Bereits abgeschlossene Abrufläufe zeitgebundener COUNT-Serien mit altem
Abschlussmarker werden beim nächsten Reconcile seitenweise erneut ausgewertet;
die ursprünglichen Instanzschlüssel verhindern Duplikate und erhalten den Zustand.
So werden fehlende Endinstanzen ergänzt, ohne Datenmigration.

Neue Aufgaben brauchen auch ohne Uhrzeit eine gültige IANA-Zeitzone; fehlt sie,
antwortet die Anlage mit `422 task_invalid`. Das Datum bleibt ein Datum. Alte
Datumsrevisionen mit `timezone: null` verwenden für Tagesgrenzen UTC, ohne die
Daten umzuschreiben. Heute gilt als bereits fällig, überfällig erst ab dem nächsten
lokalen Tag. Eine neue Serienrevision kann die Zeitzone ausdrücklich setzen.

## Kalenderdomäne

Die Oberfläche unter `/calendar` zeigt die gemeinsame Agenda; `/calendar/$occurrenceId`
öffnet eine stabile Instanz. `is_active` bleibt die Freigabe: Pausierte Quellen werden
in der Verwaltung und als Hinweis angezeigt, ihre Termine bleiben bis zur Aktivierung
verborgen. Sie tragen nicht zu einer Aussage „Keine Termine“ bei und bleiben auch für
Chatwerkzeuge und alte Referenzen gesperrt (Entscheidung zu #22: Option A).
`CalendarSetup` in `apps/web/src/calendar/CalendarSources.tsx` öffnet das ICS-Formular
`FeedSetup`: Name, private Kalenderadresse und ausdrücklich angezeigte Fallbackzone.
`webcal` wird sichtbar zu `https`; die Serverprüfung normalisiert unabhängig nochmals.
Adresse und Prüftoken bleiben nur im Dialogzustand, nie im Browser-Storage oder Query-Cache.
Änderungen verwerfen die Prüfung; Abonnieren und Adresswechsel invalidieren die Query-Gruppe
`calendar`. Google-Einrichtung ist weiterhin nicht freigegeben.
Die Agenda gruppiert und zeigt Zeitpunkte in der Browser-Zeitzone; Ganztägiges bleibt
bei seinem Datum. Lokale Tagesgrenzen werden in Zeitpunkte umgerechnet. Weil der
Index-Endpunkt nur ganze UTC-Daten akzeptiert, wird das Abfragefenster nach außen
aufgerundet und umfasst zusätzlich die Ganztagsdaten. Fenster über 90 UTC-Tagen werden
in angrenzende Teilfenster aufgeteilt, die wie Cursorseiten nur ausdrücklich nachgeladen
werden. Randtreffer außerhalb der gewählten lokalen Starttage werden ausgeblendet,
doppelte Instanz-IDs aus angrenzenden Fenstern zusammengeführt. Eine leere Teilseite
behauptet nicht „Keine Termine“, solange weitere Seiten oder Teilfenster fehlen.
Ein Stand älter als 24 Stunden bekommt einen Altershinweis; beim Öffnen wird einmal je
Quelle über den expliziten Verwaltungsendpunkt ein Abruf angefragt. Das verspricht keine
Aktualität beim Anbieter. `seed_calendars` ergänzt fünf synthetische Quellen für Google-/ICS-
Darstellung, Ganztag, langen Titel, alten Stand, fehlende Abdeckung und Pause. Ihre festen
IDs werden vor dem Einreihen und vor der Adapterausführung übersprungen.

„Im Chat fragen“ öffnet eine neue Unterhaltung mit `context_occurrence_id` und ausdrücklich
gewählter Quelle. Der Kalenderumfang (`calendar_source_ids`, maximal 50) steht getrennt vom
Mailkonto im Composer und wird als JSON-Liste in `chat_context.calendar_scope_json` gespeichert.
Der Datenbankstandard `[]` gibt Altverlauf keinen Kalenderzugriff. Jede Änderung der Auswahl,
auch eine Erweiterung, benötigt bei vorhandenem Verlauf eine neue Unterhaltung (409
`conversation_scope_change_requires_new`); historische Texte bleiben erhalten. Diese konservative
Regel vermeidet eine unbelegte Neuzuordnung alter Nutzer-, Werkzeug- oder Assistententexte.
Der Resolver prüft alle historischen Nachrichtenkontexte; der Agent prüft dieselbe Herkunft
nochmals vor dem Aufbau der Modellnachrichten. Pausieren/Entfernen macht einen Turn mit dieser
Quelle bei der nächsten Live-Prüfung ungültig, auch vor weiteren Modell- und Werkzeugaufrufen.
Bereits übertragene Modellanfragen können nicht zurückgeholt werden. Beim Neustart übernimmt die
Oberfläche nur Kalender, die sie noch als aktiv kennt; ohne belegte Auswahl bleibt der Umfang leer.

`api/mail/calendar_tools.py` stellt `search_calendar` und `get_calendar_occurrence` bereit:
Indexzugriff ohne Provider, lokale Datumsfenster bis 90 Tage und Cursorseiten bis 50 Instanzen;
Werkzeugparameter können den Turn-Umfang nur einschränken. Kalendertexte und Quellennamen stehen
in `untrusted_calendar_data`, einschließlich Stand und Abdeckung. Kalender-Schreibwerkzeuge fehlen;
der Prompt untersagt auch Ersatzaktionen als Mailvorschlag, Kalenderkopie oder Aufgabe.
`calendar_timezone` kommt aus dem Browser; ältere Clients ohne Angabe behalten Europe/Berlin.
Chat-Extras und das SSE-Ereignis `calendars` enthalten nur `source_id`/`occurrence_id`, keine Titel
oder privaten Verbindungsreferenzen. Belege lesen ihre Darstellung erneut über die freigegebene
Quelle und stabile Instanzroute; pausierte, entfernte oder nicht passende Quellen zeigen keine
Termindaten. Ort und Beschreibung fehlen im Indexvertrag und werden nicht vorgetäuscht.
Die autogenerierte Migration ergänzt die Spalte mit Serverstandard und führt die bestehenden
Migrationsköpfe zusammen; sie wurde nicht von Hand geändert.

ICS-Abonnements verwenden die privaten Tabellen `calendar_feed_config` und
`calendar_feed_validation`. `POST /calendar/feeds/validate` verwendet denselben sicheren
Abruf und isolierten Parser wie Jobs. Erst nach vollständiger Prüfung wird die gesamte
Konfiguration verschlüsselt gespeichert; die redigierte Vorschau enthält nur den selbst
gewählten Namen, Fenster und Anzahl. Prüftokens gelten genau zehn Minuten und werden
per `DELETE RETURNING` in der Anlagetransaktion einmalig verbraucht. Der feste serverseitige
Scope ist `installation`; Konfiguration einschließlich Ersatzquelle und Quellenrevision
ist gebunden. `feed_secrets.py` nutzt den bestehenden Fernet-Schlüssel; nur ein Hash
zufälliger Prüftokens wird gespeichert, Konfigurationsprüfsummen sind mit dem Token
gekeyt. Abbruch verwirft die Prüfung ausdrücklich; der Worker bereinigt Ablauf jede Minute
sowie bei weiteren Prüfungen/Anlagen. Schemafehler geben keine Eingabewerte zurück.
`POST /calendar/feeds` legt die Quelle und den ersten Job atomar an; mit geprüfter
`source_id`/`expected_revision` ersetzt derselbe Endpunkt die alte Adresse atomar.
Die bestehende Generation bleibt bis zum erfolgreichen Abruf erhalten; alte Validatoren
werden beim Adresswechsel entfernt. Verwaltungsoperationen sind keine Agenten-Lesetools.

`StoredICSAdapter` wird im gemeinsamen Dispatch registriert. Jobpayloads enthalten nur
`source_id`; Fenster werden zur Ausführung als heute −30 bis +180 Tage bestimmt.
HTTP-Validatoren sind verschlüsselt und werden mit dem vollständig validierten Snapshot
atomar aktiviert. 304 expandiert gespeicherte Komponenten erneut, auch für ein neues Fenster.
Ein gültiger leerer Snapshot leert den Bestand; Fehler erhalten Generation und Abdeckung.
Quellenrevisionen sperren veraltete Snapshot-Commits auch nach Pause/Resume oder Adresswechsel.
Ein gemeinsames transaktionales Advisory-Lock serialisiert Queue, Ersatz, Entfernen und
Snapshotaktivierung; Entfernen löscht Jobs, Index, Status und private Konfiguration.
Historische Chattexte bleiben bestehen; aktive Quellenscope-Prüfungen sperren entfernte Quellen.

`CALENDAR_SYNC_INTERVAL_MINUTES` ist standardmäßig 30. Der gemeinsame Worker prüft jede Minute
aktive ICS-Quellen, unabhängig von der Mailperiodik. Beim Öffnen fragt die Agenda über den
Verwaltungsendpunkt mit `due_only=true` nur fällige Abrufe an. Manuelles Abrufen hat eine
persistierte Minute Wartezeit. 429/5xx und Transportfehler erhalten begrenzten exponentiellen
Backoff mit Jitter; nach drei Fehlern endet die kurze Wiederholung und die Quelle kehrt zum
regulären Intervall ab `last_checked_at` zurück. Weitere Fehler starten keine neue kurze
Wiederholung; ein Erfolg setzt den Fehlerzustand zurück.
401/403/404 fordern eine Adressprüfung und stoppen automatische Versuche bis zu manuellem
Abruf, Resume oder Adressersatz. Pausierte
Quellen und Seeds werden nicht abgerufen; gestoppte Studio-Instanzen garantieren keine Periodik.

`api/calendar/` enthält Adaptervertrag, Snapshot-Dispatch und eine Quellen-Scope-Prüfung. Der
Kalenderindex speichert Quellen, Ereignisse, Instanzen und Abdeckung; Anbieteradapter müssen
vollständige Snapshots liefern. Die lesenden Endpunkte greifen ausschließlich auf den Index zu.
`GET /api/v1/calendar/occurrences` nimmt ein Fenster von höchstens 90 Tagen und beliebig viele
`source_ids` (höchstens 50) und liefert die Instanzen zeitlich geordnet; Ganztägiges zählt ab
Mitternacht UTC seines ersten Tages. Der Cursor trägt Startzeit und ID der letzten Instanz.
Zeitpunkte ohne Dauer gehören zum Fenster, wenn ihr Zeitpunkt am Anfang oder innerhalb, aber nicht am Ende liegt.
Vollständige Snapshot-Fenster erweitern die Abdeckung nur, wenn sie die bisherige Abdeckung
überlappen oder berühren; sonst ersetzen sie sie. Jede gespeicherte Instanz überlappt die
Abdeckung (auch wenn sie über deren Rand hinausreicht); andere Instanzen werden entfernt.
Ereignisse werden nur entfernt, wenn sie im aktuellen Snapshot fehlen und keine verbliebene
Instanz sie referenziert; enthaltene Ereignisse bleiben auch ohne Instanzen erhalten. `stale` bedeutet, dass noch kein erfolgreicher
Snapshot vorliegt oder der Index unvollständig ist; ohne periodischen Abruf sagt das Alter des
letzten Erfolgs allein nichts über die Aktualität beim Anbieter aus.

`ics_fetch.py` provides the HTTPS acquisition layer for ICS. It shares the
numeric-pinned streaming transport in `mail/netguard.py`, rejects non-public/mixed DNS
answers and mapped/transition addresses, and permits only HTTPS:443 with three same-origin
redirects within one 15-second deadline. Wire and decoded bodies each have a 5 MiB limit;
only identity/gzip and calendar MIME types are accepted. `normalize_url` explicitly returns
the HTTPS spelling (including private path/query data) for owner confirmation; never log it.
Fetch results hide body and validators from repr, and task-local filtering suppresses
httpcore traces that could expose headers or protocol content.

`ics.py` combines acquisition and isolated parsing in `ICSAdapter`, used per request by
`feed_jobs.StoredICSAdapter` and the privileged validation service. It
accepts an explicit fallback IANA zone and UTC-midnight window; `default_window` supplies
today −30 to +180 days. A 304 requires previously normalized events and re-expands them for
the requested window; it never treats an old window as fresh coverage. `ics_parse.py` uses
exactly pinned `icalendar==7.3.0` for folded/escaped properties, typed values and VTIMEZONE,
and the existing `python-dateutil==4.0.0` for lazy RRULE iteration. The hand-written fixture
corpus tests this combination; avoiding an eager recurrence wrapper lets the app enforce
its own exception, completeness and resource rules. Schema 1 in `Event.recurrence` stores
masters, exceptions, canonical rule fields, typed dates/local/UTC times, nominal/exact
durations and structured custom-zone observances, not raw ICS. Re-expansion needs only
these JSON-compatible events. Identities hash UID plus the original normalized recurrence
ID (or the non-null master sentinel), so moving an occurrence does not change its identity.
Custom VTIMEZONE instants use UTC in the shared occurrence contract while retaining the
original definition in recurrence data. Floating times never use the server's local zone.

Each parse/re-expansion uses a fresh exec subprocess (`ics_worker.py`), limited to 256 MiB
address space, 5 CPU seconds and 8 wall seconds. Timeout/cancellation kills, drains and
reaps the process before returning. IPC is capped at 16 MiB input and 32 MiB output, feed
input at 5 MiB; limits may be lowered per call, not raised. The component ceiling is 10,000
(including ignored components); the expansion/work ceiling is 50,000 candidates per feed,
including historical candidates needed for COUNT and exception validation, plus a 50,000
output ceiling. These are per-call budgets, not a global concurrency policy. Missing POSIX
resource support fails closed. Worker diagnostics are discarded, logging and networking
are disabled, and errors contain fixed codes only. Tests prove process reaping on timeout,
CPU/memory exhaustion and caller cancellation, while the API loop continues running.

VEVENT supports UID, DTSTART, DTEND/DURATION, SUMMARY/DESCRIPTION/LOCATION/STATUS,
RRULE, date/date-time RDATE/EXDATE and individual RECURRENCE-ID replacements/cancellations.
All-day ends are exclusive; DURATION P1D is nominal, PT24H and DTEND-derived durations are
exact. Local DST recurrence skips nonexistent generated candidates before applying COUNT;
ambiguous times choose the first offset. Explicit nonexistent times fail. Unsupported
scheduling METHODs other than PUBLISH, non-Gregorian CALSCALE, RANGE/THISANDFUTURE,
EXRULE, RSCALE, leap seconds and period-valued RDATE fail explicitly. Instantaneous
timed events are represented as points with equal start and end instants.
Duplicate masters/exceptions/supported properties, orphan exceptions, unresolved zones and an RRULE
whose DTSTART does not match also fail. VTODO, VALARM, attachments and external URLs are
never executed or loaded; instructions in descriptions remain plain data.

## Domänenmodell (Tabellen in Postgres)

- `calendar_source`, `calendar_event`, `calendar_occurrence`, `calendar_sync_state` — Kalenderquelle mit Verbindungsreferenz und Freigabe (`is_active`), Serienstamm je Quelle, Instanz als halboffenes Intervall oder Zeitpunkt ohne Dauer (ganztägig als Datum mit positivem Intervall, sonst UTC mit Zeitzone; eindeutig je Quelle und `external_id`) sowie Abdeckung, letzter Erfolg und Unvollständigkeit je Quelle.
- `calendar_feed_config`, `calendar_feed_validation` — verschlüsselte Feedkonfiguration und kurzlebige, einmalig verbrauchbare Prüfungen; keine öffentlichen Ausgabemodelle.
- `task_series`, `task_schedule_revision`, `task_occurrence` — Aufgabenserie, Zeitplanrevision und materialisierte Fälligkeit; Erstellungskennung und Instanzschlüssel sind eindeutig.
- `mail_account` — verbundenes Konto: `provider` z.B. `google`, `microsoft`, `imap` oder Connector-Name wie `gmail`; `auth_type` ist `oauth2`, `imap_password` oder `mistral_connector`.
- `mail_credential` — verschlüsseltes Payload pro Konto+Art (`oauth2_tokens` | `imap_password`), unique (`account_id`, `kind`).
- `mail_message` — Mail-Index mit `folder`, `provider_uid`, `thread_id`, `subject`, `sender`, `sender_address`, `recipients_json`, `cc_json`, `reply_to_json` (Reply-To-Adressen; Antworten gehen daran statt an den Absender, der Gmail-Connector liefert sie nicht), `snippet`, `body_text`, `body_version` (Version der Textfassung, 0 = vor der Versionierung), `internal_date`, Lese-/Prioritätsflags, `labels_json`, `attachments_json`, `list_unsubscribe` und `list_unsubscribe_post`; unique (`account_id`, `folder`, `provider_uid`), Volltextindex `search_tsv`.
- `mail_sync_state` — Cursor, Status, Fehler und letzter Abruf je Konto.
- `mail_action` — ausgeführte Aktion mit `previous_json` und `undone_at` für Rückgängig.
- `mail_insight` — Kurzfassung (`points_json`), Frist, Antwortbedarf, Folgevorschläge und Modell je Mail.
- `mail_job` — dauerhafte Sync-/Insight-Warteschlange mit Status, Deduplizierung, Versuchen und Sperrzeit.
- `chat_conversation`, `chat_message` — Verlauf; Vorschläge in `proposal_json` mit `proposal_status`, Mailreferenzen/Vorschläge/Modell in `extras_json`; ältere Entwürfe tragen `draft_json`.
- `ui_settings` — die eine geräteübergreifende Bedienungskonfiguration mit festem serverseitigem Scope (`installation`, unique): `swipe_left`/`swipe_right` aus der Allowlist `none`, `archive`, `toggle_read`, `trash`, `revision` für bedingte Updates und `updated_at`; Erstinitialisierung mit links `archive`, rechts `toggle_read`.

## Vorlagen und Turn-Kontext

Vorlagen gehören dem festen serverseitigen Scope `installation`; der Zugriff auf die
Single-Owner-App wird vom Deployment beschränkt, nicht durch eine neue App-Identität.
`prompt_template` hält Name, Version, aktuelle Revision und das Änderungsdatum `updated_at` (bei Altbeständen unbekannt und `null`); Bearbeiten erzeugt eine neue
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
- liam-e nie als HTTP-Connector in Studio importieren, oder nur mit den lesenden Operationen: `calendar_occurrence_get`, `calendar_occurrences_list`, `calendar_sources_list`, `chat_conversations_list`, `chat_history`, `chat_models_list`, `health`, `liam_mail_accounts`, `liam_mail_read`, `liam_mail_search`, `liam_mail_summary`, `mail_account_options`, `mail_accounts_list`, `mail_connector_tools_list`, `mail_connectors_list`, `mail_message_get`, `mail_message_insight`, `mail_message_original`, `mail_messages_list`, `mail_summary`, `prompt_get`, `prompts_list`, `settings_ui_get`, `tasks_get`, `tasks_list`, `tasks_occurrences_list`
  `mail_message_insight` erzeugt eine fehlende Kurzfassung mit dem Modell und speichert sie in `mail_insight` (Modellkosten, keine Änderung an Mails; für Seed-Konten nie, dort gibt es nur gesäte Kurzfassungen).
  `mail_message_original` ruft die Mail beim Anbieter ab (lesend, ohne sie als gelesen zu markieren) und speichert nichts.
  `settings_ui_get` legt beim allerersten Lesen einmalig die Standardbelegung in `ui_settings` an; eine bestehende Belegung ändert es nie.
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

<!-- OPENWIKI:START -->

## OpenWiki

This repository has a generated `openwiki/` evidence index. It is optional just-in-time context, not required startup reading.

- Do not enumerate, preload, or search wikis at task start. Use retrieval when the user asks for it, when unfamiliar architecture or dependency behavior materially affects the task, or when source inspection leaves an important uncertainty. Stop once the question is grounded.
- When those conditions apply and OpenWiki retrieval tools are available, use `openwiki_search` for just-in-time context and `openwiki_read` for the relevant complete sections. If search returns `workspace_required`, ask which listed workspace to use and retry with its ID.
- Use `openwiki_list_workspaces` or `openwiki_list_wikis` when workspace membership itself needs to be discovered.
- If the retrieval tools are unavailable, read `openwiki/quickstart.md` and follow its links to the relevant pages.
- Treat source code and tests as authoritative. A brief's unknowns and review items are verification gaps, not automatic requirements.
- Prefer the narrowest quiet validation that proves the changed behavior. Preserve complete failure output.

The scheduled OpenWiki GitHub Actions workflow refreshes the repository wiki. Do not hand-edit generated OpenWiki pages unless explicitly asked; prefer updating source code/docs and letting OpenWiki regenerate.

<!-- OPENWIKI:END -->

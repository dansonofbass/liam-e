# liam-e: Oberfläche und Mail-Aktionen – Design

Stand 2026-11-13. Grundlage für den Umsetzungsplan.

Quellen, die dieses Dokument nicht wiederholt:

- `DESIGN.md`: Tokens, Bausteine, Texte, Responsive-Verhalten, Chat-Regeln. Was dort
  steht, gilt.
- Design-System „liam-e“: https://claude.ai/artifact/MJRNJYUPnK6ciYFc2U2KAz
  (`tokens.json`, `tokens.css`, `components/bundle.css`, 17 Bausteine mit Vorschau).
- Abgenommene Screens: https://claude.ai/artifact/PdW36jpJZ5beBAgTh27yDC, Seite „Screens“.
  Die Ansichten dort sind die Vorlage für Aufbau, Texte und Zustände.
- `AGENTS.md`: Architektur, Konventionen, Sicherheitsregeln.

## 1. Absicht

liam-e soll in Mistral Studio laufen und alle Mail-Konten des Owners an einem Ort
zusammenführen. Mit den verfügbaren Mistral-Modellen soll er über alle Mails chatten und
Aufgaben erledigen können. Das Backend kann heute verbinden, abrufen, suchen und
Entwürfe nach Bestätigung senden. Die Oberfläche ist rudimentär: zwei Seiten (`/chat`,
`/mail`) ohne Gestaltung, ohne Streaming, ohne Aktionen im Posteingang.

Der Owner will:

- einen **aufgeräumten Posteingang** mit Aktionen;
- einen **Chat als Startseite**, der über alle Mails Auskunft gibt und Aufgaben anstößt,
  mit Schnellaktionen wie „Ungelesenes zusammenfassen“, „Priorisieren“ und „Newsletter
  aufräumen“;
- einen Assistenten, der **vorschlägt, während ein Klick bestätigt**: Nichts verändert
  Mails oder verschickt etwas ohne Bestätigung;
- eine Oberfläche, die klar, ruhig und flüssig wirkt, mit erkennbaren Buttons und
  Tooltips, sauberer Navigation und sauberem Streaming im Chat;
- **Texte, die auf Deutsch geschrieben klingen** und nicht übersetzt.

## 2. Ziele, Nicht-Ziele, Anti-Ziele

**Ziele**

1. `apps/web` neu aufbauen nach DESIGN.md und den abgenommenen Screens: Chat-Start,
   Unterhaltung mit Streaming, Bestätigungskarten, Posteingang mit Lesebereich, Konten,
   jeweils für Desktop, Tablet und Handy.
2. Backend um alles ergänzen, was die Screens brauchen: Streaming, Modellwahl,
   Einzelaktionen mit „Rückgängig“, Vorschläge für mehrere Mails, Newsletter und
   Abbestellen, „Kurz gefasst“ mit Fristen, Seiten und Filter im Posteingang,
   inkrementeller Abruf.
3. Die bekannten Sicherheitslücken schließen (§8).

**Nicht-Ziele (diese Runde)**

- Mehrere Nutzer, Rollen, Freigaben.
- Eigene Ordner- oder Label-Verwaltung, Regeln, Filter beim Anbieter.
- Mails frei schreiben ohne Assistenten. Versand läuft nur über Entwürfe im Chat.
- Anhänge herunterladen. Angezeigt werden Name und Größe; der Download folgt später.
- HTML-Darstellung von Mails. Mails erscheinen als Text.
- Englische Oberfläche.

**Anti-Ziele (wäre ein Fehlschlag, auch wenn es technisch läuft)**

- Der Assistent oder ein anderer Aufrufer kann Mails senden, verschieben oder abbestellen,
  ohne dass der Owner eine Karte bestätigt hat.
- Texte klingen übersetzt, Buttons heißen „OK“ oder „Absenden“.
- Streaming springt in Absätzen, flackert oder lässt die Liste wegscrollen, während der
  Owner liest.
- Am Handy erscheint etwas nur beim Überfahren, oder die Seite scrollt seitlich.
- Ein Secret, ein Token oder ein Passwort verlässt die App oder landet im Log.

## 3. Rahmen

- Stack bleibt: FastAPI + SQLModel/Alembic, TanStack Start/Router/Query, Tailwind 4,
  bun + Nx, Deploy über `mistral.json`. Konventionen aus `AGENTS.md`, insbesondere: ein
  Model und ein Accessor je Tabelle, Router-Baum gleich URL-Baum, `operation_id` eindeutig,
  generierter API-Client nie von Hand, nach API-Änderungen `gen-types`.
- `operation_id` wird in Mistral Studio zum Namen eines MCP-Tools. Jede API-Operation ist
  damit auch für Agenten in Studio aufrufbar (§8, S5).
- Einzelnutzer hinter dem Studio-Gateway; die API hat keine eigene Anmeldung.
- Secrets nur als Workspace-Secrets; IMAP-Passwörter nur als Referenz auf ein Secret.
- Eine Aufgabe, ein Branch, ein PR mit eigenen Commits je Bereich (Owner-Regel).

## 4. Ansätze

### 4.1 Wie die Oberfläche entsteht

| Ansatz | Was | Abwägung |
|---|---|---|
| **A: Design-System übernehmen** (gewählt) | `tokens.css` und `bundle.css` aus dem Design-System nach `apps/web/src/styles/` übernehmen, die Tokens zusätzlich als Tailwind-`@theme` für Layout-Utilities. Dünne React-Bausteine in `apps/web/src/ds/` setzen die `le-*`-Klassen. Screens neu unter `src/routes/`. | Sieht aus wie abgenommen, weil dieselben Regeln gelten. Die Klassen sind schon auf Kontrast, Zustände und reduzierte Bewegung geprüft. Zwei Stilquellen (Klassen und Tailwind) brauchen eine klare Grenze: Bausteine nur über Klassen, Layout in Screens über Tailwind. |
| B: Alles in Tailwind nachbauen | Jeden Baustein aus Utilities neu zusammensetzen. | Idiomatischer für Tailwind, aber doppelte Arbeit und Abweichungen vom Abgenommenen. Hover-, Tooltip- und Streaming-Details müssten neu entstehen. |
| C: Bestehende Seiten verbessern | `chat.tsx` und `mail.tsx` schrittweise gestalten. | Ihr Aufbau trägt weder Streaming noch Vorschläge noch die Hülle je Breakpoint. Am Ende wäre trotzdem fast alles neu. |

A ist meine Entscheidung; der Owner hat das Wie übergeben.

### 4.2 Wie Antworten zum Browser kommen

| Ansatz | Abwägung |
|---|---|
| **Server-Sent Events über `POST`** (gewählt) | Ein Endpunkt liefert Ereignisse (Status, Textstücke, Karten, Ende). Einfach, Abbrechen ist ein Abbruch der Anfrage. Risiko: Das Studio-Gateway könnte Antworten puffern. |
| Polling eines Antwortstands | Robust gegen Puffern, aber ruckelig, mehr Last, eigener Zustand im Server. Bleibt Ausweichweg, falls SSE durch das Gateway nicht flüssig ankommt (§11). |
| WebSocket | Mehr Aufwand ohne Gewinn, denn die Richtung ist fast nur Server zu Browser. |

## 5. Vom Owner entschieden

1. Neues Design-System, Stilrichtung C „Weich“, mit dunklem Theme nach Systemeinstellung.
2. Startseite ist der Chat mit vier Schnellaktionen: Ungelesenes zusammenfassen,
   Priorisieren, Newsletter aufräumen, Heute fällig.
3. Vorschlagen und mit einem Klick bestätigen; nichts ohne Bestätigung (DESIGN.md §9.2).
   Einzelaktionen an einer Mail löst der Owner selbst aus; sie wirken sofort und lassen
   sich rückgängig machen.
4. Handy mit Kopfzeile und Schublade, keine untere Navigationsleiste; Composer unten.
5. Schrift Plus Jakarta Sans, selbst gehostet über Fontsource.
6. Alle Texte der Oberfläche im Katalog `apps/web/src/i18n/de.ts`.
7. Die Screens auf dem Canvas, darin: „Kurz gefasst“ über jeder Mail, kein direktes
   Antworten (nur „Antwort entwerfen“), Aktionsleisten am Handy oben und unten.

## 6. Oberfläche

### 6.1 Routen

| Pfad | Inhalt |
|---|---|
| `/` | Chat-Start: Begrüßung, Stand, Schnellaktionen, Composer. Claimt die Landing-Page. |
| `/chat/$conversationId` | Unterhaltung mit Verlauf, Streaming, Karten. |
| `/mail` | Posteingang. Desktop: Liste und leerer Lesebereich („Wähle eine Mail aus.“). |
| `/mail/$messageId` | Desktop: Liste mit geöffneter Mail. Tablet und Handy: Mail als eigene Ansicht mit Zurück. |
| `/accounts` | Konten und „Konto verbinden“. Ziel des OAuth-Rücksprungs (§7.9). |

Die alten Routen `/chat` und `/mail` werden ersetzt. Pfade sind Englisch und
`// i18n-exempt`.

### 6.2 Hülle

- Seitenleiste mit Marke, Chat, Posteingang (Zähler ungelesen), Konten, darunter die
  letzten Unterhaltungen und der Stand („4 Konten · Stand 08:57“).
- Tablet: schmale Symbolleiste mit Tooltips, Unterhaltungen in einer Schublade.
- Handy: Kopfzeile (Menü, Titel, Aktion rechts), Schublade mit `scrim`.
- Seitenwechsel blenden nur die Hauptfläche über; Seitenleiste und Composer bleiben stehen.

### 6.3 Bausteine, Stil, Texte

- `apps/web/src/styles/tokens.css`: Tokens aus dem Design-System, ergänzt um
  `@media (prefers-color-scheme: dark)` für `:root:not([data-theme="light"])` und um
  `scrim`. `apps/web/src/styles/ds.css`: `bundle.css` ohne den Google-Fonts-Import.
- `apps/web/src/ds/`: die 17 Bausteine aus DESIGN.md §6 als React-Komponenten mit
  denselben Namen, Symbole aus `lucide-react` (exakt gepinnt) nach dem Lexikon in §6.
  Dazu eine Hülle (`AppShell`) und ein `Drawer`.
- Screens setzen keine eigenen Bedienelemente aus rohem `<button>` oder `<input>`
  zusammen.
- Alle Texte im Katalog `i18n/de.ts` mit Pluralformen über `Intl.PluralRules` und
  Zahlen, Beträgen und Daten über `Intl` (`de-DE`). Die Prüfliste aus DESIGN.md §2.7 gilt
  für jeden Eintrag.
- Fontsource-Paket für Plus Jakarta Sans, exakt gepinnt.

### 6.4 Chat

- Composer: Textfeld, Kontoauswahl („Alle Konten“ oder einzelne), Senden. Während einer
  Antwort wird Senden zu Anhalten.
- Ablauf einer Antwort wie DESIGN.md §9.1: Status mit drei Punkten, Text läuft gepuffert
  ein (etwa drei Zeichen je 24 ms, unabhängig davon, wie groß die Stücke vom Server
  kommen), am Ende Mail-Karten, Bestätigungskarte und bis zu drei Folgevorschläge.
- Mitscrollen nur, solange der Owner unten ist; sonst bleibt die Liste stehen, und ein
  Button „Zum Ende“ erscheint.
- Modellmenü in der Kopfzeile, Wahl gilt je Unterhaltung.
- Antworten als sicheres Markdown ohne rohes HTML; Links nur `http`, `https`, `mailto`.

### 6.5 Posteingang

- Liste über alle Konten, nach Zeit, gruppiert in Heute, Gestern, Diese Woche, Älter.
  Endloses Nachladen über einen Cursor (§7.7).
- Filter: Konten, Ungelesen, Wichtig, Mit Anhang. „Wichtig“ heißt: beim Anbieter markiert,
  oder „Kurz gefasst“ hat eine Frist oder eine erwartete Antwort erkannt.
- Zeile: Avatar in Kontofarbe, Absender, Kontoschild, Betreff, Vorschau, Zeit,
  Fristpunkt, Anhangsymbol. Desktop: Aktionsleiste beim Überfahren; Touch: Button
  „Weitere Aktionen“.
- Tastatur am Desktop: `j`/`k` wechseln, `e` archiviert, `u` gelesen/ungelesen, `#` oder
  `Entf` in den Papierkorb, `Enter` öffnet. Die Tooltips nennen die Taste.
- Geöffnete Mail: Aktionsleiste, Betreff, Absender, „Kurz gefasst“, Text, Anhänge.
  Öffnen markiert die Mail als gelesen.
- Einzelaktion: sofort ausführen, Zeile blendet aus, Hinweis mit „Rückgängig“ unten in der
  Liste, bis zur nächsten Aktion oder höchstens 10 Sekunden.

### 6.6 Konten

- Karten je Konto mit Anbieter, Zustand (Stand, Wird abgerufen, Anmeldung abgelaufen,
  Fehler mit Ursache), Zahl der Mails und Verbindungsart (Connector, Anmeldung, IMAP).
- Aktionen: Jetzt abrufen, Erneut anmelden, Umbenennen, Entfernen. Entfernen bestätigt in
  einem Dialog mit dem Satz aus dem Screen („… löscht liam-e nur seine Kopie der Mails“).
- „Konto verbinden“ mit drei Wegen: Gmail über den Studio-Connector, Outlook über
  Microsoft-Anmeldung, andere Anbieter über IMAP mit dem Namen eines Secrets. Gmail über
  eigene OAuth-Anmeldung erscheint nur, wenn kein Gmail-Connector eingerichtet ist.
  Für IMAP füllt die Adresse die Server aus den bekannten Voreinstellungen vor.

### 6.7 Zustände

Jede Ansicht hat Leer, Laden (Platzhalterzeilen) und Fehler mit Ursache und nächstem
Schritt, mit den Texten aus DESIGN.md §9.5. Ohne Konten führt die Startseite zu „Konto
verbinden“ statt zu Schnellaktionen.

## 7. Backend

### 7.0 Was die Studio-Connectoren können (abgefragt 2026-11-13)

Im Workspace sind die Connectoren `gmail` und `outlook` eingerichtet. `outlook` lieferte
beim Abfragen der Werkzeuge einen Fehler; vermutlich ist er nicht angemeldet, das prüft
der Builder. `gmail` bietet:

- `search_threads` (`query`, `includeTrash`, `pageSize`, `pageToken`);
- `get_thread` (`threadId`, `messageFormat`);
- `send_email` und `create_draft` (`to`, `cc`, `bcc`, `subject`, `body`, `htmlBody`,
  `replyToMessageId`, `attachments`), dazu `send_draft` und `list_drafts`;
- `label_message`, `unlabel_message`, `label_thread`, `unlabel_thread`, `list_labels`
  und die Label-Verwaltung.

Folgen für dieses Design:

- Gmail bleibt über den Connector angebunden.
- Archivieren, Papierkorb und Gelesen/Ungelesen laufen über Labels.
- Antworten bleiben über `replyToMessageId` in der Unterhaltung.
- Der Abruf läuft inkrementell über `search_threads` mit `after:` im Suchausdruck.
- Ob `get_thread` mit einem passenden `messageFormat` die Kopfzeilen liefert (für
  `List-Unsubscribe`), prüft der Builder. Wenn nicht, erkennt liam-e Newsletter über
  Absender-Muster, und Abbestellen ist für diese Absender nur über den Link im Newsletter
  möglich (§7.5).

### 7.1 Chat-Streaming

- Neuer Endpunkt `POST /api/v1/chat/stream` (SSE). Ereignisse:
  `status` (Satz wie „Durchsuche 4 Konten …“), `delta` (Text), `mails` (Liste von
  Mail-Verweisen für Karten), `proposal` (Bestätigungskarte), `suggestions` (bis zu drei),
  `done` (ID der gespeicherten Antwort), `error` (Code und Text).
- Tool-Runden dürfen ungestreamt laufen und erzeugen je Werkzeug ein `status`-Ereignis;
  der Antworttext wird mit `chat.stream_async` gestreamt.
- Anhalten: Der Browser bricht die Anfrage ab. Der Server erkennt das, speichert die
  Antwort bis dahin mit dem Kennzeichen „angehalten“ und startet keine weiteren Werkzeuge.
- Der Web-Client liest den Stream mit `fetch` und einem kleinen Parser; die Typen der
  Ereignisse stehen im OpenAPI-Schema, damit der generierte Client sie kennt.
- Der bisherige `POST /api/v1/chat` bleibt als nicht streamender Weg (MCP, Tests).

### 7.2 Modelle

- `GET /api/v1/chat/models`: Chat-Modelle aus der Mistral-API, die Werkzeuge
  unterstützen, mit deutschem Anzeigenamen und einem Satz Beschreibung. Standard bleibt
  `MAIL_CHAT_MODEL`.
- Gewähltes Modell je Unterhaltung in `chat_conversation.model`.
- Für „Kurz gefasst“ ein eigenes, kleines Modell (`MAIL_INSIGHT_MODEL`, Standard
  `mistral-small-latest`).

### 7.3 Vorschläge

- Der Entwurf wird zum allgemeinen Vorschlag: `chat_message` mit Rolle `proposal` und
  `proposal_json` (Art, Begründung, Einträge, Status, Ergebnis). Arten: `send` (Entwurf
  senden, antworten, weiterleiten), `archive`, `trash`, `mark_read`, `unsubscribe`.
  Bestehende `draft`-Einträge migrieren auf `proposal` mit Art `send`.
- Der Agent bekommt das Werkzeug `propose_action(kind, message_ids | sender_ids,
  reason)`; `create_draft` bleibt für `send`. Lesende Werkzeuge bleiben frei.
- `POST /api/v1/chat/proposals/{id}/confirm` mit den ausgewählten Einträgen führt aus und
  liefert das Ergebnis samt Rückgängig-Kennung, wo es eine gibt.
  `.../cancel` verwirft. Es gibt nie zwei offene Vorschläge in einer Unterhaltung; ein
  neuer schließt den alten als verworfen.
- Antworten und Weiterleiten sind echte Antworten:
  - SMTP mit `In-Reply-To` und `References`;
  - Gmail-Connector über `replyToMessageId`;
  - Graph über `createReply` bzw. `createForward`.

  Der Entwurf kennt An, Cc und „Allen antworten“. Die ursprüngliche Mail steht als Zitat
  darunter („Am 13.11. um 08:57 schrieb …:“). Die Karte zeigt Empfänger, Betreff und Text
  und lässt den Text vor dem Bestätigen bearbeiten.
- Neue Werkzeuge für Antworten: `show_mails(message_ids)` erzeugt das Ereignis `mails`,
  `suggest_followups(texts)` das Ereignis `suggestions`.
- Der Systemprompt übernimmt die Ton-Regeln aus DESIGN.md §2 (Pflicht laut §2.8).

### 7.4 Einzelaktionen und „Rückgängig“

- `POST /api/v1/mail/messages/{id}/actions` mit `archive`, `trash`, `mark_read`,
  `mark_unread`, `restore`. Je Anbieter: IMAP (`MOVE`, sonst `COPY` und `\Deleted`,
  Flags), Gmail-API (Labels), Microsoft Graph (verschieben, `isRead`), Gmail-Connector
  über `label_message`/`unlabel_message` (`INBOX`, `UNREAD`, `TRASH`; ob `TRASH` sich so
  setzen lässt, prüft der Builder gegen den Connector).
- Der lokale Index wird sofort angepasst; schlägt der Anbieter fehl, wird zurückgesetzt
  und ein Fehler gemeldet.
- Jede ausgeführte Aktion landet in `mail_action` (vorheriger Zustand, Zeitpunkt).
  `POST /api/v1/mail/actions/{id}/undo` stellt ihn wieder her, 24 Stunden lang.
- Abbestellen ist nicht rückgängig zu machen; die Karte sagt das.

### 7.5 Newsletter und Abbestellen

- Beim Abruf werden `List-Unsubscribe` und `List-Unsubscribe-Post` gespeichert.
- Werkzeug `find_newsletters()`: Absender mit Abmeldekopf, je Absender Zahl der Mails,
  Zahl ungelesen und Datum der jüngsten gelesenen Mail (daraus „nie geöffnet“ bzw.
  „zuletzt geöffnet im Mai“). Das „geöffnet“ ist eine Näherung über das Gelesen-Flag.
- Ausführung von `unsubscribe` je Absender: One-Click nach RFC 8058, wenn
  `List-Unsubscribe-Post` und eine `https`-Adresse vorliegen; sonst `mailto` über das
  Konto (die bestätigte Karte gilt als Zustimmung zu dieser Mail); sonst nicht
  automatisch: Die Karte nennt den Absender als „nur über den Link im Newsletter“ und
  bietet den Link zum Öffnen an. Danach werden die Mails des Absenders archiviert.

### 7.6 „Kurz gefasst“ und Fristen

- Tabelle `mail_insight` je Mail: bis zu drei Punkte, Frist (Datum), erwartete Antwort
  (ja/nein), Modell, Zeitpunkt.
- Erzeugt beim ersten Öffnen einer Mail und im Hintergrund nach jedem Abruf für
  ungelesene Mails der letzten 14 Tage, höchstens 50 je Abruf, mit dem kleinen Modell.
- Die Liste zeigt Fristpunkt und Schild nur aus vorhandenen Einträgen. „Priorisieren“
  im Chat nutzt sie und ergänzt fehlende.

### 7.7 Posteingang-API

- `GET /api/v1/mail/messages` mit Cursor (Zeit und ID), Filtern (Konten, ungelesen,
  wichtig, Anhang) und Suche. Antwort enthält Kontofarbe-Index, Fristen aus
  `mail_insight`, Anhangsangaben.
- Suche über Postgres-Volltext (`german`) auf Betreff, Absender und Text.
- `GET /api/v1/mail/summary`: Zahl ungelesen gesamt und je Konto, Stand je Konto, für
  Seitenleiste und Begrüßung.

### 7.8 Abruf

- Inkrementell: IMAP über `UIDVALIDITY` und die letzte UID (bei geänderter `UIDVALIDITY`
  neu aufbauen), Gmail über `historyId`, Graph über `deltaLink`, Connector so weit sein
  Werkzeug es erlaubt. Gelesen-Flags und verschobene Mails werden nachgezogen.
- Anstoßen: regelmäßig im Hintergrund, ohne dass die App offen ist (Owner-Entscheidung
  2026-11-13). Der Worker im API-Prozess stellt alle `MAIL_SYNC_INTERVAL_MINUTES`
  (Standard 5) für jedes aktive Konto einen Abruf ein, dessen letzter Abruf älter ist oder
  fehlt. Konten mit abgelaufener Anmeldung lässt der Takt aus, damit der Anbieter das Konto
  nicht nach wiederholten Fehlversuchen sperrt; „Jetzt abrufen“ und neues Verbinden gehen
  weiter. Studio bietet Apps keine Zeitpläne (Probe), deshalb läuft der Takt im Prozess.
  Zusätzlich beim Öffnen der App, wenn der letzte Abruf älter als 10 Minuten ist (etwa nach
  einem Neustart), und über „Jetzt abrufen“ je Konto oder für alle. Die Oberfläche fragt den
  Zustand ab („Wird abgerufen …“).
- Hintergrundarbeit (Abruf, „Kurz gefasst“) läuft als Zeilen in einer Tabelle `mail_job`.
  Ein Worker im API-Prozess holt sie mit `FOR UPDATE SKIP LOCKED`. Das hält auch bei
  mehreren Instanzen oder einem Neustart, ohne dass doppelt abgerufen wird. „Nie zwei
  offene Vorschläge je Unterhaltung“ sichert ein partieller Unique-Index.

### 7.9 Konten

- OAuth-Rücksprung leitet auf `/accounts?connected=<id>` bzw. `?error=<code>` weiter
  statt JSON zu liefern. „Erneut anmelden“ nutzt denselben Weg für ein bestehendes Konto.
- `PATCH /api/v1/mail/accounts/{id}` für den Anzeigenamen.
- Zustand je Konto (`ok`, `syncing`, `auth_expired`, `error` mit Ursache) aus
  `mail_sync_state`.

### 7.10 Datenmodell

Neue Spalten und Tabellen, je mit Migration über `db:revision`:

- `mail_message`: `list_unsubscribe`, `list_unsubscribe_post`, `has_attachments`,
  `attachments_json`, `is_flagged`, Volltextindex.
- `mail_insight` (neu), `mail_action` (neu).
- `chat_conversation`: `model`.
- `chat_message`: Rolle `proposal`, `proposal_json`, Kennzeichen `stopped`; Migration der
  `draft`-Einträge.

## 8. Sicherheit

| Nr. | Befund | Behebung |
|---|---|---|
| S1 | IMAP und SMTP nutzen TLS ohne Zertifikatsprüfung (`sync.py:105`, `service.py:110`, `send.py:41/43`); IMAP ohne TLS ist wählbar. | `ssl.create_default_context()` für `IMAP4_SSL`, `SMTP_SSL` und `starttls()`. Unverschlüsseltes IMAP entfällt; nur TLS oder STARTTLS. |
| S2 | `POST /api/v1/mail/connectors/{name}/tools/{tool}` (`mail_connector_call_tool`) ruft jedes Connector-Werkzeug auf, auch Senden, ohne Bestätigung. | Endpunkt entfernen. Connector-Werkzeuge nur intern mit fester Liste lesender Werkzeuge; Senden nur über den Bestätigungsweg. |
| S3 | `password_secret` löst ein beliebiges Workspace-Secret auf und meldet sich damit an einem frei wählbaren Server an. So ließe sich jedes Secret abgreifen, auch `mail_token_encryption_key`. Auch ein erlaubtes App-Passwort ginge an einen fremden Server mit gültigem Zertifikat, und freie Hosts erlauben ein Abtasten interner Ports. | Nur Secret-Namen nach dem Muster `*-app-password` zulassen, die eigenen Secrets der App immer ablehnen. IMAP- und SMTP-Server nur aus den bekannten Voreinstellungen zur Domain der Adresse oder aus der Einstellung `MAIL_IMAP_ALLOWED_HOSTS`, die der Owner in Studio pflegt, nie frei über die API. Keine privaten oder Loopback-Adressen. Das gilt auch beim späteren Abruf und Versand. |
| S4 | Bestätigen scheitert für Connector-Konten: `confirm.py` lädt Zugangsdaten, die es dort nicht gibt. | Für Connector-Konten keine Zugangsdaten laden; Senden über das Werkzeug des Connectors. |
| S5 | Jede Operation ist in Studio ein MCP-Tool. Ein Agent dort könnte Vorschläge bestätigen, Aktionen ausführen oder Konten verbinden, ohne dass der Owner etwas sieht. | Klären, ob Studio einzelne Operationen vom MCP ausnehmen kann. Wenn ja: alle verändernden Operationen ausnehmen. Wenn nein: dem Owner vorlegen, bevor der Plan weitergeht (§11). |
| S6 | Abbestellen ruft Adressen aus fremden Mails vom Server aus auf (SSRF). | Nur `https`, keine privaten, Loopback- oder Link-Local-Adressen (auch nach DNS-Auflösung und bei Weiterleitungen), Zeitlimit, keine Antwort an den Browser durchreichen. |
| S7 | Mailinhalte sind fremde Daten und können Anweisungen an den Agenten enthalten. | Lesende Werkzeuge liefern Inhalte als Daten; verändernde Schritte gehen nur über Karten. Der Systemprompt sagt das ausdrücklich. Oberfläche zeigt Mailtext als Text. |

Weiter gilt: keine Secrets, Tokens oder Mailinhalte in Logs; Fehlermeldungen an den
Browser ohne Ausnahmetexte der Anbieter, die Adressen oder Tokens enthalten könnten.

## 9. Tests und Abnahme

- API: pytest je Endpunkt mit gemockten Anbietern; Negativfälle für S1 bis S6
  (ungeprüftes Zertifikat abgelehnt, fremdes Secret abgelehnt, private Adresse beim
  Abbestellen abgelehnt, Bestätigen ohne offenen Vorschlag 409).
- Accessors und Migrationen: die Live-PG-Suiten (`db:test-pg-contract`).
- Agent: Werkzeugschleife mit aufgezeichneten Modellantworten; Prüfung, dass kein Weg
  ohne Karte verändert oder sendet.
- Web: `bun test` für Bausteine, Stream-Parser, Puffer des Streamings, Texte mit
  Pluralformen, Kontrast-Tabelle aus DESIGN.md §3 (automatisch, wie dort angekündigt).
- Sichtprüfung: Screenshots der Ansichten bei 390, 834, 1280 und 1440 px, hell und
  dunkel, gegen die Screens auf dem Canvas.
- Vor jedem Commit `bun run check` und die betroffenen Suiten.

## 10. Lieferung

Ein Branch, ein PR, Commits je Bereich in dieser Reihenfolge:

1. Sicherheit S1 bis S4 und S6 (unabhängig von der Oberfläche, zuerst).
2. Datenmodell und Migrationen.
3. Backend: Abruf, Posteingang-API, Aktionen, Vorschläge, Newsletter, Insights,
   Modelle, Streaming.
4. Web: Tokens, Bausteine, Hülle, dann Chat, Posteingang, Konten.
5. Texte gegen DESIGN.md §2.7 prüfen, Sichtprüfung, Doku (`AGENTS.md` Architektur).

Branch und Basis (Owner, 2026-11-13):

- Der neue Branch geht von `main` ab, der PR geht gegen `main`.
- Der erste Commit übernimmt die bisherige, nicht committete Mail-Arbeit unverändert,
  einschließlich `AGENTS.md`, `DESIGN.md` und diesem Dokument.
- Erst danach folgen die Commits oben. So bleiben die Sicherheitskorrekturen als eigener
  Diff lesbar.

## 11. Offen oder dem Builder überlassen

Die ersten drei Punkte prüft der Plan als erstes, in einer **eigenen Test-App** in Studio
ohne echte Konten (Owner, 2026-11-13). Die echte liam-e-App bleibt bis zum Ende
unberührt.

- **S5 MCP-Ausnahme:** Lässt sich eine Operation vom MCP ausnehmen? Erst Mistral-Doku,
  dann Probe in der Test-App. Kennt Studio keine Ausnahme, entscheidet der Owner, bevor
  die verändernden Endpunkte entstehen.
- **SSE durch das Studio-Gateway:** Probe-Endpunkt in der Test-App, bevor der Chat im
  Backend gebaut wird. Puffert das Gateway, wird der Transport auf Polling des
  Antwortstands festgelegt (§4.2). Die Antwort entsteht dann in einem `mail_job`-artigen
  Auftrag mit gespeichertem Zwischenstand, Anhalten über einen eigenen Endpunkt.
- **Regelmäßiger Abruf und Instanzen:** ob Studio Zeitpläne bietet, mehrere Instanzen
  startet oder untätige Container anhält. Probe in der Test-App.
- Dem Builder überlassen: Aufteilung der Komponenten in Dateien, Form des Stream-Parsers,
  Platzhalterzeilen, genaue Tastenbelegung über die oben genannte hinaus, Volltext-Details,
  Aufbau der Testdaten.

## 12. Meine Entscheidungen zum Prüfen

Diese Punkte hat der Owner nicht ausdrücklich entschieden:

1. Ansatz A (Design-System übernehmen) und SSE für Streaming.
2. „Kurz gefasst“ im Hintergrund für ungelesene Mails der letzten 14 Tage, höchstens 50
   je Abruf, mit `mistral-small-latest`. Das kostet Modellaufrufe bei jedem Abruf.
3. „Wichtig“ = beim Anbieter markiert oder Frist bzw. erwartete Antwort erkannt.
4. „Rückgängig“ 10 Sekunden sichtbar, 24 Stunden möglich.
5. Abbestellen ohne One-Click und ohne `mailto` geschieht nicht automatisch.
6. Anhänge nur anzeigen, nicht herunterladen; Mails nur als Text.
7. Abruf regelmäßig im Hintergrund alle 5 Minuten (Owner-Entscheidung 2026-11-13), dazu
   beim Öffnen, wenn älter als 10 Minuten, und von Hand.
8. IMAP-Server nur aus Voreinstellungen oder aus `MAIL_IMAP_ALLOWED_HOSTS` (S3). Für einen
   unbekannten Anbieter trägst du den Server dort ein, bevor du das Konto verbindest.
9. Echte Antworten in der Unterhaltung mit Cc und „Allen antworten“ (§7.3).
10. Hintergrundarbeit als Tabellenzeilen statt im Speicher des Prozesses (§7.8).

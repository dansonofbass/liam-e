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
apps/web  (TanStack Start, Port 3001, Route "/")        Browser-UI: /mail, /chat
   │  typisierter hey-api-Client (src/api/generated, generiert — nie per Hand editieren)
   ▼  same-origin /api
apps/api  (FastAPI, Port 3000, Route "/api")            Router-Baum = URL-Baum, Gruppen mit Access-Rule
   │  api/mail/: crypto, connectors, providers, service, sync, send, agent  Domänenlogik
   ▼
packages/py/db   SQLModel-Modelle (drop-in in db/models/) + Accessors (db/accessors/) + Alembic
packages/py/env  Settings-Module (env/<name>.py), Workspace-Secrets via WorkspaceSecret
managed Postgres (Modul in mistral.json)                Mail-Index, Credentials, Chat-Verlauf
```

Datenfluss: `POST /api/v1/mail/accounts/...` verbindet ein Konto (OAuth2-Redirect oder
IMAP-App-Passwort); Credentials landen **Fernet-verschlüsselt** in `mail_credential`.
`POST /api/v1/mail/accounts/{id}/sync` füllt `mail_message`. `POST /api/v1/chat` lässt den
Agenten (`api/mail/agent.py`, Tool-Loop über ein Mistral-Modell) auf dem Index arbeiten;
`create_draft` legt einen Entwurf an, der erst über `POST /api/v1/chat/drafts/{id}/confirm`
wirklich versendet wird.

## Domänenmodell (Tabellen in Postgres)

- `mail_account` — ein verbundenes Konto (provider: `google` | `microsoft` | `imap`, auth_type: `oauth2` | `imap_password`)
- `mail_credential` — verschlüsseltes Payload pro Konto+Art (`oauth2_tokens` | `imap_password`), unique (account_id, kind)
- `mail_message` — synchronisierte Mail: folder, provider_uid, thread_id, subject, sender, recipients_json, snippet, body_text (gekappt), internal_date, flags; unique (account_id, folder, provider_uid)
- `mail_sync_state` — Sync-Cursor/Status je Konto
- `chat_conversation`, `chat_message` — Chat-Verlauf; role `draft` + `draft_json` für zu bestätigende Entwürfe

## Stack & Befehle

- **Python:** `uv`-Workspace (Root `pyproject.toml`), FastAPI + SQLModel/Alembic. Tests: `bash tools/uv.sh run --no-sync pytest <pfad>`; Live-PG-Suiten: `bunx nx run db:test-pg-contract`
- **TypeScript:** bun 1.4 + Nx + TanStack Start/Router/Query + Tailwind 4, Vite 8
- Wichtigste Kommandos (Root):
  - `bun run install-all` — installiert alles inkl. generierten API-Client (`tools/gen-types.sh`)
  - `bunx nx run api:serve` — API lokal starten; `bun run dev:web` — Web lokal (Port 3001)
  - `bun run build` / `bun run test` / `bun run check` — Nx über alle Projekte
  - `bunx nx run api:gen-openapi` + `bash tools/gen-types.sh` — OpenAPI-Spec + TS-Client neu generieren (nach jeder API-Änderung; `gen-types.sh --check` ist der Drift-Gate)
  - `bunx nx run db:revision --message "..."` — Alembic-Revision autogenerieren; `bunx nx run db:migrate` — anwenden (`heads`, nicht `head`)

## Konventionen

### Python
- **Settings:** neue Settings als eigenes Modul `packages/py/env/src/env/<name>.py` (`class Env(BaseEnv)` + `env = Env()`); jeder Name **leer** in der Root-`.env.example` deklarieren. Secrets mit `Annotated[str | None, WorkspaceSecret()] = None` markieren (in Studio aus den Workspace-Secrets, lokal aus `.env`).
- **DB:** ein Model pro Datei in `packages/py/db/src/db/models/<table>.py` (drop-in, Loader entdeckt automatisch; **keine Cross-Table-Foreign-Keys**, Referenzen als String-Spalten), ein Accessor-Modul pro Tabelle in `db/accessors/` — ORM-Queries nur in Accessors. Migrationen: eine Branch pro Owner, `branch_labels` gesetzt, `down_revision = None` an der Wurzel.
- **Router:** Verzeichnisbaum = URL-Baum unter `apps/api/src/api/routers/`. Jedes Modul mit `router` serviert; jedes Paket braucht eine Access-Rule (`dependencies` in der `__init__.py`, `()` = anonym — nie weglassen, sonst Import-Fehler). `operation_id` ist eindeutig und wird in Studio zum MCP-Toolnamen. `[name]` in Datei/Verzeichnis = Pfadparameter `{name}`; `route.py` = Index.
- **Code/Kommentare/Docstrings auf Englisch** (Repo-Konvention); **UI-Texte auf Deutsch**.
- nie Secrets loggen oder committen; `.env` ist gitignored.

### TypeScript (apps/web)
- TanStack Router: eine Datei pro Route unter `src/routes/`; Landing-Page über `staticData: { landing: <rank> }` claimen. Nach neuen Routen `bunx nx run web:gen-routes`.
- API-Zugriff nur über den generierten Client (`src/api/generated/`, git-committed, nie manuell editieren) + `unwrap`/`dataOr404` aus `src/api/unwrap.ts`; `VITE_API_URL` konfiguriert die Base-URL.
- Styling mit Tailwind 4; Pfade/englische Literale mit `// i18n-exempt` markieren. Tests: `bun test` (jsdom-Setup in `src/test/setup.js`).

## Sicherheit
- OAuth-Client-Secrets und `MAIL_TOKEN_ENCRYPTION_KEY` sind **Workspace-Secrets** (`WorkspaceSecret`), nie im Code; lokal nur in `.env`. **Secret-Namen in Mistral Studio sind lowercase** — die Auflösung ist case-insensitiv: Secret `mail_token_encryption_key` füllt `MAIL_TOKEN_ENCRYPTION_KEY` (siehe Docstring von `env/_mistral_secrets.py`).
- **Pro IMAP-Konto (iCloud, Yahoo, …) genau ein eigenes Workspace-Secret** mit dem App-Passwort, z.B. `yahoo-app-password`, `icloud-app-password` (lowercase). Beim Connect wird statt des Passworts der Secret-Name übergeben (`password_secret`); die App löst ihn zur Laufzeit über `GET /v1/secrets/values` auf (`api/mail/secrets.py`) und speichert in `mail_credential` nur die **Referenz** (verschlüsselt), nie den Wert — Rotation in Studio wirkt ohne Reconnect.
- Mail-Credentials werden vor dem Schreiben in `mail_credential` mit Fernet verschlüsselt (`api/mail/crypto.py`); der Key wird nie persistiert.
- Der Agent sendet **nie ohne Bestätigung**: `create_draft` erzeugt einen `draft`-Eintrag, erst `POST .../drafts/{id}/confirm` verschickt (SMTP/Gmail-API/Graph).
- CORS bleibt auf die eigene Origin beschränkt (`CORS_ORIGIN`).

## Arbeitsweise für Agents
- Vor jeder Arbeit an der Oberfläche (`apps/web`, Texte, auch Antworttexte des Assistenten) `DESIGN.md` lesen; sie regelt Tokens, Bausteine, Responsive-Verhalten und wie Texte klingen.
- Minimale Diffs, bestehende Patterns kopieren (siehe Modul-Docstrings — sie dokumentieren die Konventionen jeweils lokal).
- Nach API-Änderungen immer `gen-types` laufen lassen und `apps/api/openapi.json` + `apps/web/src/api/generated` mit committen.
- Änderungen an Tabellen immer mit Migration (`db:revision` + `db:migrate`), nie von Hand editierte `versions/`-Dateien.
- Vor dem Commit: `bun run check` (baut alles und prüft den generierten Client) und die betroffenen Test-Suiten laufen lassen.

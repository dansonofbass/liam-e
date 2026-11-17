# Lokale Entwicklung

Diese Anleitung startet die Hauptanwendung aus [`apps/api`](../apps/api) und [`apps/web`](../apps/web) mit einer separaten Testdatenbank. Mit den synthetischen Beispieldaten lassen sich Posteingang und gespeicherte Chatverläufe ohne Mailkonto oder Mistral-Zugang ansehen. Die [minimale Chat-Demo](../apps/chat-app/README.md) hat ihren eigenen Einstieg und wird dafür nicht gestartet.

## Voraussetzungen und Installation

- Bash, Bun **1.4.0**, Node.js **24** und `uv` **0.11.17** entsprechen den Werkzeugversionen der [CI](../.github/workflows/ci.yml). Das Installationsskript verlangt die in [`package.json`](../package.json) festgelegte Bun-Version. `uv` verwendet Python **3.14** aus [`.python-version`](../.python-version) und kann den Interpreter bei Bedarf installieren.
- Eine lokal erreichbare PostgreSQL-Instanz. Das Beispiel verwendet dasselbe PostgreSQL-16-Image mit pgvector wie die CI und setzt Podman voraus. Mit Docker funktionieren dieselben Containerbefehle.

Im Repository-Root installiert [`tools/install.sh`](../tools/install.sh) beide Workspaces und erzeugt den typisierten API-Client.

```bash
bun run install-all
```

Für einen CI-nahen Checkout mit unveränderten Lockfiles und vorhandenem API-Client verwendet der [Workflow](../.github/workflows/ci.yml) die folgenden Befehle. Damit bleibt ein veralteter API-Client für `bun run check` erkennbar.

```bash
bash tools/uv.sh sync --all-packages --frozen
bun install --frozen-lockfile
```

## Konfiguration

Die [Root-`.env.example`](../.env.example) deklariert ausschließlich die Namen der eigenen Einstellungen, für die keine Studio-Capability zuständig ist. Die Anwendung lädt diese Datei nicht. Der Studio-CLI-Scaffold erzeugt eine ignorierte Root-`.env` aus den `envVars` der installierten Capabilities. Für einen vorhandenen Checkout genügt eine selbst angelegte Root-`.env` mit den benötigten Abweichungen oder die direkte Übergabe als Umgebungsvariablen. Python liest die Root-`.env` unabhängig vom Aufrufverzeichnis. Prozessvariablen haben Vorrang. Leere Werte behandelt der Settings-Loader als ungesetzt, sodass die Defaults in den Settings-Modulen greifen. Siehe [Settings-Loader](../packages/py/env/src/env/_base.py), [Datenbank](../packages/py/env/src/env/db.py) und [Mail](../packages/py/env/src/env/mail.py).

Für die Oberfläche gibt es eine eigene [`apps/web/.env.example`](../apps/web/.env.example) mit einem konkreten Wert. In einem frischen Checkout lässt sie sich nach `apps/web/.env` kopieren. Alternativ setze `VITE_API_URL=http://127.0.0.1:3000` beim Webstart wie unten. Der Wert bezeichnet den API-Ursprung ohne `/api`, weil der generierte Client diesen Pfad bereits enthält. Öffne das Web über `http://localhost:3001`, den voreingestellten `CORS_ORIGIN` der API. Bei einem anderen Browser-Ursprung setze `CORS_ORIGIN` passend. `APP_NAME=liam-e` in der Root-`.env` setzt den Anzeigenamen. Siehe [Web-Konfiguration](../apps/web/vite.config.ts) und [CORS-Setting](../packages/py/env/src/env/api.py).

## Datenbank anlegen und migrieren

Verwende für die Beispiele eine frische Datenbank. Das gezeigte Passwort gehört ausschließlich zur Wegwerf-Instanz auf Loopback. Der Container bleibt für die Dauer der Sitzung aktiv.

```bash
podman run --rm -d --name liam-e-dev-db \
  -p 127.0.0.1:55432:5432 \
  -e POSTGRES_PASSWORD=test-only -e POSTGRES_DB=liam_e_dev \
  pgvector/pgvector:0.8.0-pg16

podman exec liam-e-dev-db pg_isready -h 127.0.0.1 -U postgres -d liam_e_dev
```

Sobald `pg_isready` „accepting connections“ meldet, setze die URL und migriere. `DATABASE_URL` hat Vorrang vor `POSTGRES_*`, aus denen Studio die Datenbankverbindung bereitstellt. Der Nx-Befehl führt `alembic upgrade heads` aus und berücksichtigt alle Migrationszweige. Verwende für Migration, Seed und API dieselbe URL. Dazu kannst du die Variable für alle betreffenden Terminals in der Root-`.env` setzen. Siehe [DB-Settings](../packages/py/env/src/env/db.py), [Migrationsbefehl](../tools/db.sh) und [Alembic-Konfiguration](../packages/py/db/src/db/migrations/env.py).

```bash
export DATABASE_URL='postgresql+asyncpg://postgres:test-only@127.0.0.1:55432/liam_e_dev'
bunx nx run db:migrate
```

## Beispieldaten und Start

Fülle die migrierte Datenbank mit den Beispieldaten. Beim Wiederholen ersetzt das Skript die eigenen Beispielzeilen samt zugehörigen Daten. Es akzeptiert ausschließlich die Datenbank-Hosts `localhost`, `127.0.0.1` und `::1` ohne Host-Override in der URL. Siehe [Seed-Skript](../apps/api/src/api/mail/dev_seed.py).

```bash
bash tools/uv.sh run --no-sync python -m api.mail.dev_seed
MAIL_WORKER_ENABLED=false MISTRAL_SECRETS_ENABLED=false TELEMETRY_ENABLED=false bunx nx run api:serve
```

Lasse für diesen Test Mistral- und Provider-Zugangsdaten ungesetzt. Die API lauscht standardmäßig auf `127.0.0.1:3000` und lädt bei Codeänderungen neu. Prüfe in einem zweiten Terminal zuerst die API, dann starte die Oberfläche.

```bash
curl -fsS http://127.0.0.1:3000/api/health
curl -fsS http://127.0.0.1:3000/api/health/ready
VITE_API_URL=http://127.0.0.1:3000 bun run dev:web
```

`/api/health` antwortet auch bei einer gestörten Abhängigkeit mit HTTP 200. Prüfe `status: "ok"` und `deps.database.reachable: true` im JSON. `/api/health/ready` meldet HTTP 503, wenn die API keine Anfragen übernehmen soll. In der Testkonfiguration kann Mistral als `configured: false` erscheinen. Siehe [API-Entwicklungsstart](../apps/api/src/api/dev.py) und [Health-Routen](../apps/api/src/api/routers/api/internal/health.py).

Öffne `http://localhost:3001/mail` für den Posteingang oder `http://localhost:3001/` für den Chat. Beispielkonten führen Mailaktionen nur im Index aus. Der Abruf überspringt diese Konten, Versand und Abbestellung sind gesperrt und fehlende Mail-Kurzfassungen werden für sie nicht nachträglich erzeugt. Neue KI-Antworten benötigen Mistral-Zugang. Siehe [Abruf](../apps/api/src/api/mail/sync.py), [Aktionen](../apps/api/src/api/mail/actions.py), [Versand](../apps/api/src/api/mail/send.py), [Abbestellung](../apps/api/src/api/mail/newsletters.py) und [Kurzfassungen](../apps/api/src/api/mail/insights.py).

Zum Beenden API und Web mit `Ctrl+C` stoppen, anschließend `podman stop liam-e-dev-db` ausführen. Der mit `--rm` gestartete Container wird samt ungebundenem Datenspeicher entfernt.

## Prüfungen

Die Befehle und Anforderungen für Änderungen stehen unter [Mitarbeit](../CONTRIBUTING.md). Die PostgreSQL-Vertragstests laufen nur mit `RUN_PG_CONTRACT=1` und einer Testdatenbankverbindung, deren Rolle weitere temporäre Datenbanken anlegen und löschen darf. Die [CI](../.github/workflows/ci.yml) verwendet dafür einen separaten PostgreSQL-Dienst. Provider- und Studio-Einrichtung behandelt [Provider und Betrieb](provider-und-betrieb.md).

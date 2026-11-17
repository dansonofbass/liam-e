# Mitarbeit

Verbindlich sind [AGENTS.md](AGENTS.md) für Architektur, Konventionen und Sicherheit und
[DESIGN.md](DESIGN.md) für Oberfläche und Texte. Diese Datei fasst zusammen, was für Issues und
Pull Requests gilt. Bitte vor größerer Arbeit ein Issue öffnen.

## Einrichtung und Prüfungen

Die [Anleitung zur lokalen Entwicklung](docs/lokale-entwicklung.md) beschreibt
Installation, Datenbank, Startreihenfolge und den Seed-Modus.

```bash
bun run check                # Build, Typprüfung der Oberfläche, Drift-Prüfung des Clients
bunx nx run web:test
bash tools/uv.sh run --no-sync pytest tests apps/api/tests packages/py -q
RUN_PG_CONTRACT=1 bunx nx run db:test-pg-contract   # braucht Postgres mit pgvector
```

Die Tests brauchen weder Provider-Zugang noch Mistral-Credentials.

## Regeln in Kürze

- Code, Kommentare, Docstrings und Commit-Nachrichten auf Englisch, Texte der Oberfläche auf
  Deutsch über den Textkatalog.
- Nach API-Änderungen OpenAPI-Spezifikation und Client neu erzeugen und mit committen.
  Tabellenänderungen nur mit generierter Migration.
- Der Agent verändert oder versendet nie ohne bestätigte Vorschlagskarte. Neue verändernde
  Operationen gehören in die MCP-Inventur (`apps/api/tests/test_mcp_exposure.py`).
- Nur synthetische Testdaten. Keine Zugangsdaten, echten Mails, Mistral-IDs oder lokalen Pfade in
  Dateien, Issues, PRs, Commit-Nachrichten und Logs.

## Issues

Issues entstehen über die Formulare in [`.github/ISSUE_TEMPLATE/`](.github/ISSUE_TEMPLATE/):
Fehler, Änderung, Evaluation und Teilauftrag. Jedes fragt nach Abnahmekriterien und danach, wie
sie zu prüfen sind, damit eine Person oder ein Coding-Agent das Issue umsetzen und ein Reviewer
es nachprüfen kann. Eine vermutete Schwachstelle kommt nicht in ein Issue, siehe
[SECURITY.md](SECURITY.md).

## Pull Requests

Pull Requests folgen [`.github/pull_request_template.md`](.github/pull_request_template.md).

- Eine Aufgabe ergibt einen Branch und einen PR. Umfasst sie mehrere Issues, bekommt jedes eigene
  Commits und ein eigenes Schließwort (`Closes #12. Closes #13.`).
- Beschreiben, was geprüft wurde und wie, mit den tatsächlich ausgeführten Befehlen. Tests mit
  Fakes belegen kein Live-Verhalten in Studio, bei Providern oder auf Geräten; was nicht geprüft
  wurde, steht ausdrücklich da.
- Die CI (`check`, `web-test`, `pytest`, `pg-contract`, `secrets`) muss grün sein.

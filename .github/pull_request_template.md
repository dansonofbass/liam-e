<!--
Jeden Abschnitt ausfüllen; "keine" schreiben, wo nichts zutrifft. Geprüfte Tatsachen nennen, keine
Absichten. Nie Zugangsdaten, Tokens, echte Mails oder Termine, Mistral-IDs, lokale Pfade oder rohe
Providerantworten eintragen.
-->

<!-- Ein Schließwort je Issue, z. B. "Closes #12. Closes #13." -->
Closes #

## Zusammenfassung

<!-- Was sich geändert hat und warum, nach beobachtbarem Verhalten. Bei mehreren Issues je Issue ein Abschnitt "### #12: <Titel>". -->

## Prüfung

<!-- Tatsächlich ausgeführte Befehle mit Ergebnis (Exit-Code, Zähler). Nicht Ausgeführtes nennen. Tests mit Fakes belegen kein Verhalten in Studio, bei Providern oder auf Geräten. -->

- `bun run check`:
- `bunx nx run web:test`:
- `bash tools/uv.sh run --no-sync pytest tests apps/api/tests packages/py -q`:
- `RUN_PG_CONTRACT=1 bunx nx run db:test-pg-contract`:
- `git diff --check`:
- Gezielte oder Live-Prüfungen:

## Verträge

- [ ] API geändert: `apps/api/openapi.json` und `apps/web/src/api/generated/` neu erzeugt und committet (`bash tools/gen-types.sh --check` grün)
- [ ] Tabellen geändert: Migration mit `bunx nx run db:revision` erzeugt, nicht von Hand geschrieben
- [ ] Neue verändernde Operation in `MUTATING_OPERATIONS` (`apps/api/tests/test_mcp_exposure.py`) und in der Endpunkt-Tabelle von AGENTS.md
- [ ] Der Agent verändert oder versendet weiterhin nur nach bestätigter Vorschlagskarte
- [ ] Texte der Oberfläche auf Deutsch im Textkatalog, nach DESIGN.md; Code, Kommentare und Commits auf Englisch

## Risiko und Rücknahme

<!-- Was brechen könnte, für wen, und wie es sich zurücknehmen lässt (Migration, Daten). -->

## Review und Beteiligung von Agents

<!-- Autor (Mensch oder Agent mit Modell). Unabhängige Reviews: Prüfer, Modellfamilie, Ergebnis, behobene und begründet abgelehnte Befunde. -->

- Erstellt von:
- Unabhängiges Review:

- [ ] Dieser PR enthält keine Zugangsdaten, echten Mail- oder Kalenderinhalte, Mistral-IDs, lokalen Pfade oder rohen Providerantworten.

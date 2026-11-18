# Studio-Promptversionen lesen (2026-11-18, #37 Phase 1)

Ergebnis: **Workspace-Nachweis offen**. Die Prompt-Registry ist mit dem Schlüssel der App
erreichbar, zeigt ihm aber keinen einzigen Prompt. Für einen festgelegten synthetischen Testprompt
fehlt noch die Freigabe. Ohne diesen Nachweis bleibt der Import abgeschaltet. Die lokalen Vorlagen
funktionieren unabhängig davon vollständig.

## Schnittstelle (Doku und SDK)

- Mistral Python SDK `mistralai 3.7.0`, Namensraum `client.beta.prompts` (Beta). Die Doku nennt
  API und SDKs für Prompts und Skills ebenfalls Beta. Mit welcher SDK-Version sie kamen, ist nicht
  dokumentiert.
- REST unter `/v2/prompts`:
  - `GET /v2/prompts` (`pageSize`, `pageToken`, `alias`, `fields`, Sortierung) liefert
    `{data, nextPageToken}`.
  - `GET /v2/prompts/{prompt_id}` liefert ohne `version` und ohne `alias` die neueste Version.
  - `GET /v2/prompts/{prompt_id}/versions` liefert die Versionsliste.
  - `GET /v2/prompts/{prompt_id}/versions/{version}` liefert genau eine feste Version.
  - Schreiboperationen (`POST`, `PATCH`, `DELETE`) gibt es ebenfalls. Die Probe ruft sie nie auf.
- Ein Prompt trägt `id`, `name`, `title`, `description`, `version`, `latestVersion`, `aliases`,
  `sharingScope` (`private`, `workspace`), `createdAt`, `updatedAt`, `createdBy` und `definition`.
  `definition` enthält `content` (Text) und `variables` (Liste mit `name`). Platzhalter haben die
  Form `{{name}}`. Der Server setzt nichts ein.
- Aliasse sind frei vergebene Namen. `production` oder `staging` sind nicht reserviert. Ohne Angabe
  gilt die neueste Version. Ein Import muss deshalb immer eine Versionsnummer nennen.
- Welche Schlüsselarten lesen dürfen und welche Fehler bei fehlender Berechtigung kommen, steht
  nicht in der Doku.

Quellen: https://docs.mistral.ai/api/endpoint/beta/prompts,
https://docs.mistral.ai/studio/prompts-and-skills/overview und die SDK-Doku `docs/sdks/betaprompts`
im Repository `mistralai/client-python`.

## Matrix (ausgeführt am 18.11.2026)

Lauf: `bash tools/uv.sh run --no-sync python tools/studio_prompt_probe.py --live`, nur `GET`, mit dem
lokalen Schlüssel der App über `utils.mistral` (lokal `MISTRAL_API_KEY`).

| Fall | Ergebnis |
| --- | --- |
| `GET /v2/prompts?pageSize=1` | 200, Schlüssel `data` und `nextPageToken`, 0 Einträge, keine Folgeseite |
| unbekannte Prompt-ID | 404 |
| unbekannte Prompt-ID, Version 1 | 404 |
| ungültiger Schlüssel | 401 |
| Client-Timeout 1 ms | Verbindungs-Timeout, sauber abgefangen |
| feste Version eines Testprompts | **offen**: Es gibt keinen freigegebenen synthetischen Testprompt |
| private gegenüber geteilter Sichtbarkeit | **offen**, aus demselben Grund |
| Schlüssel der deployten App (Service-Account-Token aus `MISTRAL_SA_TOKEN_PATH`) | **offen**: nur in Studio vorhanden, lokal nicht prüfbar |

Die leere Liste lässt zwei Deutungen zu. Entweder gibt es im Workspace keine Prompts, oder der
Schlüssel sieht private Prompts anderer Personen nicht. Die Probe unterscheidet das bewusst nicht,
denn dafür müsste sie fremde Inhalte auflisten.

## Was für den Nachweis noch fehlt

1. Der Owner legt in Studio einen synthetischen Testprompt an, etwa mit dem Inhalt
   „Antworte kurz.“ und einer Variablen, einmal mit Sichtbarkeit `private` und einmal mit
   `workspace`, und gibt ID und Versionsnummer für die Probe frei.
2. Danach `tools/studio_prompt_probe.py --live --prompt-id <id> --version <n>` lokal ausführen.
   Das Werkzeug gibt nur Schlüsselnamen, Sichtbarkeit, die Zahl der Variablen und die Textlänge aus.
3. Dieselbe Abfrage mit dem Service-Account-Token der deployten App prüfen, zum Beispiel über eine
   kurzlebige lesende Proberoute in einer Test-App. Erst wenn beide Schlüssel die feste Version lesen
   können, ist Phase 1 bestanden und Phase 2 (Import als lokale Kopie) freigegeben.

Die Probe legt keine Prompts an und teilt keine. Sie gibt auch keine Zugangsdaten an andere Werkzeuge
weiter.

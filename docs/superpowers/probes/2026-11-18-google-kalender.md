# Google-Kalender über den Studio-Connector (2026-11-18)

Lesende Probe für #19. Die Live-Ergebnisse stammen aus der vorgegebenen, redigierten
Controller-Probe vom 18.11.2026. In dieser Umsetzung wurde kein Anbieter aufgerufen.
Alle eingecheckten Seiten sind frei erfunden; sie enthalten keine übernommenen Termine,
Kalenderkennungen oder Kontodaten. Die Offline-Tests belegen die Verarbeitung dieser
Formate, nicht das Verhalten eines echten Google-Kontos.

## Entscheidung

Der Studio-Connector `google_calendar` ist der vorgesehene **Lesepfad** für Google-Kalender.
Ein eigener OAuth-Fallback ist nicht vorgesehen. Die Einbindung in Agenda, Quellenverwaltung
und Worker gehört zu #21 und wird durch dieses Probe-Werkzeug noch nicht freigeschaltet.

Schreiben bleibt gesperrt: **#23 — BLOCKED: `calendar_write_capability_missing`**.
Es fehlen sowohl eine Versionsvorbedingung für Änderungen und Löschen als auch eine
idempotente Kennung für die Anlage. Ein Bestätigungsdialog allein ersetzt diese nicht.
Das Probe-Werkzeug kann ausschließlich `list_calendars` und `list_events` aufrufen.
Die bestehenden Mail-Allowlisten bleiben unverändert.

## Inventar und Verträge

- `GET /v1/connectors` nennt `google_calendar` und `outlook_calendar`.
  Die Werkzeugliste von `outlook_calendar` antwortete mit HTTP 401. Daraus folgt nichts
  über einen getrennten oder abgelaufenen Google-Connector.
- Werkzeuge von `google_calendar`: `list_events`, `get_event`, `list_calendars`,
  `create_event`, `update_event`, `delete_event`, `respond_to_event`.
- `list_calendars`: `pageSize` 1–250 (Standard 100), optional `pageToken`.
  Ausgabe: `calendars` mit `id`, `summary`, `description`, `timeZone`, dazu
  `nextPageToken`. Kein `accessRole` und keine `primary`-Markierung je Eintrag.
  Live wurden fünf Kalender auf einer Seite beobachtet.
- `list_events`: optional `calendarId` (ohne Angabe: Hauptkalender), `startTime`,
  `endTime`, `pageSize` 1–250 (Standard 100), `pageToken`, `timeZone`, `orderBy`,
  `fullText`, `eventType` als Liste. Alle Filter müssen bei Folgeseiten gleich bleiben.
  `startTime` ist die exklusive Untergrenze für das Terminende; `endTime` die exklusive
  Obergrenze für den Terminbeginn. Zeiten sind ISO 8601.
- Eine leere `eventType`-Auswahl liefert laut Werkzeugbeschreibung nur `DEFAULT`,
  `OUT_OF_OFFICE`, `FOCUS_TIME` und `FROM_GMAIL`. Live wurde auch `BIRTHDAY` gesehen.
  Ohne gesonderte Probe lässt sich daraus keine Vollständigkeit über alle denkbaren
  Google-Terminarten ableiten. Die Probe setzt keinen zusätzlichen Typfilter.
- Oberste Felder der Terminliste: `summary`, `description`, `updated`, `timeZone`,
  `accessRole`, `defaultReminders`, `events`, `nextPageToken`.
  `accessRole` wurde als `owner` und `reader` beobachtet; die Kalenderliste allein
  erlaubt also keine Rechteprüfung je Kalender.
- Terminfelder: `id`, `status`, `htmlLink`, `created`, `updated`, `summary`,
  `description`, `location`, `creator`, `organizer`, `start`, `end`, `recurrence`,
  `recurringEventId`, `originalStartTime`, `transparency`, `visibility`, `attendees`,
  `eventType`, `conferenceUrl`, `colorId`, `overrideReminders`, `attachments`,
  `guestPermissions`, `workingLocationProperties`. Viele Werte dürfen null sein.
  Adressobjekte tragen `email`, `displayName`, `self`.
- Zeitobjekte tragen `date`, `dateTime`, `timeZone`, `eventTimeZone`.
  Ganztag nutzt `date` und ein exklusives Enddatum. Zeitgebundene Termine liefern
  `dateTime` mit Offset und meist eine IANA-Zone in `start.timeZone`.
  `created`/`updated` wurden mit Millisekunden und `Z` beobachtet.
- Serien werden bereits als datierte Instanzen geliefert. Ihre `id` enthält typischerweise
  eine Serienkennung plus Datum oder UTC-Zeit; die Anwendung darf diese Kennung nicht
  selbst zerlegen. `recurringEventId` verbindet die Instanz mit der Serie.
  `get_event` auf die Serienkennung lieferte eine RRULE-Liste. Die Probe ruft dieses
  Werkzeug bewusst nicht auf: Für den begrenzten Lesesnapshot reichen expandierte Instanzen.
- `update_event` und `delete_event` nehmen Termin-/Kalenderkennung und Felder, aber kein
  etag, If-Match oder sequence. `create_event` nimmt weder eine eigene Termin-ID noch
  eine Request-ID. Schreibaufrufe wurden für diese Umsetzung nicht ausgeführt.

## Fähigkeitsmatrix

„Belegt“ nennt ausdrücklich, ob der Beleg aus der Controller-Probe oder nur aus
synthetischen Tests stammt. Ein vollständig abgearbeitetes Fenster bedeutet nicht,
zwischen mehreren Seiten einen atomaren Stand beim Anbieter gelesen zu haben.

| Fähigkeit | Bewertung | Beleg und Grenze |
|---|---|---|
| Vollständiges Lesen eines Fensters | belegt | Laut Vertrag werden Serien expandiert; alle Folgeseiten müssen gelesen werden. Bezieht sich auf die vom Connector gelieferten Terminarten, nicht auf beliebige zusätzliche Typen. |
| Pagination | belegt | Live: vier Seiten zu 25 hatten dieselbe ID-Menge wie eine Seite zu 250; ein Kalender mit 427 Terminen brauchte zwei Seiten zu 250. Keine doppelten IDs beobachtet. Offline: zwei Seiten und unveränderte Filter geprüft. |
| Serienidentität | belegt | Live: Instanz-ID plus `recurringEventId`; offline zwei Instanzen als ein `Event` mit `schema=google-1` und `recurring=true`. |
| Verschobene Instanzen | belegt | Controller: ID bleibt erhalten. Offline: dieselbe ID und Serienreferenz bei geändertem Beginn. |
| Abgesagte Instanzen | belegt | Controller: `showDeleted` fehlt, abgesagte Instanzen fehlen in der Liste. Nur ein vollständiger Snapshot darf sie aus dem Fenster entfernen. Offline wird außerdem ein ausdrücklich geliefertes `status=cancelled` übersprungen. Die Datenbankersetzung gehört zu #21. |
| Ganztag | belegt | Live: Datum, exklusives Ende, Zone null. Offline: mehrtägig; Ende ≤ Beginn wird auf den Folgetag gesetzt. |
| Zeitzonen und Offset | belegt | Live: Offset und IANA-Zone. Offline: Normalisierung nach UTC; Zone aus Beginn, Liste oder Quellenvorgabe, ungültige Zone wird UTC. |
| DST-Verhalten beim Anbieter | offen | Offline sind Wocheninstanzen vor/nach der Berliner Oktoberumstellung korrekt abgebildet (9 Uhr wird 7 bzw. 8 Uhr UTC). Das belegt nur das Mapping, keine Live-Expansion mehrdeutiger oder fehlender lokaler Zeiten. |
| Rechteprüfung | belegt | `accessRole` steht pro Terminlisting, nicht pro Eintrag von `list_calendars`; `owner` und `reader` beobachtet. Kein Nachweis für weitere Rollen. |
| Snapshotvollständigkeit | belegt | Nichtleeres `nextPageToken` bedeutet immer unvollständig, unabhängig von der Seitengröße. Die Offline-Logik scheitert bei fehlendem `events`, Tokenzyklus, mehr als 40 Seiten oder mehr als 10.000 Terminen; sie liefert dann keinen Teilsnapshot. |
| Atomare Konsistenz über mehrere Seiten | offen | Weder Snapshot-Token noch Versionsgarantie über den gesamten Abruf belegt. |
| Getrennter Google-Connector / HTTP 401 | offen | Nicht live getrennt oder neu verbunden. Das beobachtete Outlook-401 ist dafür kein Beleg. |
| Versionsvorbedingung beim Schreiben | nicht unterstützt | Kein If-Match/etag/sequence in den Werkzeugverträgen. |
| Idempotente Anlage | nicht unterstützt | Keine vorgegebene ID oder Request-ID bei `create_event`. |

## Offline-Werkzeug und Fixtures

```sh
bash tools/uv.sh run --no-sync python tools/calendar_google_probe.py
bash tools/uv.sh run --no-sync pytest apps/api/tests/test_calendar_google_probe.py
```

`apps/api/tests/fixtures/google_calendar/` enthält:

- `calendars_1.json`, `calendars_2.json`: erfundene Kalender über zwei Seiten.
- `events_1.json`, `events_2.json`: mehrtägiger Ganztag, Wochenserie am 18. und 25. Oktober
  in Europe/Berlin (UTC+2/UTC+1), Zeitpunkt ohne Dauer, explizite Absage, Folgetoken.
- `events_moved.json`: eine verschobene Instanz mit unveränderter ID und `originalStartTime`.
- `malformed.json`: absichtlich fehlendes `events` statt einer gültigen leeren Liste.

Erwartet werden vier abgebildete Instanzen und drei Ereignisstämme aus zwei Terminseiten.
Titel, Beschreibungen, Kalendernamen, Adressen, IDs und Tokens werden nie ausgegeben.
Die Ausgabe enthält nur Zähler, bekannte Schlüsselnamen und streng geprüfte Datumsformate
mit ersetzten Ziffern. Unbekannte Schlüssel werden nur gezählt, nicht übernommen.
Fehler geben ausschließlich `provider_unavailable` zurück, keine Providertexte oder Tracebacks.
Das Werkzeug speichert nichts und ändert keinen Kalenderindex.

## Optionaler Live-Aufruf

Nur nach bewusster Freigabe in einer Umgebung mit dem bestehenden App-Zugang:

```sh
bash tools/uv.sh run --no-sync python tools/calendar_google_probe.py \
  --live --calendar-id '<calendar-id>' \
  --start '2026-10-01T00:00:00Z' --end '2026-11-01T00:00:00Z' --page-size 250
```

Ohne `--live` werden keine Connector-Module geladen und keine Anbieter aufgerufen.
Live sind Kalenderkennung, Beginn und Ende Pflicht; `--page-size` ist optional.
Die Kalenderliste folgt höchstens zehn Seiten, die Terminliste höchstens 40 Seiten und
10.000 Einträgen. Auch Fehler, ungültige Argumente und unbekannte Schlüssel dürfen keine
privaten Eingaben ausgeben. HTTP-Logging wird während des Probelaufs unterdrückt, damit
Anfragepfade mit Kalenderkennungen nicht in Diagnoseausgaben gelangen.
Die lokale Shell-Historie kann eingegebene Argumente trotzdem speichern; der Aufruf mit
privater Kalenderkennung gehört nicht in öffentliche Protokolle.

## Noch umzusetzen (#21)

Produktionsadapter, Identitätsbindung, Quellenanlage und Verwaltungsrouten, Fehlerzustände,
periodischer Abruf, Revision-Fence und transaktionaler Snapshotwechsel, Google-Dialog sowie
Postgres-/UI-Vertragstests sind **nicht Bestandteil dieser Probe**. Insbesondere ist die
geplante Fingerprint-Bindung an die Hauptkalender-`summary` hier noch keine Zugriffsschranke.
Die Agenda erhält durch #19 allein keine neuen Google-Daten.

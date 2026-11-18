# Präferenzvorschläge: Offline-Probe vom 18.11.2026

## Aufbau

Zwölf vollständig synthetische Fälle in
`apps/api/tests/fixtures/preference_extraction.json`: vier dauerhafte Wünsche,
vier situative Bitten und vier zitierte, fremde oder hypothetische Aussagen.
Keine privaten oder historischen Unterhaltungen wurden verwendet.

Der Extraktor verwendet das für den Chat-Turn gewählte Modell, sonst
`mail_chat_model`. Die Live-Auswertung verwendet diesen Standard. Eingabe ist
jeweils nur der einzelne Fixturetext, mit demselben Prompt, JSON-Modus und
Validierungsweg wie im Chat. Werkzeuge und Verlauf fehlen.

## Ergebnis offline

`bash tools/uv.sh run --no-sync python tools/preference_extraction_eval.py`
endete mit Exitcode 0 und **12/12** passenden Ergebnissen:

| Fälle | Erwartet | Erhalten |
| --- | --- | --- |
| durable-short, durable-detail, durable-salutation, durable-signature | je 1 Vorschlag | je 1 Vorschlag |
| situational-short, situational-detail, situational-salutation, situational-signature | je 0 Vorschläge | je 0 Vorschläge |
| quoted-wish, foreign-wish, hypothetical-wish, forwarded-wish | je 0 Vorschläge | je 0 Vorschläge |

Keine Abweichung in den vorgegebenen Antworten. **Das ist keine Messung der
Modellgüte:** Offline werden festgelegte Ausgaben validiert. Der API-Test schickt
alle zwölf Fälle zusätzlich durch den Prompt-/Schemaweg mit einem gemockten
Client. Separate Negativtests lassen den Mock dennoch Kandidaten für die acht
ungeeigneten Eingaben liefern und prüfen deren Ablehnung.

Der konservative Dauerhaftigkeits- und Zitatfilter kann echte Wünsche übersehen.
Er kann semantische Fehlklassifikationen nicht allgemein ausschließen.
Vorschläge sind deshalb niemals bestätigte Präferenzen und wirken nicht auf Antworten.

## Live noch offen

Die Live-Probe wurde nicht ausgeführt; es lag kein Modellschlüssel vor.
Nur der ausdrückliche Aufruf mit `--live` sendet die zwölf synthetischen Fälle
über den bestehenden privaten Mistral-Client (`utils.mistral` über
`api.mail.chat_client`). Ausgabe: Fallkennung, erwartet, erhalten, Gesamtzahl.
Kein Eingabetext, Modelltext oder Fehlerdetail wird ausgegeben.

Nach der Live-Probe sind Modellname, Trefferzahl und Fehlklassifikationen hier
nachzutragen. Offline-Ergebnisse ersetzen diese Prüfung nicht.

# Präferenzvorschläge: Probe vom 18.11.2026

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
endete mit Exitcode 0. Gespeichert würde in **12 von 12** Fällen das Erwartete.

**Das ist keine Messung der Modellgüte:** Offline werden festgelegte Ausgaben validiert. Der API-Test
schickt alle zwölf Fälle zusätzlich durch den Prompt-/Schemaweg mit einem gemockten Client. Separate
Negativtests lassen den Mock dennoch Kandidaten für die acht ungeeigneten Eingaben liefern und prüfen
deren Ablehnung.

## Ergebnis live (18.11.2026)

Lauf: `bash tools/uv.sh run --no-sync python tools/preference_extraction_eval.py --live`, Modell
`mistral-medium-latest` (Standard `mail_chat_model`), lokal mit dem Schlüssel der App. Gesendet
wurden nur die zwölf synthetischen Fixturetexte. Die Ausgabe enthält nur Fallkennung, erwartete
und erhaltene Zahl.

| Fälle | Erwartet | Modell | Gespeichert |
| --- | --- | --- | --- |
| durable-short, durable-detail, durable-salutation, durable-signature | je 1 | je 1 gültiger Vorschlag | je 1 |
| situational-detail, foreign-wish, hypothetical-wish | je 0 | leere Liste | 0 |
| situational-short, situational-salutation, situational-signature, quoted-wish, forwarded-wish | je 0 | Vorschlag, von der Validierung verworfen | 0 |

Gespeichert würde also in allen zwölf Fällen das Erwartete. Das Modell allein lag in 7 von 12
Fällen richtig. Bei den fünf Fehlklassifikationen hat es situative, zitierte oder weitergeleitete
Bitten als dauerhaft vorgeschlagen; die Prüfung auf Dauerhaftigkeitswörter, Zitate und
Belegstelle hat sie abgefangen. Ohne diese Prüfung entstünden falsche Vorschläge. Der Filter
verwirft immer die ganze Antwort, auch wenn darin ein gültiger Vorschlag steckt.

Ein zweiter Lauf nach dem Review verlangt zusätzlich, dass Anrede und Signatur wörtlich in der
Belegstelle stehen. Ergebnis: wieder 12 von 12 gespeichert wie erwartet, das Modell allein 6 von 12.
Diesmal hat es auch `foreign-wish` vorgeschlagen; die Validierung hat ihn verworfen. Die
Fehlklassifikationen schwanken also zwischen Läufen.

Die Zahlen gelten für einen Lauf mit zwölf kurzen Texten. Über andere Formulierungen,
Sprachen oder Modelle sagen sie nichts. Der konservative Filter kann echte Wünsche übersehen.
Vorschläge sind deshalb niemals bestätigte Präferenzen und wirken nicht auf Antworten.

Das Werkzeug meldet inzwischen `rejected`, wenn die Validierung eine Modellantwort verwirft, und
trennt das von anderen Fehlern. Es gibt je Lauf beide Summen aus: was gespeichert würde und was das
Modell ohne Validierung geliefert hat.

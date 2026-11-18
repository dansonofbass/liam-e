# Gateway-Zugang für einen externen Lese-Client (2026-11-18, #34)

Ergebnis: **BLOCKED**. In der Probe kamen nur zwei Wege durch das Studio-App-Gateway: die
Browser-Sitzung des Owners und ein gültiger Workspace-API-Key im Header `x-api-key`. Beide
erreichen jede Route der App. Ein Zugang, der nur die Lesefassade erreicht, ließ sich nicht
nachweisen. Andere Schlüsselarten, etwa eingeschränkte Keys, wurden nicht geprüft (siehe „Nicht
geprüft“). Deshalb bleiben der native Transport (#36) und die OAuth-Anbindung externer Clients (#54)
gesperrt.

## Umgebung

| Teil | Version oder Stand |
| --- | --- |
| Mistral CLI | `mistral v0.18.1` |
| Vibe Code (CLI) | `vibe 3.1.2` |
| Mistral Python SDK in der App | `mistralai 3.7.0` |
| App | produktive App `liam-e`, Stand `main` 0327bcf, Sichtbarkeit `workspace` |
| Vibe Work | nicht geprüft |

Die Probe lief mit `tools/gateway_access_probe.py --live`, nur mit `GET` auf `/api/health`, auf die
Lesefassade `/api/agent-read/v1/mail/accounts` und auf `/.well-known/oauth-protected-resource`. Den
Workspace-Key löst das Werkzeug über die eigene Credential-Auflösung der App (`utils.mistral`) auf.
Die Ausgabe enthält weder die App-URL noch einen Schlüssel noch Antworttexte. Es gab keine
Schreibroute, keine Mail und keinen Kalenderzugriff.

## Matrix (ausgeführt)

| Fall | Ergebnis | Bedeutung |
| --- | --- | --- |
| `/api/health` ohne Credential | 401 `session_expired` | Das Gateway verlangt eine Anmeldung. |
| `/api/health`, ungültiger Bearer | 401 `session_expired` | |
| `/api/health`, gültiger Workspace-Key als `Authorization: Bearer` | 401 `session_expired` | Ein Workspace-Key im Bearer-Header genügt dem Gateway nicht. |
| `/api/health`, ungültiger Key in `x-api-key` | 403 `access_denied` | |
| `/api/health`, gültiger Workspace-Key in `x-api-key` | 200 | Der Workspace-Key öffnet die App. |
| Lesefassade ohne Credential | 401 `session_expired` | |
| Lesefassade, Workspace-Key in `x-api-key` | 401 von der App | Das Gateway lässt durch. Der Standard-Verifier in `api/mcp/access.py` lehnt ab, wie vorgesehen. |
| `/.well-known/oauth-protected-resource` | 404 | Unter diesem Pfad gibt es keine Protected Resource Metadata. Keine Antwort enthielt eine Bearer-Challenge (`WWW-Authenticate`). Andere Discovery-Pfade wurden nicht geprüft. |

Die Werte stammen aus einem Lauf am 18.11.2026. Die Fehlercodes sind feste Bezeichner des Gateways.

## Bewertung

- Der einzige nachgewiesene nicht-interaktive Weg durch das Gateway ist ein Workspace-API-Key. Er
  arbeitet nicht routengenau: Mit ihm erreicht ein Client auch Vorschläge bestätigen, Konten verbinden und Mails
  versenden. Außerdem darf er die übrigen Mistral-APIs des Workspace aufrufen. Nach dem Auftrag ist
  das ausdrücklich kein Lesezugriffsschutz.
- Ein zusätzliches, nur für die Lesefassade gültiges App-Token löst das nicht. Ein Client braucht
  trotzdem einen Workspace-Key, um das Gateway zu passieren. Die normalen App-Routen vertrauen
  weiterhin dem Gateway.
- Die serverseitige Seite hält wie vorgesehen dicht: Die Lesefassade lehnt ohne eigenen
  `ReadAccessVerifier` jeden Aufruf ab, auch hinter einem gültigen Gateway-Zugang.

## Vibe Code

`vibe mcp add` unterstützt Streamable HTTP (Standard), OAuth mit Scopes und Browser-Anmeldung
sowie einen statischen Schlüssel aus einer Umgebungsvariable mit frei wählbarem Header und Format
(`--api-key-env`, `--api-key-header`, `--api-key-format`). Technisch könnte Vibe Code also mit
`x-api-key` und einem Workspace-Key das Gateway passieren. Das ist genau der breite Schlüssel, den
der Auftrag ausschließt. Eine echte Verbindung war nicht prüfbar: Die App hat noch keinen
`/api/mcp`-Endpunkt (#36). Vibe Work wurde nicht geprüft und gilt nicht als unterstützt.

## Nicht geprüft

- `mistral apps publish` (Veröffentlichen im Vibe-Katalog): Welche Anmeldung und welchen Umfang ein
  Katalogeintrag mitbringt, ist offen. Die Veröffentlichung wäre eine Außenwirkung. Sie gehört
  nicht zu diesem Prüfauftrag und braucht eine eigene Freigabe.
- Ob Mistral Workspace-Keys mit eingeschränkten Rechten anbietet, etwa nur für eine App. In der CLI
  und in der App-Konfiguration gibt es dafür keinen Schalter.

## Entscheidung und Optionen für den Owner

BLOCKED: Ein Credential, das nur die Lesefassade erreicht, ist nicht nachgewiesen. #36 und #54 bleiben gesperrt.
Möglich wären:

1. **Abwarten:** Das Studio-Gateway bekommt routengenaue oder OAuth-gebundene Zugänge, etwa
   Protected Resource Metadata für eine Route. Dann diese Probe wiederholen.
2. **Eigenes Relay außerhalb von Studio:** Ein schmaler Dienst prüft ein eigenes, rotierbares
   Lesetoken oder OAuth (#54) und ruft nur die vier Leseoperationen auf. Den Workspace-Key hält nur
   er. Das ist eine Architekturentscheidung mit eigenem Betrieb und eigenem Deployment.
3. **Vibe-Katalog prüfen:** `mistral apps publish` an einer synthetischen Test-App ausprobieren,
   mit gesonderter Freigabe. Erst danach lässt sich sagen, ob ein Katalogeintrag den Umfang
   begrenzt.

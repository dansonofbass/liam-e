# Sicherheitsrichtlinie

## Unterstützte Versionen

Korrekturen gibt es nur für den aktuellen Stand von `main`.

## Schwachstelle melden

Bitte vertraulich über die private Meldung von GitHub: Reiter **Security**, dann **Report a
vulnerability**. Eine vermutete Schwachstelle gehört nicht in ein öffentliches Issue.

Hilfreich sind der geprüfte Stand (Commit oder Datum), die betroffene Route oder Funktion und die
Schritte zur Reproduktion mit synthetischen Daten. Nie mitschicken: Zugangsdaten, Tokens,
App-Passwörter, echte Mails oder Termine, Mistral-Organisations-, Workspace- oder App-IDs und
absolute lokale Pfade.

## Was zählt

liam-e verspricht eine enge Grenze (AGENTS.md, Abschnitte „Sicherheit“ und „Veröffentlichung und
private Daten“). In Scope sind Meldungen über ein gebrochenes Versprechen, zum Beispiel:

- Der Agent versendet, beantwortet, leitet weiter oder verändert eine Mail ohne bestätigte
  Vorschlagskarte, auch ausgelöst durch eine präparierte Mail oder Vorlage.
- Ein Credential, App-Passwort, Token oder Secret-Wert erscheint in einer Antwort, einem Log,
  einer Fehlermeldung oder unverschlüsselt in der Datenbank.
- Ein ausgehender Aufruf erreicht trotz `netguard.py` und `transport.py` ein privates Ziel
  (SSRF, DNS-Rebinding) oder einen nicht freigegebenen Mail-Host.
- Eine Abfrage liefert Daten eines Kontos oder einer Quelle außerhalb des angefragten Umfangs.
- Eine verändernde Operation ist über eine lesende MCP-Oberfläche erreichbar.

## Was nicht zählt

- liam-e ist eine Einzel-Nutzer-App. Wer sie über das Gateway aufrufen darf, regelt das
  Deployment in Mistral Studio, nicht die App. Fehlende Trennung mehrerer Nutzer ist eine
  dokumentierte Grenze.
- Schwachstellen in Mistral Studio, bei den Mail-Providern oder in Abhängigkeiten gehören zu
  diesen Projekten. Ein Advisory, das liam-e in seiner eigenen Nutzung betrifft, zählt.
- Eine falsche Kurzfassung oder Antwort des Modells ohne Folge für Versand, Daten oder Rechte ist
  kein Sicherheitsfehler.

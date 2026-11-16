# Vor der Veröffentlichung

Stand 2026-11-17. Das Repository ist privat und soll später öffentlich werden können. Diese Liste
nennt, was dafür noch zu entscheiden und einzustellen ist. Die laufenden Regeln stehen in
[AGENTS.md](../AGENTS.md), Abschnitt „Veröffentlichung und private Daten“.

## Befund vom 2026-11-17

Geprüft wurden alle getrackten Dateien, die Git-Historie aller Branches und die Texte aller Issues
und Pull Requests auf GitHub.

- **Dateien:** Die Mistral-IDs stehen nur noch in `mistral.json`. Links auf private
  Claude-Artefakte sind durch Namen ersetzt. Testadressen sind synthetisch, absolute Home-Pfade
  gibt es nicht. `tests/test_public_repo_hygiene.py` hält diesen Stand fest.
- **Historie:** Eine lokale Suche nach gängigen Schlüssel- und Tokenmustern fand nichts. Den
  verbindlichen Nachweis liefert der CI-Job `secrets` (gitleaks über die ganze Historie). Ältere
  Commits enthalten aber noch die Mistral-IDs (im Umsetzungsplan vom 13.11.) und die
  Artefaktlinks (DESIGN.md, Plan, Spec). Commits tragen den Vornamen des Autors, eine
  GitHub-noreply-Adresse und `Claude-Session`-Links.
- **Issues und PRs:** keine privaten Angaben gefunden. PR-Beschreibungen nennen Review-Profile und
  Modellfamilien der Werkzeuge, mit denen geprüft wurde.

## Offene Entscheidungen des Owners

1. **Historie.** (a) So veröffentlichen, wie sie ist: Die IDs sind keine Geheimnisse, verraten
   aber den Studio-Tenant. (b) Mit `git filter-repo` IDs und Links aus der Historie entfernen:
   Alle Commit-Hashes ändern sich, Verweise in Issues und PRs zeigen danach ins Leere.
   (c) Ein neues öffentliches Repository mit einem frischen Anfangscommit, das private bleibt
   Arbeits- und Deploy-Repo.
2. **Mistral-IDs in `mistral.json`.** `mistral deploy` baut aus dem gepushten Stand und liest den
   `deployment`-Block; ohne ihn legt ein Deploy eine neue App an. Sollen die IDs nicht öffentlich
   werden, geht das nur mit getrennten Repositories wie in (c).
3. **Lizenz.** Es gibt keine `LICENSE`. Ohne Lizenz darf niemand den Code nutzen. Die übernommenen
   Skills unter `.agents/skills/` bringen eigene Lizenzen mit.
4. **`Claude-Session`-Zeilen** in Commits und PRs behalten (wie in den anderen öffentlichen
   Repositories) oder künftig weglassen.

## Einstellungen auf GitHub beim Umschalten

- Private Schwachstellenmeldung einschalten; SECURITY.md und das Issue-Formular verweisen darauf.
- Secret Scanning und Push Protection einschalten.
- Branch-Schutz für `main`: Änderungen nur über PRs, die CI-Jobs `check`, `web-test`, `pytest`,
  `pg-contract` und `secrets` als Pflicht.
- Dependabot-Sicherheitsupdates einschalten.

## Was nie öffentlich wird

Workspace-Secrets in Studio, die lokale `.env`, die Datenbank des Deployments und die Traces in
Studio.

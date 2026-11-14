# DESIGN.md — liam-e

> **Verbindliche Quelle für die Oberfläche.** Vor jeder Arbeit an `apps/web` lesen.
> Exakte Werte (Farben, Maße, Schatten) stehen in den **Tokens**; dieses Dokument regelt,
> wie sie eingesetzt werden, wie Texte klingen und wie sich die App auf kleinen
> Bildschirmen verhält.

**Status:** gültig, Stand 2026-11-13. Quelle der Werte ist das Design-System „liam-e“ in
Claude Design (https://claude.ai/artifact/MJRNJYUPnK6ciYFc2U2KAz, Stilrichtung C „Weich“).
Mit dem Redesign entstehen daraus `apps/web/src/styles/tokens.css` (Tokens) und
`apps/web/src/ds/` (Bausteine). Ab dann sind diese Dateien die Quelle der Werte, und das
Design-System wird ihnen nachgeführt.

## Konflikt-Hierarchie

Bei Widerspruch gewinnt das Höhere.

**Wer entscheidet:**
1. Owner im Chat bzw. im Auftrag.
2. `AGENTS.md` (Repo-Regeln).
3. **DESIGN.md** (dieses Dokument).

**Was im Einzelfall gilt:**
- **Exakte Werte:** die Tokens. Weicht ein Wert hier ab, wird DESIGN.md korrigiert.
- **Regeln und Verhalten** (Texte, Zustände, Responsive): DESIGN.md. Weichen Bausteine
  davon ab, wird entschieden und entweder der Code oder dieses Dokument angepasst.
- Voreinstellungen von Bibliotheken (Tailwind, TanStack) zuletzt.

---

## 1. Wesen und Haltung

liam-e bringt die Mails aus allen Konten an einen Ort und erledigt mit dir, was darin
ansteht. Die Oberfläche ist **hell, weich und aufgeräumt**: schwebende Flächen auf einem
grünlich-grauen Grund, ein tiefes Petrol als einzige Farbe für Aktionen, große Rundungen,
helles und dunkles Theme. Sie tritt hinter den Inhalt zurück, bis etwas zu tun ist; dann
ist klar, was ein Klick bewirkt.

- **Ein Ziel pro Fläche.** Höchstens eine primäre Aktion je Ansicht.
- **Nichts passiert ohne Bestätigung.** Was der Assistent verändert oder verschickt, schlägt
  er vor; erst ein Klick führt es aus (§9.2).
- **Jeder Button erklärt sich.** Symbol-Buttons tragen Namen und Tooltip; Buttons mit nicht
  offensichtlichen Folgen ebenso.
- **Ruhe vor Dichte.** Lieber eine Zeile weniger als ein Rahmen mehr.
- **Bewegung erklärt, sie schmückt nicht.**

## 2. Sprache und Texte

### 2.1 Grundsatz: auf Deutsch geschrieben, nicht übersetzt

Jeder Text der Oberfläche, auch jede Antwort des Assistenten, muss klingen, als hätte ihn
jemand auf Deutsch für dich geschrieben. Englische Satzmuster, die durchscheinen,
Callcenter-Floskeln und Behördendeutsch sind Fehler, auch wenn jedes Wort für sich stimmt.
Deutsch ist die Ausgangssprache; es gibt kein englisches Original, das übertragen wird.

Der Maßstab des Owners (2026-11-13): „Guten Morgen! Was kann ich für dich erledigen?“
wirkt dahingesloppt. „Hallo, was kann ich für dich tun?“ klingt richtig. Das ist ein
Beispiel für den Ton, keine Einzelregel.

### 2.2 Ton

- **Du**, kleingeschrieben (du, dein). Freundlich, knapp, sachlich; wie jemand, der mitdenkt,
  nicht wie eine Hotline.
- Der Assistent darf in der **Ich-Form** sprechen („Hallo, was kann ich für dich tun?“),
  aber ohne Gefühle und Floskeln: kein „Gerne!“, kein „Ich hoffe, das hilft“, kein
  „Natürlich!“, keine Entschuldigungsketten.
- **Verben statt Substantivketten.** „ob du das Angebot annimmst“, nicht „deine Bestätigung
  des Angebots“.
- **Das gängige deutsche Wort zuerst.** Anglizismen nur, wo sie im Alltag das normale Wort
  sind (Mail, Chat, Newsletter, Link, Spam) oder Fachbegriff der Plattform (Secret).
- **Keine Emojis, keine Ausrufezeichen** in der Oberfläche.

### 2.3 Typische Fehler

| Statt | Besser | Warum |
|---|---|---|
| „Guten Morgen! Was kann ich für dich erledigen?“ | „Hallo, was kann ich für dich tun?“ | Tageszeit-Gruß und „erledigen“ klingen nach Hotline; so fragt niemand. |
| „Drei Mails brauchen eine Antwort.“ | „Auf drei Mails solltest du antworten.“ | „need a reply“, wörtlich übertragen. |
| „Danach wartet die Meyer GmbH auf deine Bestätigung des Angebots.“ | „Die Meyer GmbH möchte bis Montag wissen, ob du ihr Angebot annimmst.“ | Nominalstil; ein Verb trägt den Satz. |
| „Bist du sicher?“ | „5 Newsletter abbestellen? Das lässt sich nicht rückgängig machen.“ | Folge nennen statt Zweifel säen. |
| „Erfolgreich gespeichert!“ | „Gespeichert.“ | Erfolg ist der Normalfall. |
| „Es ist ein Fehler aufgetreten.“ | „Gmail antwortet nicht. Versuch es in ein paar Minuten noch mal.“ | Ursache und nächster Schritt. |
| „Keine Daten verfügbar“ | „Keine Mails in diesem Konto. Neue erscheinen nach dem nächsten Abruf.“ | Die Sache benennen, dann weiterhelfen. |
| „Lade …“, „Loading …“ | „Wird geladen …“ | „Lade“ liest sich als Befehl. |
| „Klicke hier, um ein Konto zu verbinden.“ | Button „Konto verbinden“ | Der Linktext ist die Handlung. |
| „Sync“, „Inbox“, „Draft“, „Thread“ | „Abrufen“/„Stand“, „Posteingang“, „Entwurf“, „Verlauf“ | Deutsches Alltagswort vorhanden. |
| „Gerne! Hier ist deine Zusammenfassung:“ | direkt mit dem Inhalt beginnen | Floskel ohne Information. |
| „Möchtest du, dass ich Antworten entwerfe?“ | Vorschlag als Chip: „Antworten entwerfen“ | Angebote sind Aktionen, keine Fragen. |
| „Mail(s)“ | „1 Mail“, „2 Mails“, „keine Mails“ | Pluralform ausschreiben. |
| „11/21“, „Fri, Nov 21“ | „Fr., 21.11.“ | Deutsches Datumsformat. |

### 2.4 Begriffe

Gleiche Sache, gleiches Wort, überall: Navigation, Buttons, Tooltips, Hinweise und
Antworten des Assistenten.

| Begriff | Nicht | Bedeutung |
|---|---|---|
| Mail, Mails | E-Mail(s), Nachricht | eine Mail; „E-Mail“ nur in festen Wörtern wie „E-Mail-Adresse“ |
| Konto | Account, Postfach | ein verbundenes Mailkonto (Gmail, Outlook, iCloud, IMAP) |
| Posteingang | Inbox | die gemischte Liste aller Mails aus allen Konten |
| Verlauf | Thread, Konversation | zusammengehörige Mails zu einem Betreff |
| Unterhaltung | Chat-Verlauf, Session, Thread | ein Gespräch mit dem Assistenten |
| Entwurf | Draft | vom Assistenten vorgeschlagene Mail, noch nicht gesendet |
| Abrufen · Stand | Sync, Synchronisieren, Refresh | neue Mails holen · Zeitpunkt des letzten Abrufs („Stand 08:57“) |
| Archivieren | Ablegen, Verschieben | aus dem Posteingang nehmen; die Mail bleibt im Konto |
| In den Papierkorb | Löschen (bei Mails) | wiederherstellbar; „Löschen“ nur, wo es endgültig ist |
| Abbestellen | Abmelden, Unsubscribe | Newsletter über den Abmeldelink beenden |
| Verbinden · Entfernen | Hinzufügen · Löschen (bei Konten) | Konto in liam-e aufnehmen bzw. herausnehmen; beim Anbieter bleibt alles |
| Anmelden | Einloggen, Login | Anmeldung bei Google oder Microsoft |
| Bestätigen · Abbrechen | OK · Ja · Nein | Entscheidung über einen Vorschlag |
| Rückgängig | Undo, Zurücknehmen | eine Aktion umkehren, solange es geht |
| Modell | KI, LLM | das gewählte Mistral-Modell |
| Secret | Geheimnis, Token | Workspace-Secret in Mistral Studio (Begriff der Plattform) |
| liam-e | Bot, KI, Agent | Name des Assistenten, wo ein Name nötig ist |

### 2.5 Schreibweisen

- **Zeichen:** Anführungszeichen „…“ (innen ‚…‘). Auslassung als ein Zeichen „…“, mit
  Leerzeichen davor, wenn Wörter fehlen („Wird geladen …“). Gedankenstrich „–“ mit
  Leerzeichen; Bis-Strich ohne („9–17 Uhr“). Bindestrich nur in Wörtern.
- **Zahlen:** Dezimalkomma, Tausenderpunkt ab vier Stellen („2.314 Mails“). Zahl und
  Einheit mit geschütztem Leerzeichen („184,20 €“, „3 Min.“). In Bedienelementen und
  Zählern Ziffern; in Antworten des Assistenten bis zwölf ausgeschrieben, außer bei
  Beträgen, Daten und Uhrzeiten.
- **Datum und Zeit:** in Listen „08:57“, „Gestern“, Wochentag für die laufende Woche
  („Di.“), danach „21.11.“; das Jahr nur, wenn es nicht das laufende ist. In Sätzen
  „Freitag, 21. November“ und „um 8:57 Uhr“. Relative Angaben nur bis „vor 59 Min.“.
- **Plural:** je Form ein eigener Text über `Intl.PluralRules` („keine Mails“, „1 Mail“,
  „2 Mails“). Nie Klammerplural.
- **Großschreibung** nach deutscher Rechtschreibung, erstes Wort von Buttons und
  Überschriften groß. Kein Title Case, keine Versalien.
- **Abkürzungen** nur in Hinweisen („z. B.“ mit Leerzeichen), nie in Buttons.

### 2.6 Textarten

- **Buttons:** Verb im Infinitiv mit Gegenstand, ein bis vier Wörter: „Konto verbinden“,
  „Antwort entwerfen“, „5 archivieren“. Nie „OK“, „Ja“, „Absenden“.
- **Tooltips:** ein Satz, was passiert, mit Verb in der dritten Person („Holt neue Mails
  aus allen Konten“) oder knapp im Infinitiv („Archivieren (E)“). Tastenkürzel in
  Klammern. Nie den sichtbaren Namen wiederholen.
- **Hinweise nach einer Aktion:** Ergebnis mit Zahl, Partizip am Ende („61 Mails
  archiviert.“), dann „Rückgängig“, wo es geht.
- **Fehler:** was nicht geklappt hat, die Ursache, wenn sie bekannt ist, und der nächste
  Schritt. Keine Schuldzuweisung, keine Fehlercodes ohne Erklärung.
- **Leere Zustände:** die Sache benennen und sagen, was als Nächstes passiert oder was du
  tun kannst.
- **Bestätigungen:** Frage mit Zahl und Gegenstand („5 Newsletter abbestellen?“), ein Satz
  Begründung, Unumkehrbares ausdrücklich.
- **Begrüßung:** kurz und ohne Tageszeit („Hallo, was kann ich für dich tun?“), darunter
  eine Zeile Stand („47 ungelesene Mails in 4 Konten · Stand 08:57“).
- **Platzhalter:** eine Einladung oder ein Beispiel („Frag etwas zu deinen Mails …“), keine
  Bedienungsanleitung.
- **Antworten des Assistenten:** mit dem Ergebnis beginnen, ohne Einleitung und ohne
  Schlussformel. Die Regeln aus §2.2 bis §2.5 gelten auch hier; der Systemprompt in
  `apps/api/src/api/mail/agent.py` enthält sie.

### 2.7 Prüfliste für jeden Text

1. Laut lesen: Würde man das so zu jemandem sagen?
2. Scheint ein englischer Satz durch? Dann neu formulieren, nicht umstellen.
3. Stimmen die Begriffe aus §2.4?
4. Stimmen Zeichen und Formate aus §2.5?
5. Ist die Folge einer Aktion genannt?
6. Pluralformen für 0, 1 und 2 geprüft?
7. Passt der längste realistische Wert (Kontoname, Betreff, Absender)?

### 2.8 Wo Texte stehen

Alle Texte der Oberfläche stehen in einem Katalog, `apps/web/src/i18n/de.ts`, nach
Ansichten gruppiert (entsteht mit dem Redesign). So steht jeder Begriff einmal und bleibt
einheitlich. Technische Literale in TSX (Pfade, Klassen, englische Werte) tragen
`// i18n-exempt`.

## 3. Farbe

- Grund der App ist `surface-ground`; darauf schweben `surface`-Flächen mit `shadow-sheet`
  (Seitenleiste, Hauptfläche). Innerhalb einer Fläche gliedern `surface-soft`-Kacheln. Menüs
  und Popover liegen auf `surface-overlay` mit `shadow-overlay`.
- `accent` ist die **einzige Handlungsfarbe**: primäre Buttons, aktiver
  Navigationspunkt, Senden, Links, Assistent-Marke, Erfolg. Text darauf in `on-accent`.
  Hover über Kacheln, Chips und Symbol-Buttons: `accent-soft` mit `accent`-Text.
- `warm` heißt nur **Dringlichkeit** (Prioritätspunkt, Frist), nie Aktion oder Schmuck.
- `danger` nur für Löschen und Fehler, immer mit Wort oder Symbol.
- `acc-1` bis `acc-4` färben **Konten** in der Reihenfolge ihrer Verbindung (Avatar,
  Konto-Punkt); ab dem fünften Konto beginnt die Reihe von vorn. Sie bedeuten nie einen
  Status.
- Rahmen von Bedienelementen sind `control-border`; `line` und `line-strong` sind rein
  dekorativ.
- **Dunkles Theme** folgt der Systemeinstellung (`prefers-color-scheme`), umschaltbar über
  `data-theme`. Es ist kein invertiertes Hell: `accent` wird heller und trägt dunklen Text,
  Schatten werden tiefer statt farbig.
- Schublade und Dialoge dunkeln den Inhalt dahinter mit `scrim` ab. Der Token fehlt im
  Design-System noch und kommt mit `apps/web/src/styles/tokens.css` dazu (hell
  `rgba(13, 19, 17, .45)`, dunkel `rgba(0, 0, 0, .6)`).
- In Komponenten nie Hex-Werte, immer `var(--…)`.

### Kontrast (WCAG AA, hell und dunkel)

Text mindestens 4,5:1, Kanten, Fokusring und andere bedeutungstragende Zeichen mindestens
3:1. Gemessen 2026-11-13 an den Werten des Design-Systems; die Spalte nennt das schwächste
Paar über beide Themes.

| Token | Auf | Ziel | Schwächstes Paar |
|---|---|---|---|
| `ink` | `surface`, `surface-soft`, `surface-ground`, `surface-overlay`, `accent-soft` | 4,5:1 | 10,65:1 |
| `ink-muted` | `surface`, `surface-soft`, `surface-ground`, `accent-soft` | 4,5:1 | 5,43:1 |
| `accent` als Text | `surface`, `surface-soft`, `accent-soft` | 4,5:1 | 5,36:1 |
| `on-accent` | `accent`, `accent-hover` | 4,5:1 | 6,40:1 |
| `warm` | `surface`, `surface-soft`, `warm-soft` | 4,5:1 | 4,94:1 |
| `danger` | `surface`, `surface-soft`, `danger-soft` | 4,5:1 | 5,38:1 |
| `on-danger` | `danger` | 4,5:1 | 6,54:1 |
| `on-acc` | `acc-1` bis `acc-4` | 4,5:1 | 4,58:1 |
| `tip-ink` | `tip-bg` | 4,5:1 | 15,88:1 |
| `control-border` | `surface`, `surface-soft` | 3:1 | 3,19:1 |
| `focus-ring` | `surface`, `surface-soft`, `surface-ground`, `accent-soft` | 3:1 | 5,36:1 |

Wer einen Farbwert ändert, misst diese Tabelle neu; mit dem Redesign prüft ein Test in
`apps/web` sie automatisch.

## 4. Schrift

- **Plus Jakarta Sans** in 400, 500, 600 und 700 für alles. In der App selbst gehostet
  über Fontsource, exakt gepinnt; keine Übertragung an Google. Nur die Vorschauen in Claude
  Design laden sie von Google Fonts.
- Stile aus den Tokens: `display` (36 px, nur die Begrüßung), `title` (24 px, Seitentitel
  und Betreff der geöffneten Mail), `heading` (17 px), `body` (14,5 px), `body-strong`,
  `small` (13 px, Metadaten), `caption` (12 px, Konto-Tags, Zähler, Uhrzeiten).
- Ziffern in Zählern, Uhrzeiten und Beträgen tabellarisch (`font-variant-numeric:
  tabular-nums`, Klasse `le-num`).
- Ungelesene Mails: Absender und Betreff in 700, sonst 500 und 400. Kein Kursiv, keine
  Versalien.
- Keine freien px-Schriftgrößen außerhalb der Tokens.

## 5. Raum, Form, Schatten, Bewegung

- **4-px-Raster**, Schritte `space-1` bis `space-8` (4 bis 64 px). App-Rahmen und Abstand
  der schwebenden Flächen `space-3` (ab `tablet`; auf `mobile` gibt es keinen Rahmen, §7.3),
  Innenabstand der Hauptfläche `space-5`, Kacheln und Karten `space-4`.
- **Radien:** `radius-pill` für alles, was man drückt (Buttons, Chips, Navigationspunkte,
  Tags, Symbol-Buttons); `radius-sm` (12 px) für Zeilen und Felder; `radius-md` (18 px)
  für Kacheln, Karten und Menüs; `radius-lg` (24 px) für schwebende Flächen, Composer und
  Bestätigungskarte.
- **Schatten** nur aus den Tokens: `shadow-sheet` für schwebende Flächen, `shadow-overlay`
  für Menüs, Popover und die Aktionsleiste in Listen, `shadow-lift` für den Hover von
  Kacheln und primären Buttons. Karten innerhalb einer Fläche haben keinen Schatten.
- **Linien sparsam:** Bereiche trennen sich über Flächen und Abstand; `line` nur in langen
  Listen, Konturen nur an Bedienelementen (`control-border`).
- **Bewegung:** 160 ms für Hover und Tooltips, 220 ms für Zustandswechsel, 420 ms für
  erscheinende Inhalte (`le-rise`), Kurve `cubic-bezier(.2, .8, .2, 1)`. Tooltips nach
  350 ms Verweilen, bei Tastaturfokus sofort. Seitenwechsel blenden den Inhalt der
  Hauptfläche über; Seitenleiste und Composer bleiben stehen.
- **`prefers-reduced-motion`** immer beachten: dann nur Überblenden, kein Aufsteigen,
  Streaming zeigt den Text sofort.

## 6. Symbole und Bausteine

- **Symbole: Lucide** (`lucide-react`, exakt gepinnt), 24er-Raster, Strich 1,8, runde
  Enden, `currentColor`. Größen 19 px (Standard) und 16 px (klein). Keine Emojis, keine
  Logos der Anbieter.
- **Lexikon:** `message-circle` Chat · `messages-square` Unterhaltungen (Symbolleiste am Tablet) · `inbox` Posteingang · `at-sign` Konten · `archive`
  Archivieren · `trash-2` In den Papierkorb · `reply` Antworten · `pencil` Antwort
  entwerfen · `mail-open` Gelesen/Ungelesen · `refresh-cw` Abrufen · `more-horizontal`
  Weitere Aktionen · `external-link` Mail öffnen · `arrow-up` Senden · `square` (gefüllt)
  Anhalten · `sparkle` Assistent · `flag` Priorisieren · `newspaper` Newsletter · `clock`
  Frist · `paperclip` Anhang · `check`, `circle-alert`, `info` in Hinweisen · `menu` Menü
  öffnen · `x` Schließen · `arrow-left` Zurück · `plus` Neue Unterhaltung · `search` Suchen
  · `chevron-down` Auswahl · `link` Connector · `key-round` Anmeldung beim Anbieter.
- **Bausteine** (Klassen `le-*`, Beschreibung und Vorschau im Design-System): Button,
  IconButton, Chip (mit Tag, Badge, Punkt), Tooltip, Notice, AppShell, NavItem, Menu,
  QuickAction, Composer, ChatMessage, MailReference, ConfirmCard, MailRow, Avatar,
  TextField, AccountCard. In der App liegen sie unter `apps/web/src/ds/` mit denselben
  Namen. Screens unter `src/routes/` setzen keine eigenen Bedienelemente aus rohem
  `<button>` oder `<input>` zusammen.
- **Zustände ohne Inhalt sind Pflicht:** jede Liste und Ansicht hat Leer, Laden
  (Platzhalterzeilen, kein Spinner über der ganzen Fläche) und Fehler mit Ursache und
  nächstem Schritt.

## 7. Responsive und mobil

Handy und Tablet sind keine verkleinerte Desktop-Ansicht; jede neue Ansicht plant sie von
Anfang an mit.

### 7.1 Breakpoints

| Name | Bereich | Ziel |
|---|---|---|
| `mobile` | unter 640 px | Handy hochkant |
| `tablet` | 640–1023 px | Tablet, kleines Fenster, Handy quer |
| `desktop` | ab 1024 px | Desktop |
| `wide` | ab 1440 px | breiter Monitor, Inhaltsbreite begrenzt |

### 7.2 Touch

- Bei `pointer: coarse` sind alle Tippziele mindestens **44 × 44 px**, ohne sich zu
  überlappen.
- **Nichts nur bei Hover.** Die Aktionsleiste einer Mailzeile erscheint am Desktop beim
  Hover; auf Touch öffnet ein sichtbarer Button „Weitere Aktionen“ dieselben Aktionen.
- Der Fokusring bleibt auch mit Touch (Tastatur am Tablet).

### 7.3 Hülle je Breakpoint

- `desktop`: Seitenleiste (`sidebar-width`) und Hauptfläche schweben nebeneinander.
- `tablet`: Seitenleiste als schmale Symbolleiste mit Tooltips; „Unterhaltungen“ öffnet
  eine Schublade über dem Inhalt.
- `mobile`: Die Hauptfläche füllt den Bildschirm, ohne Rahmen, Rundung und Schatten.
  Kopfzeile mit Menü-Button links, Titel und „Neue Unterhaltung“ rechts. Das
  Menü öffnet eine Schublade mit Navigation und Unterhaltungen, mit abgedunkeltem
  Hintergrund. Keine untere Navigationsleiste: Der Composer gehört an den unteren Rand.
- Die Schublade ist 308 px breit, höchstens `100vw - 48px`, mit 12 px Innenabstand,
  rechts 24 px Rundung und `shadow-overlay`; ein Schließen-Button steht in der Markenzeile.
- Der Composer bleibt unten, mit Abstand `max(12px, env(safe-area-inset-bottom))`.

### 7.4 Posteingang je Breakpoint

- `desktop`: Liste (`list-width`) und Lesebereich nebeneinander.
- `tablet` und `mobile`: nur die Liste; eine Mail öffnet als eigene Ansicht mit Zurück.
  Archivieren, Gelesen/Ungelesen, Papierkorb und „Weitere Aktionen“ stehen in der Leiste am
  oberen Rand; „Im Chat fragen“ und „Antwort entwerfen“ stehen in einer Leiste am unteren
  Rand.
- Auf `mobile` trägt jede Mailzeile einen sichtbaren Button „Weitere Aktionen“; eine Frist
  steht als Schild in `warm-soft` unter dem Vorschautext.
- Filter-Chips stehen auf `mobile` in einer Zeile, die für sich seitlich scrollt; die Seite
  scrollt nie seitlich.

### 7.5 Formulare und Container

- Felder füllen in Formularen die volle Breite.
- Kinder in Flex- und Grid-Containern, die wachsen (Text, Felder), tragen `min-width: 0`.
- Lange Werte (Betreff, Adresse, Kontoname) enden mit Auslassung, der volle Text steht im
  zugänglichen Namen oder Tooltip.

## 8. Barrierefreiheit

- Kontrast wie in §3, in beiden Themes.
- **Tastatur zuerst:** sichtbarer Fokusring (2 px `focus-ring`, 2 px Abstand) auf
  `:focus-visible`, logische Reihenfolge, Escape schließt Menüs und Schubladen, der Fokus
  bleibt in offenen Schubladen und Dialogen und kehrt danach an den Auslöser zurück.
- Symbol-Buttons tragen `aria-label`. Tooltips sind `role="tooltip"` und hängen über
  `aria-describedby` am Element.
- Status nie nur über Farbe: Dringlichkeit hat Punkt **und** Text oder Tooltip, Fehler ein
  Symbol und einen Satz.
- Gestreamte Antworten: `aria-live="polite"` auf dem Antwortbereich, angesagt wird erst die
  fertige Antwort, nicht jedes Zeichen.
- `prefers-reduced-motion` wie in §5.

## 9. Chat

### 9.1 Ablauf einer Antwort

1. Die Bitte erscheint rechts als Blase in `accent`.
2. Darunter zeigt `le-working` mit drei Punkten, was der Assistent gerade tut
   („Durchsuche 4 Konten …“).
3. Der Text läuft gleichmäßig ein (gepuffert, etwa drei Zeichen je 24 ms, nie ganze
   Absätze auf einmal), am Ende pulsiert ein Punkt in `accent`.
4. Mail-Karten und Bestätigungskarten erscheinen erst, wenn ihr Inhalt vollständig ist.
5. Danach bis zu drei Folgevorschläge als Chips.

Während der Antwort wird Senden zu Anhalten. Eine angehaltene Antwort bleibt stehen und
bekommt den Hinweis „Angehalten – die Antwort ist unvollständig.“ Die Liste scrollt nur mit,
solange du unten bist; scrollst du hoch, bleibt sie stehen, und ein Button „Zum Ende“
erscheint.

### 9.2 Vorschlagen und bestätigen

- Der Assistent darf suchen, lesen und zusammenfassen. Alles, was Mails verändert oder etwas
  verschickt (senden, antworten, weiterleiten, abbestellen, archivieren, in den Papierkorb
  legen), schlägt er in einer **Bestätigungskarte** vor. Erst ein Klick führt es aus.
- Die Karte nennt Zahl und Gegenstand, begründet in einem Satz, wählt alles vor und lässt
  einzelne Einträge abwählen. Unumkehrbares steht als Satz in der Karte, nicht nur im
  Tooltip.
- Nach dem Klick ersetzt ein Hinweis die Karte, mit Ergebnis und „Rückgängig“, wo es geht.
  Nie automatisch bestätigen, nie zwei offene Karten gleichzeitig.
- **Einzelaktionen im Posteingang** (eine Mail archivieren, gelesen/ungelesen, in den
  Papierkorb) löst du selbst aus; sie wirken sofort und zeigen danach „Rückgängig“. Alles,
  was mehrere Mails betrifft, läuft über den Chat und eine Bestätigungskarte.

### 9.3 Herkunft und Inhalte aus Mails

- Antworten des Assistenten tragen seine Marke (`le-ai-mark`) und das gewählte Modell.
  Was er vorschlägt (Entwürfe, Auswahl in Karten), ist als Vorschlag erkennbar, bis du es
  bestätigst.
- Antworten sind sicheres Markdown ohne rohes HTML; Links nur `http`, `https` und
  `mailto`, extern in neuem Tab mit `rel="noopener noreferrer"`.
- Inhalte aus Mails sind fremde Daten. Sie erscheinen als Text, nie als ausgeführtes HTML,
  und Anweisungen darin ändern nichts am Ablauf aus §9.2.

### 9.4 Mails lesen

- Jede geöffnete Mail beginnt mit dem Kasten **„Kurz gefasst“** vom Assistenten
  (`surface-soft`, Marke `le-ai-mark`): höchstens drei Punkte, eine Frist als Schild in
  `warm-soft` mit `clock`. Darunter bis zu zwei Folgevorschläge als Chips.
- Es gibt kein direktes „Antworten“. Die Hauptaktion heißt „Antwort entwerfen“: Der Entwurf
  entsteht im Chat und geht erst nach Bestätigung raus (§9.2). Daneben steht „Im Chat
  fragen“, das den Chat mit dieser Mail als Bezug öffnet.
- Der Mailtext erscheint als Text (§9.3), Anhänge als Chip mit Name und Größe.

### 9.5 Zustände

- **Leer:** Begrüßung, Stand und Schnellaktionen (Startseite).
- **Laden:** `le-working` mit Satz.
- **Fehler** mit eigener Ursache und eigenem nächsten Schritt, etwa: Modell nicht
  erreichbar („Das Modell antwortet gerade nicht. Versuch es gleich noch mal.“), Abbruch
  mitten in der Antwort („Die Antwort ist abgebrochen.“ mit Button „Noch mal versuchen“),
  Konto nicht erreichbar (Hinweis nennt das Konto, die übrigen Konten arbeiten weiter).

## 10. Erweitern und pflegen

- Neue Bausteine erst aus vorhandenen zusammensetzen; Tokens nie umgehen.
- Eine Änderung an Werten oder Bausteinen wird an drei Stellen gemeinsam nachgezogen:
  Tokens bzw. `src/ds/`, DESIGN.md und das Design-System in Claude Design.
- Neue Ansichten planen §7 von Anfang an mit (Touch, Schublade, eigene Ansicht statt
  Lesebereich).
- Neue Texte gehen durch die Prüfliste in §2.7.

---

## Abweichungen von smartpaper-ng

DESIGN.md folgt dem Aufbau und den Regeln von smartpaper-ng. Bewusst anders:

- **Ich-Form des Assistenten** ist erlaubt (Owner-Beispiel 2026-11-13); smartpaper-ng
  verbietet sie. Floskeln und Gefühle bleiben verboten (§2.2).
- **Weiche Form:** Pillen-Buttons, Radien bis 24 px, farbige Blase für eigene Nachrichten
  und Schatten für schwebende Flächen; smartpaper-ng ist flacher und trennt ohne Schatten.
- **Keine Mono-Schrift:** Zahlen sind tabellarisch statt in einer zweiten Familie.
- **Deutsch als einzige Sprache der Oberfläche**; es gibt keine englische Fassung.

## Entschieden (2026-11-13, Owner)

1. **Neues Design-System**, Stilrichtung C „Weich“; OMP Control wird nicht verwendet.
2. **Startseite ist der Chat** mit Schnellaktionen: Ungelesenes zusammenfassen,
   Priorisieren, Newsletter aufräumen, Heute fällig.
3. **Vorschlagen und mit einem Klick bestätigen**, nichts ohne Bestätigung (§9.2). Regeln,
   die ohne Rückfrage handeln, sind später gesondert zu entscheiden.
4. **Gestaltung:** aufgeräumt, Buttons klar erkennbar und mit Tooltip, saubere Navigation,
   fließende Übergänge, sauberes Streaming im Chat.
5. **Texte** klingen wie auf Deutsch geschrieben (§2), Maßstab „Hallo, was kann ich für dich
   tun?“.
6. **Design-System „liam-e“** abgenommen, mit dunklem Theme nach Systemeinstellung und
   sofort wirkenden Einzelaktionen mit „Rückgängig“.
7. **Mobile Hülle** mit Kopfzeile und Schublade statt unterer Navigationsleiste (§7.3).
8. **Schrift selbst gehostet** über Fontsource, keine Übertragung an Google (§4).
9. **Textkatalog** `apps/web/src/i18n/de.ts` für alle Texte der Oberfläche (§2.8).
10. **Screens abgenommen** auf dem Design-Canvas „liam-e Oberfläche“, Seite „Screens“
    (https://claude.ai/artifact/PdW36jpJZ5beBAgTh27yDC): Chat-Start, Antwort mit
    Streaming, Vorschlag bestätigen, Posteingang, Konten, dazu Handy mit Chat, Schublade,
    Posteingang und Mail. Darin entschieden: „Kurz gefasst“ über jeder Mail, kein direktes
    Antworten (§9.4), Einzelaktionen sofort mit „Rückgängig“ (§9.2), Aktionsleisten am
    Handy (§7.4).

## Entschieden (2026-11-14, Owner)

1. **Handy randlos:** Unter 640 px füllt die Hauptfläche den Bildschirm, ohne Rahmen,
   Rundung und Schatten. Ab 640 px schwebt sie wie bisher (§7.3).
2. **Vier Details aus den Screens übernommen:** Dringlichkeitspunkt in `warm` in der
   Mailzeile mit Tooltip; Symbole in Buttons mit Text 16 px, in Symbol-Buttons 19 px;
   eine Zeile Vorschautext auf der Mailkarte im Chat; 20 px Innenabstand im Panel
   „Konto verbinden“.
3. **Ungelesen-Zähler** am Posteingang auch in der schmalen Symbolleiste am Tablet.
4. **Weitere Einträge im Menü „Weitere Aktionen“** der geöffneten Mail sind geplant:
   „Weiterleiten“ (als Vorschlag über den Chat), „Als Spam markieren“ (Einzelaktion mit
   „Rückgängig“) und „Original anzeigen“ (Kopfzeilen und Quelltext, nur lesend). Jeder
   Eintrag ist eine eigene Aufgabe mit eigenem Endpunkt.
5. **Outlook:** Der Connector wird erneut geprobt, nur lesend, sobald die App in Studio
   ihren `MISTRAL_API_KEY` hat. Eigenes Microsoft-Login wird erst geplant, wenn er weiter
   scheitert.
6. **Gmail-Probe** (Antworten über den Connector, To und Cc) macht der Owner selbst.
7. **CI:** Ein GitHub-Workflow führt die bisher nur lokalen Prüfungen aus.
8. **Design-System „liam-e“** in Claude Design wird nach DESIGN.md und Code nachgeführt
   (§10).
9. **Theme-Schalter** Hell, Dunkel, System, im Browser gespeichert, unten in der
   Seitenleiste neben der Statuszeile (§3).
10. **Fokus:** Eingabefeld und Composer zeigen den Fokusring aus §8 wie alle anderen
    Bedienelemente.
11. **Freie Werte aufgeräumt:** Schriftgrößen nur über Tokens, Abstände auf dem
    4-px-Raster (§4, §5).

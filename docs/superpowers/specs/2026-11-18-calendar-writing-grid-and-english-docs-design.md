# Calendar writing, calendar grid and English documentation: design (2026-11-18)

## Intent

The owner reviewed the deployed calendar and found two gaps:

- **No write access.** Appointments can only be read. #23 was blocked because the Studio
  connector `google_calendar` has no version precondition and no idempotent create.
- **The view is not a calendar.** `/calendar` is two date fields, source chips and a day-grouped
  list. There is no month, week or day grid.

The same task continues #67 and #66, so documentation, issues and PRs become English. That was
the owner's direction from 2026-11-18.

Success means the owner can do three things:

- see a calendar that looks and behaves like one (month, week, day);
- create, change and delete their own appointments from it;
- let the assistant propose such changes in the chat and confirm them.

## Delivery

- **One task:** branch `feat/welle-6` in its own Git worktree, one PR.
- **Issues covered:** #67, #66, #23, and a new issue for the calendar grid. The new issue is
  written in English from the change template.
- **Commits:** each issue has its own commits and its own closing keyword in the PR.
- **Merging and deploying** are the owner's decision, after review.

## Goals

1. **Templates (#67):** English issue and PR templates. Field IDs and required flags stay the same.
2. **Documentation (#66):**
   - English as the leading documentation language, with English file names for the top-level docs.
   - A link check.
   - The AGENTS.md language rule.
   - A section mapping in the PR.
3. **Writing (#23):** create, update and delete own single Google appointments without guests.
   - The owner does this directly in the calendar.
   - The assistant does it through a confirmation card.
4. **Grid (new issue):** Month, Week, Day and List views.
   - Clicking a free slot starts a new appointment.
   - Clicking an appointment shows its details, with edit and delete where allowed.

## Non-goals

- Dragging appointments to move them or to change their length. This can be a later round.
- Editing series, inviting guests, RSVP, creating or deleting calendars, moving an appointment
  to another calendar.
- Writing ICS subscriptions or anything other than Google sources.
- Translating UI texts (#65) or historical probe reports and plans.
- An own Google OAuth path for the calendar. The owner decided against it on 2026-11-18,
  see Approaches.

## Anti-goals

These would count as failure even if the feature works:

- A second click, a retry or a restart creates the same appointment twice without anyone noticing.
- A change silently overwrites an appointment that changed in Google since it was shown.
- The assistant changes a calendar without a confirmed card, or acts on a calendar outside the
  turn's calendar scope.
- Calendar titles, descriptions, locations or provider texts appear in logs, error texts or
  chat extras.
- The translation drops a rule, a number or a decision from the German originals.

## Constraints from the current system

**Sources and the index**
- Google sources are read through `api/calendar/google.py`. The calls are `list_events` and
  `list_calendars`, plus the identity check (fingerprint of the primary calendar summary) before
  and after every listing.
- `calendar_source.capabilities_json` exists and is `["read"]` today.
- The index stores no location, no description, no attendees and no provider `updated`
  timestamp.
- `calendar_event.recurrence_json` holds `{"schema":"google-1","recurring":bool}` for Google
  events.
- Snapshots replace the whole window (`replace_all`) under a revision fence and a shared
  advisory lock.
- A manual sync has a persisted one-minute wait.

**Proposals and chat**
- Proposals live in `chat_message.proposal_json` (`api/mail/proposals.py`). They have a
  discriminated `kind` and one open card per conversation.
- The atomic claim (`claim_proposal`) prevents double execution. Provider calls run outside
  long transactions, as in the mail confirm path.
- Turn scope: `chat_context.calendar_scope_json` (a list of source IDs). The agent may only read
  calendars in that scope.

**Prompt and inventory**
- `agent_prompt.py` (`APP_PROMPT_VERSION` 7) forbids calendar writes and substitute actions.
- `apps/api/tests/test_mcp_exposure.py` has two parts that matter here:
  - It finds the read-only operation list in AGENTS.md by the German marker
    `lesenden Operationen:`. The marker must change together with the translation.
  - It requires every new mutating operation in `MUTATING_OPERATIONS`.

**Documentation**
- Code comments and tests cite DESIGN.md section numbers (§2.5, §5, §7.1, §7.2, §9.3). The
  numbering must stay stable.

**Repository rules**
- AGENTS.md conventions apply: one model per file, accessors only, generated migrations,
  regenerated OpenAPI and TS client, English code, German UI.
- DESIGN.md rules apply: building blocks from `src/ds`, no raw controls in routes, floating
  elements positioned only through `ds/floating.ts`, breakpoints and touch targets.

### Connector write tools (read on 2026-11-18, schema only, no calendar data)

- `create_event` takes `summary`, `startTime`, `endTime` (required), `calendarId`,
  `description`, `location`, `allDay` (start and end at midnight UTC) and `timeZone`, plus
  attendees, recurrence, reminders, Meet, colour and visibility.
  - It takes **no client ID and no request ID**.
- `update_event` takes `eventId` (required), `calendarId` and the fields to change.
  - **Only the given fields change**; omitted fields are kept.
  - `allDay` switches between timed and all-day; `startTime` and `endTime` must then be given.
  - It has **no etag, no If-Match and no sequence**.
  - It cannot move an event to another calendar.
- `create_event`, `update_event` and `delete_event` all accept `notificationLevel`.

### Live write probe (2026-11-18, owner-created empty calendar "liam-e TEST")

The probe found the calendar by its exact name and required it to be empty (`accessRole`
`owner`, 0 events). It created, changed and deleted synthetic appointments only, and printed
key names and checked values only. Afterwards the calendar held 0 events again.

**Successful calls**
- **Write scope:** the Studio grant can write. Create, update and delete succeeded.
- **Responses:** `create_event`, `update_event` and `delete_event` return the full event JSON,
  with the same keys as `get_event`, including `id`, `updated`, `htmlLink`, `created`,
  `organizer.self`, `attendees`, `recurringEventId` and `eventType`.
  - The `updated` in the update response equals a following `get_event`. **No read-back is
    needed.**
- **Partial update confirmed:** changing only the title kept location and description, and
  `updated` changed.
- **Clearing works:** `location: ""` and `description: ""` give `null` afterwards.
- **All-day:**
  - Start and end at midnight UTC give an **exclusive** end date, as in the listings. 12-05 to
    12-06 is one day.
  - Timed to all-day and back via `allDay` both work.
  - The connector accepted an all-day create with start equal to end and stored a zero-length
    day. **The app must validate end > start itself.**
- **Delete:** `get_event` afterwards returns the event with `status: cancelled`, not an error.
  A second delete returns an error text.

**Errors**
- **Delivery:** errors arrive as **HTTP 200 with `isError` absent** and a plain-text result
  instead of JSON. The text has the form `Google Calendar request failed (HTTP <code>, reason
  <reason>, not applied): …`, for example 404 `notFound` or 400 `timeRangeEmpty`.
- **Schema violations:** an unexpected argument returns a validation-error text, also with
  HTTP 200.
- **Consequence for reads:** the existing read path's HTTP 401/403 mapping in `live_call`
  never sees connector failures. Reads currently turn them into `provider_unavailable`, because
  JSON parsing fails. Recorded as a finding; changing the read path is not part of this task.
- `delete_event` takes `eventId`, `calendarId` and `notificationLevel` (default `NONE`).
- `get_event` takes `eventId` and `calendarId` and returns the full event, including `updated`,
  `attendees`, `organizer`, `recurringEventId`, `eventType` and `htmlLink`.

## Approaches

### Write path (decided by the owner: A)

- **A. Write through the connector with safeguards (chosen):**
  - Atomic claim of every write.
  - Live re-read right before writing; a changed `updated` gives a conflict.
  - A persisted write record; an unclear outcome becomes `unknown` and is resolved by reading,
    never by a blind retry.
  - Residual risks:
    - A change in the same second can be overwritten.
    - A duplicate can survive if the read-back cannot identify the created appointment.
  - No new setup for the owner.
- **B. Own Google OAuth with a calendar scope:**
  - Real `If-Match` and client event IDs, so full guarantees.
  - Needs a Google Cloud client, new consent and a second Google path next to the connector.
  - Refresh tokens expire after seven days while the client is in testing mode.
  - Rejected because the size grows a lot for a single-user app.

### Grid (builder's call, stated to the owner)

- **Own grid on the design system (chosen):** fits DESIGN.md (tokens, building blocks,
  floating rules, German texts) and the existing DST and timezone helpers in `calendar/state.ts`.
- **Calendar library** (FullCalendar, Schedule-X and others): brings its own buttons, DOM and
  styling, and conflicts with the no-raw-controls test and the floating rules. Rejected.

### Translation (decided in #66)

- In-place translation with renamed top-level docs.
- Historical reports stay German and get an English index.

## Part 1: English templates (#67)

- **Renames:**
  - `01-fehler.yml` → `01-bug.yml`
  - `02-aenderung.yml` → `02-change.yml`
  - `03-evaluation.yml` stays
  - `04-teilauftrag.yml` → `04-subtask.yml`
- **Translation:** all labels, descriptions, placeholders and options, plus `config.yml` and
  `pull_request_template.md`.
- **What stays:**
  - field IDs, `validations` and labels;
  - `blank_issues_enabled: false` and the private vulnerability reporting link;
  - the privacy notes;
  - the PR contract checklist, translated in full.
- **A test** parses every form and compares field IDs and required flags with a frozen copy of
  the current values. A negative case asserts that no German text remains (a small German
  stop-word list).
- **References:** AGENTS.md and CONTRIBUTING.md point to the new names.

## Part 2: English documentation (#66)

**Files to translate**
- `README.md`, `AGENTS.md`, `DESIGN.md`, `SECURITY.md`, `CONTRIBUTING.md` and
  `apps/chat-app/README.md`.
- CONTRIBUTING.md and the chat-app README are not named in #66, but they are maintained
  documents. Builder's call: include them.

**Renames**
- `docs/architektur.md` → `docs/architecture.md`
- `docs/lokale-entwicklung.md` → `docs/local-development.md`
- `docs/provider-und-betrieb.md` → `docs/providers-and-operations.md`
- `docs/veroeffentlichung.md` → `docs/publishing.md`

**Rules for the translation**
- **No content changes:** every rule, number, name and decision stays.
  - The PR carries a per-file section mapping, German heading to English heading.
  - The calendar additions from Parts 3 and 4 are written after the translation, so the mapping
    stays a pure translation diff.
- **DESIGN.md:** section numbers stay. German UI texts quoted as examples (tone rules, terms,
  button labels) stay German and are marked, for example `„Rückgängig“ (UI text)`.
- **AGENTS.md** gains the language rule: documentation, issues, PRs and commit messages are
  English; UI wording follows the locale catalogues (#65).
- **Inventory marker:** the read-only operation list keeps its exact operation names. The marker
  becomes English, `read-only operations:`, and `READ_ONLY_LIST_MARKER` in
  `test_mcp_exposure.py` changes with it. The test text "section Sicherheit" becomes
  "section Security".
- **Historical index:** `docs/superpowers/README.md` lists every dated spec, plan and probe
  report with a one-line English summary. The reports themselves stay unchanged.

**Link check**
- A test, `tests/test_doc_links.py`, resolves every relative link and anchor in tracked Markdown
  files.
  - It skips the generated `openwiki/` and `.agents/` trees. Their links to renamed docs follow
    on the next scheduled OpenWiki refresh; the PR says so.
- It also resolves every doc path cited in code comments (`AGENTS.md`, `DESIGN.md §n`, `docs/…`).
- Negative case: a broken link fixture fails.

**Untouched**
- OpenWiki pages are not edited.
- `tests/test_public_repo_hygiene.py` must still pass.

## Part 3: Writing appointments (#23)

### What is writable

**A source is writable when all three hold:**
- `provider == "google"`;
- the source is active and not a seed (seed rules below);
- the last successful listing reported `accessRole` `owner` or `writer`.

The snapshot stores this as `capabilities_json` `["read","write"]` or `["read"]`. The value is
updated on every successful snapshot, so a lost role removes `write`.

What that needs:
- `map_pages` reads `accessRole`.
- `GoogleSnapshot` carries it.
- The snapshot commit writes `capabilities_json` in the same transaction.

**An appointment is writable when its source is writable and the event:**
- has no `recurringEventId` and no `recurrence`;
- has no attendee other than `self`;
- has an organizer that is `self` or absent;
- has `eventType` `default` or none.

The snapshot stores this per event in the Google recurrence metadata, as `"editable": bool`
next to `"recurring"`, and exposes it as `editable` on `OccurrenceOut`. Builder's call: if a
column fits the accessor pattern better, use a generated migration instead.

The index flag only decides what the UI offers. **Every write re-checks eligibility live.**

### Live detail

- **Endpoint:** `GET /api/v1/calendar/occurrences/{id}/live` (`calendar_occurrence_live`). It is
  browser-only, listed in `BROWSER_ONLY_GET_OPERATIONS`, not in the Studio read list.
- **What it does:**
  - Calls `get_event` for an active Google source, after the identity check.
  - Returns title, start and end, all-day flag, timezone, location, description, `htmlLink`,
    `revision` (the provider `updated` string), `editable` and a fixed `reason` code when the
    event is not editable.
- **Description:** converted to plain text with the existing `html_to_text`. HTML is never
  rendered.
- **Storage:** nothing is stored.
- **Other providers:** for ICS and seeds it returns the index values without location and
  description.
- **Who uses it:** the detail panel and the edit dialog. The edit dialog sends `revision` back as
  `expected_revision`.

### Direct writes (owner-initiated, no card)

Endpoints:

| Method | Path | operation_id |
| --- | --- | --- |
| POST | `/api/v1/calendar/events` | `calendar_event_create` |
| PATCH | `/api/v1/calendar/occurrences/{id}` | `calendar_event_update` |
| DELETE | `/api/v1/calendar/occurrences/{id}` | `calendar_event_delete` |
| GET | `/api/v1/calendar/writes/{write_id}` | `calendar_write_get` (browser-only) |
| POST | `/api/v1/calendar/writes/{write_id}/check` | `calendar_write_check` |

**Request bodies**
- **All writes** carry `write_id`, a UUID the dialog creates when it opens.
- **Create** carries `source_id`, `title`, either `start_local`/`end_local` plus `timezone` or
  `start_date`/`end_date`, and optionally `location` and `description`.
  - The UI shows the all-day end inclusively; the API takes an exclusive `end_date`.
- **Update** carries `expected_revision` and only the changed fields.
- **Delete** carries `expected_revision`.

**Times**
- The server resolves local times in the IANA zone.
  - A nonexistent local time gives `422 calendar_time_invalid`.
  - An ambiguous local time takes the first offset, as tasks do.
- The server sends ISO times with offset plus `timeZone`. All-day writes send `allDay: true`
  with midnight UTC, as the connector requires.
- Builder's call on limits: title 1–500 characters, location ≤ 1,000, description ≤ 8,000,
  duration ≤ 14 days for timed events.

**Write record**
- A new table `calendar_write` holds:
  - `id` (the write ID, or the proposal ID for cards), `source_id`, `operation` and the target
    `external_id`;
  - `request_json` and its hash, `expected_revision`;
  - `status` (`running`, `done`, `failed`, `unknown`, `not_applied`);
  - `started_at`, `finished_at`, `result_external_id` and `error_code`.
- A partial unique index allows at most one `running` write per (`source_id`, `external_id`).
  A second concurrent write gives `409 calendar_write_in_progress`.

**Sequence of a write**
1. **Validation and claim:** validate, then insert the record as `running`.
   - The same `write_id` with the same hash returns the existing record.
   - The same `write_id` with a different hash gives `409 calendar_write_conflict`.
   - Insert and checks happen in one short transaction under the shared calendar lock.
2. **Live check:**
   - identity check, then source active and writable;
   - for update and delete: `get_event` and the eligibility rules again;
   - compare `updated` with `expected_revision`. A mismatch gives `409 calendar_event_changed`
     with the current values for the browser only, and the record becomes `not_applied`.
3. **Provider call:**
   - `create_event`, `update_event` (only the changed fields) or `delete_event`, always with
     `notificationLevel: NONE`;
   - writes get their own 30-second timeout, shorter than the stale threshold below;
   - this step holds no open transaction.
4. **Outcome**, classified from the tool result:
   - A JSON event with an `id` (and for create the requested title and times) is `done`. The
     response gives the new `revision` and the values for the index.
   - A text matching `Google Calendar request failed (HTTP <4xx>, reason <r>, not applied)` is
     `failed`, with fixed codes:
     - 404 → `calendar_event_gone` (update and delete) or `calendar_unavailable`;
     - 401/403 → `calendar_write_rejected`. A read-only grant must not cause a reconnect loop.
     - other 4xx → `calendar_write_rejected`.
   - A schema-validation text (our bug) is `failed` with `calendar_write_rejected`. It is logged
     as a fixed code only.
   - Everything else is `unknown`, with **no automatic retry**:
     - a timeout or connection loss;
     - an HTTP error of the Mistral API;
     - a 5xx text;
     - any text without `not applied`;
     - unparsable JSON;
     - a create response without an `id`.
5. **Identity:** the identity check (connector fingerprint) still runs before the live check,
   and again after an `unknown` outcome before resolving it.
6. **Index update:**
   - **When:** only after `done`.
   - **How:** a new fenced accessor, because `replace_window` is bound to a job claim. Under the
     shared lock and the source revision fence it applies:
     - create inserts the event and the occurrence when it lies inside the coverage;
     - update rewrites the occurrence;
     - delete removes the occurrence, and the event if nothing else references it.
   - **Afterwards:** bump `data_revision`. The next regular snapshot stays authoritative, and no
     manual sync is forced.
7. **Retention:** once a record reaches `done`, `failed` or `not_applied`, its `request_json` is
   cleared. Only the hash, the IDs, the status and the codes remain. Removing a source also
   deletes its write records (`calendar_source.remove`).

**Clearing location or description** sends an empty string; the probe confirmed that this clears
the field.

**Validation before any call:**
- end after start, for all-day too (the connector accepts a zero-length all-day);
- an all-day `endTime` is the exclusive end date at midnight UTC.

**Resolving `unknown`**

This runs on the check endpoint and lazily when the record is read. A record left `running`
longer than two minutes, after a restart, counts as `unknown`.

- **Create:** `list_events` on the calendar around the requested start and end with `fullText`
  set to the title.
  - Exactly one match on title, start, end and `created` ≥ `started_at` minus 5 minutes gives
    `done`.
  - No match gives `not_applied`.
  - Several matches leave `unknown`, with a link to Google so the owner can check by hand.
- **Update:** `get_event`. All requested fields equal gives `done`. `updated` still equal to
  `expected_revision` gives `not_applied`. Anything else stays `unknown`, shown as a conflict.
- **Delete:** `status: cancelled` (the probe showed this, not a 404) or a 404 text gives `done`.
  The same `updated` as expected with `status` not cancelled gives `not_applied`.
- **Retry:** only after `not_applied` may the UI offer "Erneut versuchen", with a new `write_id`.

**Error codes** are fixed: `calendar_not_writable`, `calendar_event_not_editable`,
`calendar_event_changed`, `calendar_event_gone`, `calendar_write_in_progress`,
`calendar_write_conflict`, `calendar_time_invalid`, `calendar_write_unknown`,
`reconnect_required`, `calendar_unavailable`, `calendar_write_rejected`. Texts are German, without input values.

### Assistant proposals (cards)

**The tool**
- `propose_calendar_change` with `action` `create`, `update` or `delete`, the target
  (`source_id`, or `occurrence_id` for update and delete), the values, and `timezone`. The
  browser zone is the default; it is shown on the card.
- The source must be in the turn's `calendar_scope_json`, active and writable.
- For update and delete, the tool reads the event live, applies the eligibility rules and binds
  `expected_revision` together with the before values.
- It refuses ambiguous input: a missing date, end before start, or a nonexistent time. The agent
  then asks the owner.
- No tool can confirm a card or write to the provider.

**The card**
- New `ProposalKind` `calendar` with one typed, discriminated `calendar` command, analogous to
  `api/tasks/proposals.py`. The command is bound to source, connection fingerprint, target,
  operation, `expected_revision`, timezone and the complete before and after values.
- A new card replaces the open one as today.
- The card shows calendar, title, date, start and end or all day, timezone, location and
  description, with before and after for updates. Delete states that it cannot be guaranteed to
  be undone.
- Builder's call: no editing inside the card in this round.

**Confirming**
- `POST /chat/proposals/{id}/confirm` claims atomically, then checks again:
  - the context is live;
  - the source is in the context's calendar scope, active and writable;
  - the identity is unchanged.
- It then runs the same write service with `write_id` set to the proposal ID.
- The result goes into `ProposalResult` (new field `calendar_write_id`, plus the status).
  `proposal_status` becomes one of the following:
  - `done`;
  - `failed`, with a code; `not_applied` counts as failed with `calendar_write_not_applied`, and
    the owner asks again;
  - the new `unknown`, with a "Prüfen" action calling `calendar_write_check`. A check that
    resolves the write rewrites the card's status and result.
- A card in `unknown` cannot be confirmed again.
- A second confirm gives `409 proposal_not_pending`, as in the mail path.
- Title, description and location stay in `proposal_json`, as mail drafts and task titles
  already do.

**Prompt**
- `APP_PROMPT_VERSION` 8.
- Calendar changes only through `propose_calendar_change`, and only own single appointments
  without guests.
- Ask when date, time or zone are unclear. Never invent IDs.
- Series, invitations and ICS stay read-only. The existing ban on substitute actions stays.

### Seeds

- `dev_seed` gets one synthetic Google source with static `capabilities_json`
  `["read","write"]`.
- The write service branches on seed IDs: their writes change only the index and never reach a
  provider, the same rule as for seed mail actions.
- Its live detail returns the stored values.
- All other seed sources stay read-only. The rule "a source is writable" applies to real sources.

### Inventory and security

- **MUTATING_OPERATIONS:** add `calendar_event_create`, `calendar_event_update`,
  `calendar_event_delete` and `calendar_write_check`.
- **BROWSER_ONLY_GET_OPERATIONS:** add `calendar_occurrence_live` and `calendar_write_get`.
- **AGENTS.md:** update the read-only list.
- **Logs:** they carry only fixed codes, never titles, descriptions, locations, calendar IDs or
  provider texts.

## Part 4: Calendar grid (new issue)

### Layout (desktop and tablet)

```
[Heute] ‹ ›  16.–22. November 2026      Monat | Woche | Tag | Liste   [+ Termin]  ↻
● Privat ● Arbeit ○ Feiertage                 Hinweis: 1 Kalender veraltet
        Mo 16   Di 17   Mi 18   Do 19   Fr 20   Sa 21   So 22
ganzt.          ▭ Urlaub ─────────────────▭
 08:00  ▭Team           ▭Zahnarzt
 09:00  ▭               ━━━━━━━━ jetzt
 10:00          ▭Call ▭Review
```

**Toolbar**
- "Heute", previous and next, a title for the period, a view switch, "+ Termin" (only when a
  writable source exists) and "Aktualisieren".
- Below it, source toggles as a coloured dot plus the name. Colours alone never identify a
  source: DESIGN.md §3 has only `acc-1` to `acc-4`, so they repeat from the fifth source.
  Builder's call on the assignment.
- Source notices (paused, outdated, incomplete, not covered, errors) collapse into one line. It
  expands to the per-source details that `SourceStatus` shows today.

**Views**
- **Week (desktop and tablet default)** and **Day:**
  - an all-day row on top, then an hour grid from 00:00 to 24:00 in its own scroll area;
  - the first render scrolls to 07:00, or to the current hour when that is later;
  - a now-line in the current day;
  - overlapping appointments share the column width;
  - events crossing midnight are clipped per day.
- **Month:**
  - a 6×7 grid starting on Monday, with up to three entries per day and "+N weitere", which
    opens that Day;
  - all-day spans run across the cells;
  - days outside the month are dimmed.
- **List:** the current agenda, kept for long ranges and screen readers, with its from and to
  fields.

**Behaviour**
- **URL state:** `/calendar?view=week&date=2026-11-18`, so reload, back and links work. An
  invalid value falls back to the default view and today.
- **Times:** shown in the browser zone; all-day stays on its date. This reuses `queryWindows`,
  `localBoundary` and `inLocalWindow`.
- **Loading:**
  - The visible range is loaded through the existing occurrences endpoint.
  - The grid follows cursor pages automatically, up to ten pages of 100. Beyond that it shows a
    notice that not everything was loaded.
  - An empty grid claims "Keine Termine" only when every selected source covers the range and no
    page is missing.

### Interactions

- **Click on a free slot** (Week, Day) or a day cell (Month) with a writable source present:
  opens "Neuer Termin", prefilled with that slot and one hour (Month: all day). A keyboard
  alternative is the "+ Termin" button.
- **Click on an appointment:** opens the detail.
  - Desktop: a panel next to the grid, like the inbox reading pane.
  - Tablet and mobile: the existing `/calendar/$occurrenceId` page.
  - The detail loads the live view and shows "Bearbeiten" and "Löschen" when `editable`.
    Otherwise it shows "Nur lesbar" with a fixed reason, plus "In Google Kalender öffnen" when a
    link exists.
- **New and edit dialog** (`le-dialog`):
  - Fields: calendar (only writable sources, at create only), title, all day, date, start and
    end, timezone shown, location and description.
  - An HTML description warns that formatting is lost when the description itself is edited.
  - Saving shows the states saving, saved, conflict (current values with "Übernehmen und neu
    bearbeiten"), and unknown ("Wird geprüft …" with a check action).
  - "Erneut versuchen" appears only after `not_applied`.
- **Delete** asks in a dialog and states that it cannot be guaranteed to be undone.

### Mobile

- The default view is Day, with a seven-day strip on top for jumping.
- Month shows dots per day and the selected day's appointments below the grid.
- Touch targets are 44 px. Nothing is hover-only.

### Accessibility

- Every appointment is a link or button with a full name, for example "Zahnarzt, Mittwoch,
  18. November, 08:00 bis 09:00, Privat".
- The view switch is a segmented control with `aria-pressed`. Arrow keys move between days in
  Month.
- The now-line and the decorative grid lines are `aria-hidden`.

### Texts

- German UI texts go into `i18n/de.ts`, written per DESIGN.md §2.
- DESIGN.md gains a short calendar subsection under §7, in English, written after Part 2.
- AGENTS.md "Calendar domain" describes Part 3, in English, also after Part 2.

## Order of work

1. **Part 1 and Part 2 first:** a mechanical translation, then the link check.
2. **Part 3 backend in parallel:** no doc edits; it regenerates the OpenAPI spec and the client.
3. **Part 4 in parallel:** the grid on the existing API first, then the dialogs and the detail
   once the Part 3 API is fixed.
4. **Integration:** the lead agent integrates serially and resolves overlaps
   (`test_mcp_exposure.py`, the generated client), then writes the English calendar
   documentation.

## Verification

**Backend**
- Mocked connector tests:
  - success;
  - conflict (changed `updated`);
  - a not-editable event (attendees, series, foreign organizer, special type);
  - lost role;
  - inactive source;
  - identity changed;
  - out-of-scope source for cards;
  - a double submit with the same and with a different `write_id` hash;
  - a parallel write on the same target;
  - a timeout giving `unknown`, then a check giving `done`, `not_applied` or ambiguous;
  - a process restart (a stale `running` record);
  - a create response without an ID;
  - all-day, DST gap and DST fold.
- PG contract tests: the partial unique index and the write-record claim under concurrency.
- Proposal regressions: a second confirm, a revoked context, the scope check at confirm.

**Frontend**
- Tests:
  - the week overlap layout;
  - midnight-crossing and all-day spans;
  - Month "+N";
  - URL state;
  - auto-paging cap and the empty-state rule;
  - DST days (23 and 25 hours);
  - the dialog states (conflict, unknown, retry only after `not_applied`);
  - read-only reasons;
  - the mobile defaults.
- The no-raw-controls and floating tests must keep passing.

**Docs**
- Template test, link check, hygiene test and the mapping review by a second reader.

**Full gate**
- `pytest tests apps/api/tests`, and the PG suites with `RUN_PG_CONTRACT=1`.
- `bun run test` in apps/web, `bash tools/gen-types.sh --check`, `bun run check` and
  `git diff --check`.

**Reviews**
- Each package gets a review from another model family. The security-relevant write path also
  gets a third family.

**Live write probe**
- **Done:** the first round ran on 2026-11-18 (results above).
- **Report:** a redacted English report goes to
  `docs/superpowers/probes/2026-11-18-google-calendar-write-probe.md`.
- **End-to-end check:** before the PR, the finished service runs once against "liam-e TEST":
  create, conflict (changed in between), update, delete and an `unknown` resolution, all with a
  simulated timeout. Never against a personal calendar.
- **Mocks:** tests use fixtures shaped like the recorded responses and error texts.

**Not checkable before merge**
- Real writes to the owner's personal calendars: no live write probe there.
- The GitHub issue chooser.
- Real devices.

These go into the PR as "not checked".

## Left to the builder

- Column or JSON flag for `editable`; exact field limits; the colour assignment per source.
- The exact component split and CSS, within DESIGN.md.
- How the stale `running` threshold is enforced (on read or by the worker), as long as no
  automatic provider retry happens.
- The wording of German UI texts, per DESIGN.md §2.

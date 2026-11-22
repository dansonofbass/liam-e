# Calendar writing, calendar grid and English docs: implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking. In this repository, separate implementation agents
> implement the packages and a lead agent integrates them (see "Packages").

**Goal:** Owners can see their appointments in a month, week or day grid and can create, change
and delete their own Google appointments, directly or through confirmed assistant cards.
Documentation and GitHub templates become English.

**Architecture:**
- **Writes** go through the Studio connector `google_calendar` with a persisted write record
  (`calendar_write`):
  - an atomic claim;
  - a live revision check before each call;
  - classification of the tool result into done, failed or unknown;
  - resolution of unknown outcomes by reading back.
- **Index:** a confirmed result updates the index through a fenced accessor.
- **Cards:** assistant proposals reuse the existing proposal and confirm path with a new kind
  `calendar`.
- **Grid:** built on the design system and the existing occurrences endpoint.

**Tech Stack:** FastAPI, SQLModel/Alembic, Postgres, pytest; React 19, TanStack
Router/Query, Tailwind 4, bun test.

**Spec:** `docs/superpowers/specs/2026-11-18-calendar-writing-grid-and-english-docs-design.md`.
Read it fully before starting any task.

## Global Constraints

**Repository conventions (AGENTS.md)**
- Code, comments and docstrings are English; UI texts are German, written per DESIGN.md §2;
  docs, issues and PRs are English.
- Models and accessors:
  - one model per file in `packages/py/db/src/db/models/`;
  - ORM queries only in `db/accessors/`;
  - no cross-table foreign keys.
- Migrations: only generated (`bunx nx run db:revision --message "..."`), applied with
  `bunx nx run db:migrate`. Never hand-edit `versions/`.
- After any API change, run `bunx nx run api:gen-openapi` and `bash tools/gen-types.sh`, and
  commit `apps/api/openapi.json` and `apps/web/src/api/generated/`.

**API and web conventions**
- Every new non-GET operation goes into `MUTATING_OPERATIONS`; every new browser-only GET goes
  into `BROWSER_ONLY_GET_OPERATIONS` (`apps/api/tests/test_mcp_exposure.py`).
- Web code calls the API only through the generated client.
- Web building blocks come from `src/ds`. Routes contain no raw `<button>`/`<input>` and no
  Tailwind sizes. Floating elements are positioned only through `src/ds/floating.ts`.
- Breakpoints: `mobile` < 640 px, `tablet` 640–1023 px, `desktop` ≥ 1024 px. Touch targets are
  44 × 44 px with `pointer: coarse`. Nothing is hover-only.

**Data and logging**
- Logs and error texts carry fixed codes only: no titles, descriptions, locations, calendar IDs,
  event IDs, emails or provider texts.
- Test data is synthetic: `example.org` addresses and invented titles. Never commit real
  calendar data.

**Connector calls**
- Every write sends `notificationLevel: "NONE"`.
- Writes use a 30-second timeout.
- No automatic provider retry, ever.

**Write status, error codes, prompt**
- Write status values: `running`, `done`, `failed`, `unknown`, `not_applied`. A `running` record
  older than 120 seconds counts as `unknown`.
- Error codes, exactly: `calendar_not_writable`, `calendar_event_not_editable`,
  `calendar_event_changed`, `calendar_event_gone`, `calendar_write_in_progress`,
  `calendar_write_conflict`, `calendar_time_invalid`, `calendar_write_unknown`,
  `reconnect_required`, `calendar_unavailable`, `calendar_write_rejected`,
  `calendar_write_not_applied`.
- `APP_PROMPT_VERSION` becomes `"8"`.

## Review Focus

These are the inputs most likely to break for a real owner, each pinned by a test in the named
task:

1. **Double click and parallel confirm** on the same card or the same dialog. Expected: one
   provider call, and the second request sees the first record. Pinned in B4 and B6.
2. **A response lost after Google applied the write.** Expected: `unknown`, then a check finds
   the event and reports `done`, with no duplicate. Pinned in B4.
3. **An appointment changed in Google after the dialog opened.** Expected: `409
   calendar_event_changed` with current values; nothing written. Pinned in B4 and U2.
4. **DST days and the all-day end:** a 23- or 25-hour day in the week grid, a nonexistent local
   time on create, a one-day all-day event. Expected: correct placement, `422
   calendar_time_invalid`, and an exclusive end date. Pinned in B4, G1 and U2.
5. **A source that loses write rights, or is paused or removed while a dialog or card is open.**
   Expected: `calendar_not_writable` or `calendar_unavailable`; never a write to another source.
   Pinned in B4 and B6.

---

## Packages

Packages D, B and G run in parallel, each with its own implementation agent in its own clone.
Package U starts after B and G are integrated, in a clone reset to the integration branch. The
lead agent owns the C tasks.

| Package | Tasks | Owner | Touches |
| --- | --- | --- | --- |
| D | D1, D2 | implementation agent | `.github/`, all maintained `*.md`, `tests/test_github_templates.py`, `tests/test_doc_links.py`, the marker in `apps/api/tests/test_mcp_exposure.py`, doc paths in code comments |
| B | B1–B7 | implementation agent | `apps/api/src/api/calendar/`, `apps/api/src/api/mail/{connectors,proposals,agent_tools,agent_prompt,dev_seed}.py`, `apps/api/src/api/routers/api/v1/calendar/`, `apps/api/src/api/routers/api/v1/chat/{proposals,schemas}.py`, `packages/py/db/`, API tests, the inventory sets in `test_mcp_exposure.py`, generated client |
| G | G1–G3 | implementation agent | `apps/web/src/calendar/`, `apps/web/src/routes/_app/calendar*`, `apps/web/src/i18n/de.ts` (calendar section), `apps/web/src/api/queries.ts` (calendar queries) |
| U | U1–U3 | implementation agent, after B+G | `apps/web/src/calendar/`, `apps/web/src/chat/` (calendar card), `apps/web/src/i18n/de.ts` |
| C | C1–C6 | lead agent | issue, integration, English calendar docs, probe report, end-to-end run, gate, PR |

Packages B and G must not edit AGENTS.md, DESIGN.md or other Markdown. The lead agent writes
the calendar documentation in C3.

---

## Package D: English templates and documentation

### Task D1: English GitHub templates (#67)

**Files:**
- Rename and translate:
  - `.github/ISSUE_TEMPLATE/01-fehler.yml` → `01-bug.yml`
  - `02-aenderung.yml` → `02-change.yml`
  - `03-evaluation.yml` (name stays)
  - `04-teilauftrag.yml` → `04-subtask.yml`
- Translate: `.github/ISSUE_TEMPLATE/config.yml`, `.github/pull_request_template.md`.
- Create: `tests/test_github_templates.py`.

**Interfaces:**
- Produces: the template file names above. AGENTS.md and CONTRIBUTING.md references are updated
  in D2.

- [ ] **Step 1: Freeze the current contract in the failing test.** Before renaming, read every
  form and write `EXPECTED`, a dict from the new file name to a list of `(id, required)` tuples
  in form order, taken from the current files. Test
  `test_issue_forms_keep_field_ids_and_required_flags` parses each new YAML with `yaml.safe_load`
  and asserts:
  - `[(f.get("id"), f.get("validations", {}).get("required", False)) for f in body if f["type"] != "markdown"] == EXPECTED[name]`;
  - `labels` unchanged.
- [ ] **Step 2:** Test `test_config_keeps_blank_issues_off_and_private_reporting` asserts:
  - `blank_issues_enabled is False`;
  - the contact link URL is unchanged.
- [ ] **Step 3:** Test `test_templates_contain_no_german` asserts that none of these words occur
  as whole words, case-insensitive, in any template file: `und`, `nicht`, `oder`, `bitte`,
  `wird`, `für`, `über`, `ist`, `Beschreibung`, `Ergebnis`, `Fehler`.
- [ ] **Step 4:** Run `bash tools/uv.sh run --no-sync pytest tests/test_github_templates.py -q`.
  Expected: FAIL (files missing).
- [ ] **Step 5:** `git mv` and translate the templates. Keep:
  - structure, field IDs, `validations` and labels;
  - the privacy notes (no credentials, real mails, Mistral IDs or local paths);
  - the full PR checklist: one task/branch/PR, closing keyword per issue, generated client,
    generated migrations, settings, MCP inventory, not-checked items.
- [ ] **Step 6:** Run the test. Expected: PASS.
- [ ] **Step 7: Commit.** Message: `docs(github): English issue and PR templates`. Body:
  `Part of #67.`

### Task D2: English documentation (#66)

**Files:**
- Translate in place: `README.md`, `AGENTS.md`, `DESIGN.md`, `SECURITY.md`, `CONTRIBUTING.md`,
  `apps/chat-app/README.md`.
- `git mv` and translate:
  - `docs/architektur.md` → `docs/architecture.md`
  - `docs/lokale-entwicklung.md` → `docs/local-development.md`
  - `docs/provider-und-betrieb.md` → `docs/providers-and-operations.md`
  - `docs/veroeffentlichung.md` → `docs/publishing.md`
- Create: `docs/superpowers/README.md`, `tests/test_doc_links.py`.
- Modify: `apps/api/tests/test_mcp_exposure.py`, only:
  - `READ_ONLY_LIST_MARKER = "read-only operations:"`;
  - the two message strings "section Sicherheit" → "section Security".
- Modify: every code comment and test that cites a renamed doc path or a German section name
  (find them with `grep -rn -E 'AGENTS\.md|DESIGN\.md|docs/' apps packages tests tools`).
- Do not touch `openwiki/`, `.agents/` or `docs/superpowers/{specs,plans,probes}/*`.

**Interfaces:**
- Consumes: the D1 file names.
- Produces:
  - the English AGENTS.md line containing `read-only operations:` followed by the same
    backticked operation names, in the same order;
  - section names `Security`, `Calendar domain`, `Agent read facade` and the others, translated
    one to one;
  - DESIGN.md with unchanged section numbers.

- [ ] **Step 1: Write `tests/test_doc_links.py`.** Test `test_relative_markdown_links_resolve`
  covers every `git ls-files '*.md'` file except those under `openwiki/` and `.agents/`. For each
  `[text](target)` whose target is not a URL and not `mailto:`:
  - the file exists relative to the source file;
  - when a `#anchor` is given, a heading in the target file slugifies to it. GitHub slug: lower
    case, spaces to `-`, punctuation dropped except `-` and `_`, umlauts kept.

  Test `test_code_comment_doc_references_resolve` checks every `docs/<name>.md` mentioned in
  tracked `*.py`, `*.ts`, `*.tsx` and `*.sh` files for existence.

  Negative test `test_link_check_reports_a_missing_target` runs the checker function on a
  temporary file linking `missing.md` and asserts one failure.
- [ ] **Step 2:** Run it. Expected: PASS on the current tree (proves the checker before the
  renames).
- [ ] **Step 3: Translate the documents.** Rules:
  - Keep every rule, number, name, operation ID, code span and decision.
  - Keep DESIGN.md §-numbering.
  - German UI texts quoted as examples stay German and are marked once per section, for example
    `„Rückgängig“ (UI text)`.
  - Product terms in the UI keep their German spelling in quotes.
  - Add to AGENTS.md, under the agent working rules: "Documentation, issues, pull requests and
    commit messages are English. UI wording follows the locale catalogues (see #65); until then
    the UI is German."
  - Update the template references to the D1 names.
- [ ] **Step 4: Update the marker** in `test_mcp_exposure.py` as above. Run
  `bash tools/uv.sh run --no-sync pytest apps/api/tests/test_mcp_exposure.py -q`. Expected: PASS.
- [ ] **Step 5: Write `docs/superpowers/README.md`.** One table each for specs, plans and
  probes. Every file gets one English summary line and a relative link. It states that these are
  dated records and stay in their original language.
- [ ] **Step 6: Section mapping.** Write `/tmp/section-mapping.md` (not committed) with one table
  per file: German heading → English heading. Paste it into the final report.
- [ ] **Step 7: Run the checks.**
  - `bash tools/uv.sh run --no-sync pytest tests -q`
  - `git grep -n -I -E '\b(und|nicht|oder|bitte|wird|für|über)\b' -- README.md AGENTS.md DESIGN.md SECURITY.md CONTRIBUTING.md docs/*.md apps/chat-app/README.md`

  Expected: all PASS. Every remaining grep hit is a marked UI example or a quoted product term;
  list them in the report.
- [ ] **Step 8: Commit.**
  - `docs: make English the leading documentation language` with body `Part of #66.`
  - A separate commit for the link check: `test(docs): check relative links and doc references`.

---

## Package B: writing appointments (backend)

### Task B1: Write capability and per-occurrence `editable` from snapshots

**Files:**
- Modify:
  - `apps/api/src/api/calendar/google.py` (`map_pages`, `GoogleSnapshot`, new `editable`)
  - `apps/api/src/api/calendar/sync.py` (`run_sync`)
  - `packages/py/db/src/db/accessors/calendar_snapshot.py` (`replace_window`)
  - `packages/py/db/src/db/models/calendar_occurrence.py`
  - `apps/api/src/api/routers/api/v1/calendar/schemas.py`
- Migration: generated, adds `calendar_occurrence.editable` (bool, server default false).
- Test: `apps/api/tests/test_calendar_google_probe.py` (extend) and the PG snapshot contract
  tests.

**Interfaces:**
- Produces:
  - `google.editable(raw: dict) -> tuple[bool, str | None]`, with reasons `series`, `guests`,
    `organizer`, `event_type`, `cancelled`;
  - `google.map_event(raw: dict, page_timezone: str | None, source_timezone: str) -> Occurrence`,
    factored out of `map_pages`;
  - `Occurrence.editable: bool = False` in `adapters.py`;
  - `GoogleSnapshot.access_role: str | None`;
  - `replace_window(..., capabilities_json: str | None = None)`;
  - `OccurrenceOut.editable: bool`.

- [ ] **Step 1: Failing tests:**
  - `test_editable_rules`: series instance (`recurringEventId` set) gives `(False,"series")`;
    another attendee gives `"guests"`; only the self attendee gives True; `organizer.self` False
    gives `"organizer"`; `eventType` `birthday` gives `"event_type"`; `eventType` `default` or
    None gives True.
  - `test_map_pages_marks_editable_and_reports_access_role`: the fixture page has
    `accessRole: "writer"` and the result has `access_role == "writer"`.
- [ ] **Step 2: Failing PG test**
  `test_replace_window_sets_capabilities_in_the_same_transaction`. Assert:
  - `capabilities_json` is `'["read","write"]'` after a snapshot with role `owner`;
  - it is `'["read"]'` after one with role `reader`;
  - it is unchanged when the claim is lost.
- [ ] **Step 3: Implement.**
  - In `run_sync` map the roles: `owner`/`writer` → `["read","write"]`, anything else →
    `["read"]`, for Google sources only.
  - Generate the migration.
- [ ] **Step 4:** Run `pytest apps/api/tests/test_calendar_google_probe.py -q` and the PG suite
  (`RUN_PG_CONTRACT=1`). Expected: PASS.
- [ ] **Step 5: Commit.** `feat(calendar): record write capability and editable occurrences`.

### Task B2: Write records

**Files:**
- Create:
  - `packages/py/db/src/db/models/calendar_write.py`
  - `packages/py/db/src/db/accessors/calendar_write.py`
- Modify: `packages/py/db/src/db/accessors/calendar_source.py` (`remove` deletes write rows in
  the same transaction).
- Migration: generated.
- Test: `packages/py/db/tests/test_calendar_write_pg.py` (live-Postgres suites in that
  directory are discovered by `bunx nx run db:test-pg-contract` and may import `api`).

**Interfaces:**
- Produces model `CalendarWrite` (table `calendar_write`) with these columns:
  - `id: str` PK;
  - `source_id: str`;
  - `operation: str` (`create`, `update`, `delete`);
  - `target_external_id: str | None`;
  - `request_json: str | None`;
  - `request_hash: str`;
  - `expected_revision: str | None`;
  - `status: str`;
  - `error_code: str | None`;
  - `result_external_id: str | None`;
  - `result_revision: str | None`;
  - `started_at: datetime` (UTC column helper);
  - `finished_at: datetime | None`.

  Index: partial unique `uq_calendar_write_running_target` on (`source_id`,
  `target_external_id`) `WHERE status = 'running' AND target_external_id IS NOT NULL`.
- Produces accessor functions:
  - `async def claim(row: CalendarWrite) -> tuple[CalendarWrite, bool]`:
    - takes `lock_source` and inserts;
    - returns `(existing, False)` when the ID exists with the same `request_hash`;
    - raises `WriteConflict` when the hash differs;
    - raises `WriteInProgress` on the partial unique index.
  - `async def finish(write_id: str, *, status: str, error_code: str | None = None, result_external_id: str | None = None, result_revision: str | None = None) -> CalendarWrite`:
    - sets `finished_at`;
    - sets `request_json = None` when the status is `done`, `failed` or `not_applied`.
  - `async def get(write_id: str) -> CalendarWrite | None`.
  - `async def expire_running(write_id: str, *, before: datetime) -> CalendarWrite | None`: sets
    `unknown` only when the record is still `running` and `started_at < before`.
  - Exceptions `WriteConflict` and `WriteInProgress`.

- [ ] **Step 1: Failing PG tests:**
  - `test_claim_is_idempotent_for_same_hash`;
  - `test_claim_conflicts_on_other_hash`;
  - `test_second_running_write_on_target_is_refused`, with two concurrent claims via
    `asyncio.gather`, of which exactly one succeeds;
  - `test_finish_clears_request_text_on_final_states` (`unknown` keeps it);
  - `test_expire_running_only_after_threshold`;
  - `test_remove_source_deletes_write_rows`.
- [ ] **Step 2: Implement** the model and accessor. Generate the migration with message
  `calendar write records`.
- [ ] **Step 3:** Run the PG suite. Expected: PASS.
- [ ] **Step 4: Commit.** `feat(calendar): persist calendar write records`.

### Task B3: Connector write client and result classification

**Files:**
- Create: `apps/api/src/api/calendar/google_write.py`.
- Modify: `apps/api/src/api/mail/connectors.py`. Add an optional `timeout: float = 120` to
  `_post` and `_call_tool`; no behaviour change for existing callers.
- Create test: `apps/api/tests/test_calendar_google_write.py`.
- Create fixtures: `apps/api/tests/fixtures/google_calendar/write_event.json` (synthetic event
  with every key recorded in the spec's probe section), `write_errors.json` (the recorded error
  text shapes with synthetic values).

**Interfaces:**
- Produces:
  - `TOOLS = frozenset({"get_event", "list_events", "create_event", "update_event", "delete_event"})`;
  - `@dataclass(frozen=True) class ToolResult: kind: Literal["event", "failed", "unknown"]; event: dict | None = None; status: int | None = None; reason: str | None = None`;
  - `def classify(text: str) -> ToolResult`;
  - `async def call(tool: str, arguments: dict) -> ToolResult`. It rejects tools outside
    `TOOLS` with `ValueError`, uses `_call_tool(..., timeout=30)`, and turns timeouts, transport
    errors and `httpx.HTTPStatusError` into `ToolResult("unknown")`.

- [ ] **Step 1: Failing tests:**
  - `test_classify_event_json` → `kind == "event"` when the JSON is a dict with a non-empty
    string `id`.
  - `test_classify_not_applied_404`. The text
    `"Google Calendar request failed (HTTP 404, reason notFound, not applied): Not Found."` gives
    `("failed", status=404, reason="notFound")`.
  - `test_classify_validation_error_is_failed`. The text starting
    `"1 validation error for call[create_event]"` gives `("failed", reason="schema")`.
  - `test_classify_5xx_or_unknown_text_is_unknown`. Inputs: an `HTTP 503 … not applied` text
    (5xx is never definite), any other text, and a JSON dict without `id`.
  - `test_call_refuses_other_tools`.
  - `test_call_timeout_is_unknown`, with a monkeypatched `_call_tool` raising
    `httpx.ReadTimeout`.
- [ ] **Step 2: Implement.** Regex:
  `^Google Calendar request failed \(HTTP (\d{3}), reason ([A-Za-z]+), not applied\)`. Only
  `400 <= status < 500` is `failed`.
- [ ] **Step 3:** Run `pytest apps/api/tests/test_calendar_google_write.py -q`. Expected: PASS.
- [ ] **Step 4: Commit.** `feat(calendar): classify connector write results`.

### Task B4: Write service

**Files:**
- Create:
  - `apps/api/src/api/calendar/writes.py`
  - `packages/py/db/src/db/accessors/calendar_index_write.py`
- Create test: `apps/api/tests/test_calendar_writes.py`, mocked connector with in-memory event
  state. Add PG cases to `packages/py/db/tests/test_calendar_write_pg.py`.

**Interfaces:**
- Consumes: B1 `map_event`, `editable`; B2 accessor; B3 `call`, `ToolResult`;
  `google.identity`.
- Produces in `writes.py`:
  - `class WriteRequest(BaseModel)` (`extra="forbid"`) with these fields:
    - `write_id: UUID`;
    - `operation: Literal["create","update","delete"]`;
    - `source_id: str`;
    - `occurrence_id: str | None`;
    - `expected_revision: str | None`;
    - `title: str | None` (1–500 characters);
    - `start_local: str | None` and `end_local: str | None` (ISO local `YYYY-MM-DDTHH:MM`);
    - `timezone: str | None` (IANA);
    - `start_date: date | None` and `end_date: date | None` (exclusive);
    - `location: str | None` (≤ 1,000);
    - `description: str | None` (≤ 8,000).

    Validators:
    - create needs a title and exactly one of the timed pair or the date pair;
    - update needs `occurrence_id`, `expected_revision` and at least one field;
    - delete needs `occurrence_id` and `expected_revision`;
    - timed end > start and at most 14 days;
    - date end > start.
  - `class WriteOutcome(BaseModel)`:
    - `write_id: str`;
    - `status: Literal["done","failed","unknown","not_applied","running"]`;
    - `error_code: str | None`;
    - `occurrence_id: str | None`;
    - `revision: str | None`;
    - `current: LiveEvent | None` (set on `calendar_event_changed`).
  - `class LiveEvent(BaseModel)`:
    - `occurrence_id: str | None`;
    - `source_id: str`;
    - `title: str`;
    - `start_at: datetime | None`, `end_at: datetime | None`, `timezone: str | None`;
    - `start_date: date | None`, `end_date: date | None`;
    - `location: str | None`;
    - `description: str | None` (plain text via `api.mail.sync_types.html_to_text`);
    - `description_was_html: bool`;
    - `html_link: str | None`;
    - `revision: str | None`;
    - `editable: bool`;
    - `reason: str | None`.
  - `async def execute(request: WriteRequest, *, write_id: str | None = None) -> WriteOutcome`.
    The proposal path passes `write_id=proposal_id`.
  - `async def check(write_id: str) -> WriteOutcome`.
  - `async def live(occurrence_id: str) -> LiveEvent`.
  - `def resolve_local(value: str, zone: str) -> datetime`. A nonexistent time raises
    `WriteError("calendar_time_invalid")`; an ambiguous time takes `fold=0`.
  - `class WriteError(Exception): code: str; status: int`.
- Produces in `calendar_index_write.py`:
  `async def apply(*, source_id: str, upsert: tuple[CalendarEvent, CalendarOccurrence] | None, delete_external_id: str | None) -> bool`.
  It works under `lock_source`. The source must be active. An upsert happens only when the
  occurrence overlaps the sync-state coverage. Delete removes the occurrence, and its event when
  it is unreferenced. It increments `calendar_sync_state.data_revision`. It returns False without
  change when the source is inactive.

**Sequence in `execute`** (the spec's "Sequence of a write"):
1. Validate. Compute `request_hash` as SHA-256 of the canonical JSON without `write_id`.
2. Load the source.
   - Missing or inactive → `calendar_unavailable`.
   - Not Google, or `write` not in its capabilities → `calendar_not_writable`.
   - Seed IDs take the seed branch (B5).
3. Claim. An existing record is returned as its outcome, after `expire_running` with
   `now - 120 s`. `WriteConflict` → 409 `calendar_write_conflict`. `WriteInProgress` → 409
   `calendar_write_in_progress`.
4. `identity()` must equal `source.connection_ref`; otherwise finish `failed`
   `reconnect_required`.
5. For update and delete, run `get_event`:
   - failed 404 → `calendar_event_gone`;
   - `editable(raw)` False → `calendar_event_not_editable`;
   - `raw["updated"] != expected_revision` → finish `not_applied`, error
     `calendar_event_changed`, `current` filled.
6. Call the write tool with `notificationLevel: "NONE"`.
   - Create sends `summary`, `startTime`/`endTime` with offset plus `timeZone`, or
     `allDay: true` with `YYYY-MM-DDT00:00:00Z` for start and exclusive end, plus `location` and
     `description` when given.
   - Update sends only the fields present in the request. An empty string clears location or
     description. A switch between timed and all-day sends `allDay` and both times.
7. Classify the result:
   - `event` → `done` with `result_external_id` and `result_revision` (`updated`), then
     `calendar_index_write.apply` with `map_event(..., editable(raw)[0])`;
   - `failed` → codes as in the spec:
     - 404 → `calendar_event_gone` for update/delete, `calendar_unavailable` for create;
     - 401, 403 and other 4xx → `calendar_write_rejected`;
     - schema → `calendar_write_rejected`;
   - `unknown` → `unknown` with `calendar_write_unknown`.

**Resolution in `check`** (create, update, delete), exactly as in the spec's "Resolving
`unknown`". Create uses `list_events` with `calendarId`, `startTime = start - 1 min`,
`endTime = end + 1 min`, `fullText = title`, and matches on title, start and end with `created
>= started_at - 5 min`.

- [ ] **Step 1: Failing tests**, one per behaviour, with a fake connector:
  - `test_create_done_updates_index`;
  - `test_same_write_id_returns_first_outcome_without_second_call`;
  - `test_same_write_id_other_payload_conflicts`;
  - `test_parallel_updates_on_one_event_one_call` (PG);
  - `test_update_changed_revision_not_applied_with_current`;
  - `test_update_sends_only_changed_fields`;
  - `test_clear_location_sends_empty_string`;
  - `test_delete_done_removes_occurrence`;
  - `test_not_editable_series_guests_organizer_refused`;
  - `test_source_without_write_capability_refused`;
  - `test_inactive_source_refused`;
  - `test_identity_changed_reconnect_required`;
  - `test_timeout_unknown_then_check_done_single_match`;
  - `test_timeout_unknown_then_check_not_applied`;
  - `test_check_ambiguous_create_stays_unknown`;
  - `test_check_delete_cancelled_is_done`;
  - `test_stale_running_reads_as_unknown`;
  - `test_create_response_without_id_unknown`;
  - `test_nonexistent_local_time_422`;
  - `test_ambiguous_local_time_first_offset`;
  - `test_all_day_end_is_exclusive_midnight_utc`;
  - `test_all_day_equal_dates_refused`;
  - `test_failed_403_is_write_rejected_not_reconnect`;
  - `test_live_reads_description_as_text`;
  - `test_logs_contain_no_titles` (`caplog` holds only fixed codes).
- [ ] **Step 2:** Run them. Expected: FAIL.
- [ ] **Step 3: Implement** `writes.py` and `calendar_index_write.py`.
- [ ] **Step 4:** Run `pytest apps/api/tests/test_calendar_writes.py -q` and the PG suite.
  Expected: PASS.
- [ ] **Step 5: Commit.** `feat(calendar): write own appointments with claims and live checks`.
  Body: `Part of #23.`

### Task B5: Calendar write endpoints, live detail, seeds, inventory

**Files:**
- Create:
  - `apps/api/src/api/routers/api/v1/calendar/events.py` (POST `""`)
  - `apps/api/src/api/routers/api/v1/calendar/writes.py` (GET `/{write_id}`, POST
    `/{write_id}/check`)
- Modify:
  - `apps/api/src/api/routers/api/v1/calendar/occurrences.py` (GET `/{occurrence_id}/live`,
    PATCH `/{occurrence_id}`, DELETE `/{occurrence_id}`)
  - `schemas.py`
  - `apps/api/src/api/mail/dev_seed.py`
  - `apps/api/tests/test_mcp_exposure.py` (sets only)
- Test: `apps/api/tests/test_calendar_write_routes.py`.

**Interfaces:**
- Operation IDs:
  - `calendar_event_create`: body `EventCreateIn` → `WriteOutcome`, 201;
  - `calendar_event_update`: body `EventUpdateIn` → `WriteOutcome`;
  - `calendar_event_delete`: body `EventDeleteIn` with `write_id` and `expected_revision` →
    `WriteOutcome`;
  - `calendar_occurrence_live` → `LiveEvent`;
  - `calendar_write_get` → `WriteOutcome`;
  - `calendar_write_check` → `WriteOutcome`.
- Status mapping:
  - `WriteError` → `refuse(status, code, German text)` from `api.errors`;
  - `calendar_event_changed` → 409 with the `WriteOutcome` (including `current`) as body under
    `detail`;
  - `unknown` → 202 with the outcome;
  - `done` → 200 (create 201);
  - `failed` → 4xx per code. The codes are listed in Global Constraints.
- Seeds: in `seed_calendars`, the Google seed source (key `work`, index 0) gets
  `capabilities_json='["read","write"]'`. Its occurrences get `editable=True` for its single
  events. `writes.execute` checks `source_id in SEED_CALENDAR_IDS`:
  - it applies the change to the index only, with synthetic IDs `seed-<uuid>` and revision
    `seed-<counter>`;
  - it never calls `google_write.call` or `identity`.

  `live()` returns index values for seeds and ICS.
- Inventory:
  - add `calendar_event_create`, `calendar_event_update`, `calendar_event_delete` and
    `calendar_write_check` to `MUTATING_OPERATIONS`;
  - add `calendar_occurrence_live` and `calendar_write_get` to `BROWSER_ONLY_GET_OPERATIONS`.

- [ ] **Step 1: Failing route tests** (TestClient with a monkeypatched service):
  - status codes per outcome;
  - a 409 body containing `current`;
  - a 422 for a body with extra fields;
  - a seed source write that changes the index and makes no connector call (assert the fake is
    unused).
- [ ] **Step 2: Implement.** Run `pytest apps/api/tests -q`. Expected: PASS, including
  `test_mcp_exposure.py`.
- [ ] **Step 3: Commit.** `feat(calendar): calendar write endpoints and live detail`.
  Body: `Part of #23.`

### Task B6: Assistant proposals for appointments

**Files:**
- Create:
  - `apps/api/src/api/calendar/proposals.py` (typed commands)
  - `apps/api/src/api/calendar/chat.py` (`prepare` for the tool)
- Modify:
  - `apps/api/src/api/mail/proposals.py`
  - `apps/api/src/api/mail/agent_tools.py`
  - `apps/api/src/api/mail/agent_prompt.py`
  - `packages/py/db/src/db/models/chat_message.py` (status comment only)
- Test: `apps/api/tests/test_calendar_proposals.py`.

**Interfaces:**
- Consumes: B4 `WriteRequest`, `execute`, `check` and `live`.
- Produces:
  - `class CalendarCommand(BaseModel)` (`extra="forbid"`) with these fields:
    - `action: Literal["create","update","delete"]`;
    - `source_id: str`;
    - `connection_ref: str` (stored server-side, never sent to the browser);
    - `occurrence_id: str | None`;
    - `expected_revision: str | None`;
    - `timezone: str`;
    - `before: LiveEvent | None`;
    - `after: CalendarValues | None`.
  - `CalendarValues` holds title, start and end (local timed or date pair), location and
    description.
  - `Proposal.calendar: CalendarCommand | None` and `ProposalKind` including `"calendar"`.
  - `ProposalResult.calendar_write_id: str | None` and
    `ProposalResult.calendar_status: str | None`.
  - Tool `propose_calendar_change` with parameters:
    - `action` (enum);
    - `reason`;
    - `source_id`;
    - `occurrence_id`;
    - `title`;
    - `start_local`, `end_local`;
    - `start_date`, `end_date`;
    - `timezone`;
    - `location`, `description`.

    It returns `{"proposal_id", "status": "pending"}` or `{"error": <fixed code>}`.
  - `async def recheck_calendar_card(proposal_id: str) -> ChatMessage` in `api/mail/proposals.py`.
    It calls `writes.check(proposal_id)` and rewrites the card's status and result.
- The browser-facing proposal output never contains `connection_ref`. Check where
  `proposal_json` is serialized for `ChatMessageOut` and exclude it there.

**Rules:**
- `prepare` refuses with these codes:
  - a source outside `ctx.calendar_source_ids`, or inactive, or without `write`:
    `calendar_out_of_scope` / `calendar_not_writable`;
  - missing or ambiguous times: `calendar_time_invalid`;
  - update or delete on a not editable event: `calendar_event_not_editable`, after `live()`.
- `confirm` for kind `calendar` follows this path:
  - Validation: `selected_ids`, `body` and `task_edit` must be empty, otherwise
    `selection_invalid`.
  - Claim via `claim_proposal`. On a failed claim, a pending card with a revoked context gives
    `ProposalContextRevokedError`, otherwise `ProposalStateError`.
  - Context checks: the context is live and the source is still in `calendar_scope_json`.
  - Write: build the `WriteRequest` from the command and run `writes.execute(...,
    write_id=proposal_id)`.
  - Status mapping:
    - `done` → `done`;
    - `failed` → `failed`;
    - `not_applied` → `failed`, with `calendar_write_not_applied`, or `calendar_event_changed`
      when that was the cause;
    - `unknown` → `unknown`.
  - The outcome is stored with `set_proposal`.
- New route `POST /chat/proposals/{proposal_id}/check` (`chat_proposal_check`, in
  `MUTATING_OPERATIONS`) calls `recheck_calendar_card`. It is allowed only for kind `calendar` in
  status `unknown`.
- Prompt:
  - Replace the calendar write ban: calendar changes only through `propose_calendar_change`, and
    only for own single appointments without guests.
  - Ask when date, time or zone are unclear. Never invent IDs. Read the occurrence first for
    update and delete.
  - Series, invitations and ICS stay read-only.
  - Keep the ban on substitute actions (mail drafts, copies, tasks) for anything not writable.
  - Set `APP_PROMPT_VERSION = "8"`.

- [ ] **Step 1: Failing tests:**
  - `test_propose_out_of_scope_source_refused`;
  - `test_propose_update_binds_live_revision_and_before`;
  - `test_confirm_runs_one_write_with_proposal_id`;
  - `test_second_confirm_proposal_not_pending`;
  - `test_confirm_after_scope_change_refused_without_write`;
  - `test_confirm_revoked_context_refused`;
  - `test_unknown_card_cannot_be_confirmed_and_check_resolves_to_done`;
  - `test_card_output_has_no_connection_ref`;
  - `test_prompt_version_8_and_rules_present`.
- [ ] **Step 2: Implement.** Run `pytest apps/api/tests -q`. Expected: PASS.
- [ ] **Step 3: Commit.** `feat(chat): propose and confirm calendar changes`. Body: `Part of #23.`

### Task B7: Generated contract

- [ ] **Step 1:** Run `bunx nx run api:gen-openapi && bash tools/gen-types.sh`.
- [ ] **Step 2:** Run `bash tools/gen-types.sh --check && bun run check`. Expected: exit 0.
- [ ] **Step 3: Commit** `apps/api/openapi.json` and `apps/web/src/api/generated/` as
  `chore(api): regenerate client for calendar writes`.

---

## Package G: calendar grid (frontend, existing API)

### Task G1: Pure grid helpers

**Files:**
- Create:
  - `apps/web/src/calendar/grid.ts`
  - `apps/web/src/calendar/grid.test.ts`
  - `apps/web/src/calendar/url.ts`
  - `apps/web/src/calendar/url.test.ts`

**Interfaces** (all take `timeZone = browserZone()` where relevant):
- `type CalendarView = 'month' | 'week' | 'day' | 'list'`.
- `parseSearch(search: Record<string, unknown>, isMobile: boolean): { view: CalendarView; date: string }`.
  Invalid values fall back to `isMobile ? 'day' : 'week'` and `todayLocal()`.
- `visibleRange(view: CalendarView, date: string): { from: string; to: string }`, with an
  exclusive `to`:
  - week starts Monday;
  - month spans 6 × 7 days from the Monday on or before the 1st;
  - list spans `date` to `date + 7`.
- `shift(view: CalendarView, date: string, step: -1 | 1): string`.
- `periodTitle(view: CalendarView, date: string): string`, German via `Intl` `de-DE`, for
  example `16.–22. November 2026`, `November 2026`, `Mittwoch, 18. November 2026`.
- `type Placed = { row: OccurrenceOut; day: string; startMinute: number; endMinute: number; column: number; columns: number }`.
- `layoutDay(rows: OccurrenceOut[], day: string, timeZone?: string): Placed[]`:
  - timed rows only, clipped to the local day (DST-aware via `localBoundary`);
  - overlap groups packed into columns;
  - zero-length points get 15 minutes of height.
- `allDaySpans(rows: OccurrenceOut[], from: string, to: string): { row: OccurrenceOut; startCol: number; span: number }[]`,
  for all-day rows only, clipped to the range.
- `monthCells(date: string): { day: string; inMonth: boolean }[]`, length 42.

- [ ] **Step 1: Failing tests:**
  - week of 2026-11-18 → from `2026-11-16` to `2026-11-23`;
  - month of 2026-11 → from `2026-10-26` to `2026-12-07`;
  - `shift` across a year boundary;
  - two overlapping events give `columns: 2`, and a third non-overlapping one gives `columns: 1`;
  - an event 23:00–01:00 appears on both days, clipped;
  - on 2026-10-25 in Europe/Berlin (25 h), an event 02:30 local has
    `startMinute = 150 + 60` only when it is in the second 02:30 (assert by instant);
  - on 2026-03-29 (23 h), 03:00 local gives `startMinute = 120`;
  - an all-day 2026-11-20 to 2026-11-23 in the week gives `startCol 4, span 3`;
  - `parseSearch({ view: 'x' }, true).view === 'day'`.
- [ ] **Step 2:** Run `cd apps/web && bun test src/calendar/grid.test.ts src/calendar/url.test.ts`.
  Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4:** Run again. Expected: PASS.
- [ ] **Step 5: Commit.** `feat(calendar): grid layout helpers`.

### Task G2: Views, toolbar and route state

**Files:**
- Create:
  - `apps/web/src/calendar/CalendarView.tsx` (page shell and toolbar)
  - `MonthView.tsx`
  - `TimeGrid.tsx` (week and day)
  - `ListView.tsx` (the current agenda moved here, behaviour unchanged)
  - `SourceBar.tsx` (dot plus name toggles, collapsed notices line that expands to `SourceStatus`)
  - `useRangeOccurrences.ts`
- Modify:
  - `CalendarPage.tsx` (keeps `SourceStatus` and `CalendarDetail` exports)
  - `calendar.css`
  - `apps/web/src/routes/_app/calendar.tsx` (`validateSearch` with `parseSearch`)
  - `apps/web/src/i18n/de.ts` (calendar section)
  - `apps/web/src/api/queries.ts`
- Test: `apps/web/src/calendar/CalendarView.test.tsx` and the existing
  `CalendarPage.test.tsx`/`CalendarRoute.test.tsx`, kept passing.

**Interfaces:**
- Consumes: G1.
- Produces:
  - `useRangeOccurrences(from: string, to: string, sourceIds: string[]): { rows: OccurrenceOut[]; complete: boolean; capped: boolean; isPending: boolean; isError: boolean; refetch(): void }`.
    It follows `next_cursor` automatically, at most 10 pages of 100 per query window from
    `queryWindows`, and deduplicates by `id`. `capped` is true when the limit stopped it.
  - Props `onSlot(start: { date: string; minute?: number })` and
    `onOpen(occurrenceId: string)` on `MonthView` and `TimeGrid`. They are used by U2; in G2,
    `onSlot` is a no-op and `onOpen` navigates to `/calendar/$occurrenceId`.

**Behaviour** (from the spec's Part 4):
- Toolbar: "Heute", previous and next, a period title, and the segmented control "Monat",
  "Woche", "Tag", "Liste" with `aria-pressed`.
- "Aktualisieren" keeps today's due-only refresh-on-open.
- Week and day:
  - an all-day row, then 24 hour rows in a scroll container;
  - the initial scroll goes to 07:00 or to the current hour if that is later;
  - a now-line (`aria-hidden`);
  - each event is a `Link` with an accessible name: title, weekday, date, time range, source
    name.
- Month:
  - three entries per cell, then "+N weitere", which navigates to `view=day`;
  - arrow keys move focus between cells.
- "Keine Termine" only when `complete && !capped` and every selected source covers the range
  (`covers`); otherwise the existing unknown text. `capped` shows a notice.

- [ ] **Step 1: Failing tests:**
  - default view `week` on desktop;
  - the URL changes on view switch and on next;
  - "+N weitere" appears with five events on one day;
  - an event link's name contains the time range;
  - the empty-state rule (incomplete source → no "Keine Termine");
  - the capped notice after ten pages;
  - the list view still renders the agenda (existing tests).
- [ ] **Step 2: Implement.** Run `cd apps/web && bun test src/calendar src/routes`.
  Expected: PASS, including `routes/no-raw-controls.test.ts` and `ds/floating.test.tsx`.
- [ ] **Step 3: Commit.** `feat(calendar): month, week, day and list views`.

### Task G3: Mobile behaviour

**Files:** `TimeGrid.tsx`, `MonthView.tsx`, `CalendarView.tsx`, `calendar.css`, tests.

- [ ] **Step 1: Failing tests** (`useBreakpoint` mocked to `mobile`):
  - default `day`;
  - a seven-day strip above the grid with the selected day pressed;
  - month cells show dots and the selected day's list below the grid;
  - tap targets carry the 44 px class under `pointer: coarse`, following `CalendarPage.test.tsx`
    line 21.
- [ ] **Step 2: Implement.** Run `bun test src/calendar`. Expected: PASS.
- [ ] **Step 3: Commit.** `feat(calendar): mobile day and month views`.

---

## Package U: dialogs, detail and card (after B and G are integrated)

### Task U1: Live detail with edit and delete

**Files:** modify `apps/web/src/calendar/CalendarPage.tsx` (`CalendarDetail`) and `de.ts`.
Create `CalendarDetail.test.tsx`.

**Interfaces:**
- Consumes: generated `calendarOccurrenceLive`, `calendarEventDelete`.

**Behaviour:**
- The detail loads the live view, showing location and description as text.
- When `editable` and the source has `write`: "Bearbeiten" and "Löschen".
- Otherwise "Nur lesbar" with the German reason text per reason code, and "In Google Kalender
  öffnen" (external link) when `html_link` is present.
- "Löschen" opens a confirm dialog stating "kann nicht garantiert rückgängig gemacht werden".
- After `done`: invalidate the `calendar` queries and navigate to `/calendar` with the same
  search params.

- [ ] **Step 1: Failing tests:**
  - read-only reasons for a series and for guests;
  - the delete flow calls the client with `expected_revision` from `live.revision`;
  - 409 `calendar_event_changed` shows the current values and no success.
- [ ] **Step 2: Implement.** Run `bun test src/calendar`. Expected: PASS.
- [ ] **Step 3: Commit.** `feat(calendar): live detail with edit and delete`. Body: `Part of #23.`

### Task U2: New and edit dialog

**Files:** create `apps/web/src/calendar/EventDialog.tsx` and `EventDialog.test.tsx`. Modify
`CalendarView.tsx` (wire `onSlot`, "+ Termin") and `de.ts`.

**Interfaces:**
- Consumes: generated `calendarEventCreate`, `calendarEventUpdate`, `calendarWriteCheck`,
  `calendarWriteGet`.
- Produces: `EventDialog({ mode: 'create' | 'edit', initial, sources, onClose })`.

**Behaviour:**
- `write_id = crypto.randomUUID()` is generated once per dialog open.
- Fields:
  - calendar (writable sources only; create only);
  - title;
  - "Ganztägig";
  - date;
  - start and end, or end date shown inclusive and sent exclusive (+1 day);
  - the browser zone shown as text;
  - location;
  - description.
- Edit sends only changed fields. Clearing location or description sends `""`. An HTML
  description shows a hint that formatting is lost when the description is edited.
- States:
  - saving: buttons disabled;
  - done: close and invalidate the `calendar` queries;
  - 409 changed: show current values with "Übernehmen und neu bearbeiten", which reloads
    `live` and gives a new `write_id`;
  - 202 unknown: "Wird geprüft …" with "Prüfen" calling `calendarWriteCheck`;
  - `not_applied`: "Erneut versuchen" with a new `write_id`;
  - other codes: German fixed texts.
- Validation in the dialog: end after start, matching the server.

- [ ] **Step 1: Failing tests:**
  - a slot click prefills one hour;
  - the month cell prefills all day;
  - the inclusive end becomes exclusive in the request (`2026-11-20` shown → `end_date` `2026-11-21`);
  - double submit sends the same `write_id` twice at most and shows one result;
  - "Erneut versuchen" appears only after `not_applied`;
  - unknown → check → done closes;
  - edit sends only changed fields.
- [ ] **Step 2: Implement.** Run `bun test src/calendar && bun run check`. Expected: PASS.
- [ ] **Step 3: Commit.** `feat(calendar): create and edit appointments`. Body: `Part of #23.`

### Task U3: Calendar card in the chat

**Files:** create `apps/web/src/chat/CalendarProposal.tsx`, `calendar-proposal.css` and
`CalendarProposal.test.tsx`. Modify `ProposalCard.tsx` (dispatch by kind) and `de.ts`.

**Behaviour:**
- The card shows calendar name, title, date, start and end or "Ganztägig", the timezone, and
  location and description. For updates it shows before and after side by side.
- Delete shows the "not guaranteed undoable" text.
- Confirm uses the existing confirm call.
- Status `unknown` shows "Prüfen" (`chatProposalCheck`).
- Result `calendar_event_changed` asks to request a new proposal.
- After confirm, invalidate the `calendar` queries.

- [ ] **Step 1: Failing tests:**
  - before and after for an update;
  - the delete warning;
  - unknown → check;
  - no confirm button on a non-pending card.
- [ ] **Step 2: Implement.** Run `bun test src/chat`. Expected: PASS.
- [ ] **Step 3: Commit.** `feat(chat): calendar proposal card`. Body: `Part of #23.`

---

## Package C: lead agent

### Task C1: Calendar grid issue

- [ ] Create the issue from `.github/ISSUE_TEMPLATE/02-change.yml` fields, in English:
  - title `calendar: month, week and day grid instead of the agenda list`;
  - body from the spec's Part 4;
  - label `enhancement`.

  Use its number in G commits (`Part of #<n>`) and in the PR (`Closes #<n>`).

### Task C2: Integrate packages

- [ ] Integrate serially. Per package:
  - collect the agent's commits;
  - review them;
  - get a review from another model family (for B, two reviews from different families);
  - cherry-pick onto `feat/welle-6`;
  - confirm with `git cherry` that every commit arrived, then release the clone.
- [ ] Resolve overlaps:
  - `test_mcp_exposure.py`: D's marker, B's sets;
  - the `de.ts` calendar section: G, then U;
  - the generated client: always regenerate after integrating B.

### Task C3: English calendar documentation

- [ ] AGENTS.md "Calendar domain":
  - replace the read-only Google statement and the #23 `BLOCKED` line with the write design
    (capability, editable, write records, statuses, error codes, the unknown resolution,
    retention);
  - add the new endpoints to the API table;
  - add `calendar_write` to the domain model list.
- [ ] DESIGN.md: a calendar subsection under §7 (views per breakpoint, dialog states). Add the
  calendar card under §9.2.

### Task C4: Probe report

- [ ] Write `docs/superpowers/probes/2026-11-18-google-calendar-write-probe.md` from the spec's
  probe section. Add it to the index in `docs/superpowers/README.md`.

### Task C5: End-to-end run against "liam-e TEST"

- [ ] A scratchpad script (not committed) runs `writes.execute` and `writes.check` live:
  - create;
  - a changed-in-between conflict (update via the connector directly, then
    `execute(update, expected_revision=old)` → `calendar_event_changed`);
  - update;
  - delete;
  - a create whose `google_write.call` is wrapped to raise a timeout after the real call
    succeeded → `unknown` → `check` → `done`.

  It requires the calendar to be empty before and after, and prints codes only.

### Task C6: Gate, reviews, PR

- [ ] Full gate:
  - `bash tools/uv.sh run --no-sync pytest tests apps/api/tests -q`;
  - the PG suites with `RUN_PG_CONTRACT=1`;
  - `cd apps/web && bun run test`;
  - `bash tools/gen-types.sh --check`;
  - `bun run check`;
  - `git diff --check`.
- [ ] A whole-branch review from another model family before the PR.
- [ ] One PR. It names #67, #66, #23 and the grid issue with their closing keywords, the section
  mapping, the probe summary, and the "not checked" list.

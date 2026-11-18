# Writing through the Google Calendar connector (2026-11-18)

This is the write probe for #23. On 2026-11-18 the controller called the Studio connector
`google_calendar` directly. It used only an empty calendar named "liam-e TEST", which the owner
created for this purpose. The probe scripts printed key names, types, booleans and synthetic
dates only. No calendar ID, event ID, email address or provider text was recorded, and none
appears here. Afterwards the test calendar held 0 events again.

The checked-in tests use invented fixtures shaped like these results. They prove that the app
processes these shapes, not how a real Google account behaves.

## Decision

The owner chose write path A: write through the connector, with safeguards in the app. The
connector has no precondition and no idempotency key, so the app provides both:

- an atomic claim on a persisted write record (`calendar_write`);
- a live comparison of the provider `updated` value right before each change or delete;
- a classification of every tool result into done, failed or unknown;
- a read-back that resolves an unknown outcome.

The remaining risk is a change in Google between the live check and the write. It is named in
the dialog and on the card and is not hidden.

## Tool schemas (read without calendar data)

- `create_event`:
  - Takes `summary`, `startTime` and `endTime` (required), and `calendarId`, `description`,
    `location`, `allDay`, `timeZone` and `notificationLevel`.
  - Also takes attendees, recurrence, reminders, Meet, colour and visibility; the app uses none
    of these.
  - Has no client ID and no request ID.
- `update_event`:
  - Takes `eventId` (required) and `calendarId`, plus the fields to change and
    `notificationLevel`.
  - Has no etag, no If-Match and no sequence number.
  - Cannot move an event to another calendar.
- `delete_event`: takes `eventId`, `calendarId` and `notificationLevel` (default `NONE`).
- `get_event`: takes `eventId` and `calendarId`.

## Live results

| Check | Result |
| --- | --- |
| Find the test calendar | found exactly once by its name, `accessRole` `owner` in the event listing, 0 events |
| Timed create with location and description | full event JSON with `id`, `updated`, `htmlLink`, `created`, `organizer.self`, `eventType` |
| Update of the title only | title changed, location and description kept, `updated` changed |
| `updated` in the update response | equal to a following `get_event` |
| `location: ""` and `description: ""` | both `null` afterwards |
| Timed → all-day (`allDay: true`, midnight UTC start and end) | stored as an all-day event with an exclusive end date |
| All-day → timed (`allDay: false`, local times with `timeZone`) | stored as a timed event in that zone |
| All-day create 12-05 to 12-06 | one day; the end date is exclusive, as in listings |
| All-day create with start equal to end | accepted and stored as a zero-length day |
| Delete | full event JSON; a following `get_event` returns `status: cancelled` |
| Second delete of the same event | error text |
| Final listing | 0 events |

## Errors

- Errors arrive as HTTP 200 with `isError` absent and a plain-text result instead of JSON:
  `Google Calendar request failed (HTTP <code>, reason <reason>, not applied): …`.
- Observed: 404 `notFound` (update, delete and get of an unknown event) and 400
  `timeRangeEmpty` (create with end before start).
- An unexpected argument returns a validation-error text, also with HTTP 200.

## Consequences for the implementation

- **No read-back after a successful write:** the response carries `updated`, which becomes
  the next expected revision.
- **Text classification:**
  - Only a text that says `not applied` with a 4xx status, or a validation-error text, counts
    as a definite failure.
  - 5xx, transport errors, timeouts and any other text count as unknown and are never retried
    automatically.
- **Exclusive end date:** the app sends the exclusive end date for all-day events and rejects
  end ≤ start itself, because the connector does not.
- **Delete check:** a later check treats `status: cancelled` as a completed delete.
- **No notifications:** every write sends `notificationLevel: "NONE"`.
- **Read path finding (not changed in this task):** the existing read path's HTTP 401/403
  mapping in `live_call` never sees connector failures, because they arrive as HTTP 200 text.
  Reads report them as `provider_unavailable`.

## Not probed

- A calendar shared with the role `writer`, events with other attendees, series instances and
  birthday or other special event types. The test calendar was empty and owned.
  - The editability rules come from the keys in the responses and the schema, not from live
    behaviour on such events.
- The behaviour when a write succeeds at Google but the response is lost. The probe could not
  provoke this; the unknown path is tested with fakes.
- Rate limits and quotas.

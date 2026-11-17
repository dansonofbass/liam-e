"""Hand-written expectations, never a parser as the test oracle; all data synthetic."""

import asyncio
import json
from dataclasses import asdict
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from api.calendar import ics, sync
from api.calendar.adapters import Event, normalize
from api.calendar.ics_fetch import FetchResult

FIXTURES = Path(__file__).parent / "fixtures" / "ics"


def instant(value):
    return datetime.fromisoformat(value).replace(tzinfo=UTC)


def feed(properties):
    return ("BEGIN:VCALENDAR\nVERSION:2.0\nBEGIN:VEVENT\nUID:example@example.org\n"
            + properties + "\nEND:VEVENT\nEND:VCALENDAR\n").encode()


def summary(snapshot):
    return [(r.title, str(r.start_at or r.start_date), str(r.end_at or r.end_date)) for r in snapshot.occurrences]


@pytest.mark.anyio
async def test_hand_written_calendar_instances_and_inert_content():
    result = await ics.parse((FIXTURES / "calendar.ics").read_bytes(), instant("2026-03-28"),
                             instant("2026-04-05"), fallback_zone="Europe/Berlin")
    assert result.complete
    assert summary(result) == [
        ("Three days", "2026-03-28", "2026-03-31"),
        ("Morning meeting", "2026-03-28 08:00:00+00:00", "2026-03-28 09:00:00+00:00"),
        ("Floating time", "2026-03-29 08:00:00+00:00", "2026-03-29 09:00:00+00:00"),
        ("UTC time", "2026-03-29 11:00:00+00:00", "2026-03-29 11:30:00+00:00"),
        ("Moved meeting", "2026-03-29 12:00:00+00:00", "2026-03-29 14:00:00+00:00"),
        ("Morning meeting", "2026-04-01 07:00:00+00:00", "2026-04-01 08:00:00+00:00"),
        ("Morning meeting", "2026-04-04 07:00:00+00:00", "2026-04-04 08:00:00+00:00"),
    ]
    assert all(normalize(row) == row for row in result.occurrences)
    stored = json.dumps([asdict(e) for e in result.events])
    assert "BEGIN:" not in stored and "do-not-fetch" not in stored and "Never execute" not in stored
    master = next(e.recurrence["master"] for e in result.events if e.title == "Three days")
    assert master["description"] == "First line\nSecond line" and master["location"] == "Example hall"
    assert "execute tools" in next(e.recurrence["master"]["description"] for e in result.events if e.title == "UTC time")


@pytest.mark.anyio
async def test_custom_vtimezone_exact_instances():
    result = await ics.parse((FIXTURES / "custom-zone.ics").read_bytes(), instant("2026-03-28"),
                             instant("2026-04-01"), fallback_zone="UTC")
    assert [r.start_at for r in result.occurrences] == [instant(v) for v in [
        "2026-03-28T08:00:00", "2026-03-29T07:00:00", "2026-03-30T07:00:00", "2026-03-31T07:00:00"]]
    assert all(r.timezone == "UTC" and normalize(r) == r for r in result.occurrences)
    assert "Example/Custom" in result.events[0].recurrence["zones"]


@pytest.mark.anyio
@pytest.mark.parametrize("name", ["calendar.ics", "custom-zone.ics", "rules.ics", "all-day.ics"])
async def test_json_roundtrip_reexpansion_without_raw_ics(name):
    body = (FIXTURES / name).read_bytes()
    a = await ics.parse(body, instant("2026-03-28"), instant("2026-03-29"), fallback_zone="Europe/Berlin")
    stored = [Event(**e) for e in json.loads(json.dumps([asdict(e) for e in a.events]))]
    b = await ics.reexpand(stored, instant("2026-03-29"), instant("2026-05-01"))
    direct = await ics.parse(body, instant("2026-03-29"), instant("2026-05-01"), fallback_zone="Europe/Berlin")
    assert b == direct


@pytest.mark.anyio
async def test_monthly_bysetpos_dst_gap_count_and_until():
    result = await ics.parse((FIXTURES / "rules.ics").read_bytes(), instant("2026-01-01"),
                             instant("2026-05-01"), fallback_zone="UTC")
    assert [r.start_date for r in result.occurrences if r.title == "Last weekday"] == [
        date(2026, 1, 30), date(2026, 2, 27), date(2026, 3, 31), date(2026, 4, 30)]
    assert [r.start_at for r in result.occurrences if r.title.startswith("Skip")] == [instant(v) for v in [
        "2026-03-28T01:30:00", "2026-03-30T00:30:00", "2026-03-31T00:30:00"]]
    assert [r.start_at for r in result.occurrences if r.title == "Inclusive UNTIL"] == [instant(v) for v in [
        "2026-03-28T08:00:00", "2026-03-29T08:00:00", "2026-03-30T08:00:00"]]


@pytest.mark.anyio
async def test_moved_identity_uses_original_and_moves_across_window():
    body = (FIXTURES / "calendar.ics").read_bytes()
    moved = body.replace(b"20260329T140000", b"20260402T140000")
    original = await ics.parse(body, instant("2026-03-29"), instant("2026-03-30"), fallback_zone="UTC")
    later = await ics.parse(moved, instant("2026-04-02"), instant("2026-04-03"), fallback_zone="UTC")
    assert len(later.occurrences) == 1
    assert later.occurrences[0].external_id == next(r.external_id for r in original.occurrences if r.title == "Moved meeting")
    earlier = await ics.parse(moved, instant("2026-03-29"), instant("2026-03-30"), fallback_zone="UTC")
    assert "Moved meeting" not in [r.title for r in earlier.occurrences]
    assert len({r.external_id for r in earlier.occurrences}) == len(earlier.occurrences)


@pytest.mark.anyio
@pytest.mark.parametrize(("ending", "end"), [("DURATION:P1D", "2026-03-29T10:00:00"),
    ("DURATION:PT24H", "2026-03-29T11:00:00"),
    ("DTEND;TZID=Europe/Berlin:20260329T120000", "2026-03-29T10:00:00")])
async def test_nominal_day_versus_exact_duration(ending, end):
    result = await ics.parse(feed("DTSTART;TZID=Europe/Berlin:20260328T120000\n" + ending),
                             instant("2026-03-28"), instant("2026-03-30"), fallback_zone="UTC")
    assert result.occurrences[0].start_at == instant("2026-03-28T11:00:00")
    assert result.occurrences[0].end_at == instant(end)


@pytest.mark.anyio
async def test_floating_until_and_ambiguous_first_offset():
    result = await ics.parse(feed("DTSTART:20261024T023000\nDURATION:PT30M\nRRULE:FREQ=DAILY;UNTIL=20261026T023000"),
                             instant("2026-10-24"), instant("2026-10-27"), fallback_zone="Europe/Berlin")
    assert [r.start_at for r in result.occurrences] == [instant(v) for v in [
        "2026-10-24T00:30:00", "2026-10-25T00:30:00", "2026-10-26T01:30:00"]]


@pytest.mark.anyio
@pytest.mark.parametrize("properties", [
    "DTSTART:20260328T120000Z\nDURATION:PT1H\nRRULE:FREQ=DAILY;COUNT=2;COUNT=3",
    "DTSTART:20260328T120000Z\nDURATION:PT1H\nRRULE:FREQ=DAILY;",
    "DTSTART:20260328T120000Z\nDURATION:PT1H\nRRULE:FREQ=DAILY;BYMONTH=13",
    "DTSTART:20260328T120000Z\nDURATION:PT1H\nRRULE:FREQ=DAILY;COUNT=0",
    "DTSTART:20260328T120000Z\nDURATION:PT1H\nRRULE:FREQ=DAILY;COUNT=2;UNTIL=20260401T000000Z",
    "DTSTART:20260328T120000Z\nDURATION:PT1H\nRRULE:FREQ=YEARLY;RSCALE=HEBREW",
    "DTSTART:20260328T120000Z\nDURATION:PT1H\nRDATE;VALUE=PERIOD:20260329T120000Z/PT2H",
    "DTSTART:20260328T120000Z\nDURATION:PT1H\nEXRULE:FREQ=DAILY",
    "DTSTART:20260328T120000Z\nDURATION:PT1H\nRECURRENCE-ID;RANGE=THISANDFUTURE:20260328T120000Z",
    "DTSTART;TZID=Unknown/Example:20260328T120000\nDURATION:PT1H",
    "DTSTART;TZID=Europe/Berlin:20260329T023000\nDURATION:PT1H",
    "DTSTART;TZID=Europe/Berlin:20260329T023000Z\nDURATION:PT1H",
    "DTSTART:20260328T120000Z\nDTSTART:20260329T120000Z\nDURATION:PT1H",
    "DTSTART:20260328T120000Z\nDTEND:20260328T130000Z\nDURATION:PT1H",
    "DTSTART;VALUE=DATE:20260328\nDURATION:PT1H",
    "DTSTART:20260328T120000Z\nDURATION:-PT1H",
    "DTSTART:20260328T120000Z\nDURATION:PT1Hgarbage",
    "DTSTART:20260328T120000Z\nDURATION:PT1H\nEXDATE;VALUE=DATE:20260329",
    "DTSTART:20260328T120000Z\nDURATION:PT1H\nRECURRENCE-ID:20260329T120000Z",
    "DTSTART;VALUE=DATE:20260328\nDTEND;VALUE=DATE:20260328",
    "DTSTART:20260328T120000Z\nDTEND:20260328T110000Z",
])
async def test_invalid_or_unsupported_semantics_fail_without_partial_snapshot(properties, caplog):
    with pytest.raises(ics.ICSError) as caught:
        await ics.parse(feed(properties), instant("2026-03-01"), instant("2026-04-01"), fallback_zone="UTC")
    assert str(caught.value) in {"invalid_format", "unsupported_semantics"}
    assert not caught.value.__cause__ and "example.org" not in str(caught.value) + caplog.text


@pytest.mark.anyio
@pytest.mark.parametrize("mutation", ["duplicate_master", "duplicate_exception", "orphan_exception", "malformed_envelope", "unknown_zone"])
async def test_conflicting_components_fail_whole_feed(mutation):
    body = (FIXTURES / "calendar.ics").read_bytes()
    if mutation == "duplicate_master":
        event = body[body.index(b"BEGIN:VEVENT"):body.index(b"END:VEVENT") + len(b"END:VEVENT")]
        body = body.replace(b"END:VCALENDAR", event + b"\nEND:VCALENDAR")
    elif mutation == "duplicate_exception":
        offset = body.index(b"RECURRENCE-ID")
        begin = body.rfind(b"BEGIN:VEVENT", 0, offset)
        end = body.index(b"END:VEVENT", offset) + len(b"END:VEVENT")
        body = body.replace(b"END:VCALENDAR", body[begin:end] + b"\nEND:VCALENDAR")
    elif mutation == "orphan_exception":
        body = body.replace(b"RECURRENCE-ID;TZID=Europe/Berlin:20260329T090000", b"RECURRENCE-ID;TZID=Europe/Berlin:20260329T100000")
    elif mutation == "malformed_envelope":
        body += b"SUMMARY:unattached\n"
    else:
        body = body.replace(b"Europe/Berlin", b"Unknown/Example")
    with pytest.raises(ics.ICSError, match="invalid_format"):
        await ics.parse(body, instant("2026-03-28"), instant("2026-04-05"), fallback_zone="UTC")


@pytest.mark.anyio
@pytest.mark.parametrize("property", ["METHOD:CANCEL", "METHOD:REQUEST", "CALSCALE:EXAMPLE"])
async def test_scheduling_and_unknown_calendar_scale_fail_closed(property):
    body = feed("DTSTART;VALUE=DATE:20260101").replace(b"VERSION:2.0", b"VERSION:2.0\n" + property.encode())
    with pytest.raises(ics.ICSError, match="unsupported_semantics"):
        await ics.parse(body, instant("2026-01-01"), instant("2026-01-02"), fallback_zone="UTC")


@pytest.mark.anyio
async def test_window_alignment_and_default():
    assert ics.default_window(date(2026, 3, 1)) == (instant("2026-01-30"), instant("2026-08-28"))
    for start, end in [(datetime(2026, 1, 1), instant("2026-02-01")),
                       (instant("2026-01-01T01:00:00"), instant("2026-02-01")),
                       (instant("2026-02-01"), instant("2026-01-01"))]:
        with pytest.raises(ics.ICSError, match="invalid_window"):
            await ics.parse(feed("DTSTART;VALUE=DATE:20260101"), start, end, fallback_zone="UTC")


@pytest.mark.anyio
async def test_component_and_expansion_limits():
    with pytest.raises(ics.ICSError, match="component_limit"):
        await ics.parse((FIXTURES / "calendar.ics").read_bytes(), instant("2026-03-28"), instant("2026-04-05"),
                        fallback_zone="UTC", limits=ics.Limits(components=3))
    with pytest.raises(ics.ICSError, match="expansion_limit"):
        await ics.parse(feed("DTSTART:20260101T000000Z\nDURATION:PT1S\nRRULE:FREQ=SECONDLY"),
                        instant("2026-01-01"), instant("2026-01-02"), fallback_zone="UTC")


@pytest.mark.anyio
async def test_adapter_200_and_304_reexpand_and_dispatch_contract(monkeypatch):
    async def fetch(*args, **kwargs):
        return FetchResult("ok", body=(FIXTURES / "calendar.ics").read_bytes())
    monkeypatch.setattr(ics, "fetch", fetch)
    adapter = ics.ICSAdapter("https://calendar.example.org/test-only", "Europe/Berlin")
    start, end = instant("2026-03-28"), instant("2026-04-05")
    result = await adapter.snapshot("source", start, end)
    assert "test-only" not in repr(adapter)
    async def not_modified(*args, **kwargs):
        return FetchResult("not_modified")
    monkeypatch.setattr(ics, "fetch", not_modified)
    with pytest.raises(ics.ICSError, match="missing_cached_components"):
        await adapter.snapshot("source", start, end)
    adapter.previous_events = result.events
    assert await adapter.snapshot("source", start, end) == result
    # Exercise the actual shared dispatch's normalization/window checks, no DB.
    from types import SimpleNamespace
    async def source(identifier):
        return SimpleNamespace(id=identifier, provider="test-ics", is_active=True)
    calls = []
    async def replace(**kwargs):
        calls.append(kwargs)
    monkeypatch.setattr(sync.calendar_source, "get", source)
    monkeypatch.setattr(sync, "replace_window", replace)
    monkeypatch.setitem(sync._adapters, "test-ics", adapter)
    await sync.run_sync({"source_id": "source", "start": start.isoformat(), "end": end.isoformat()}, "job", 1)
    assert len(calls[0]["occurrences"]) == 7


@pytest.fixture
def children(monkeypatch):
    real = asyncio.create_subprocess_exec
    children = []
    async def create(*args, **kwargs):
        child = await real(*args, **kwargs)
        children.append(child)
        return child
    monkeypatch.setattr(asyncio, "create_subprocess_exec", create)
    return children


@pytest.mark.anyio
async def test_all_day_exceptions_rdates_and_exclusive_overlap():
    body = (FIXTURES / "all-day.ics").read_bytes()
    result = await ics.parse(body, instant("2026-01-01"), instant("2026-02-04"), fallback_zone="UTC")
    assert [(r.title, r.start_date, r.end_date) for r in result.occurrences] == [
        ("Two days", date(2026, 1, 1), date(2026, 1, 3)),
        ("Two days", date(2026, 1, 7), date(2026, 1, 9)),
        ("Moved days", date(2026, 2, 1), date(2026, 2, 3)),
    ]
    overlap = await ics.reexpand(result.events, instant("2026-01-02"), instant("2026-01-03"))
    assert len(overlap.occurrences) == 1 and overlap.occurrences[0] == result.occurrences[0]
    after = await ics.reexpand(result.events, instant("2026-01-03"), instant("2026-01-04"))
    assert not after.occurrences


@pytest.mark.anyio
async def test_full_component_limit_counts_ignored_components():
    for count, succeeds in [(9999, True), (10000, False)]:
        body = b"BEGIN:VCALENDAR\nVERSION:2.0\n" + b"BEGIN:VTODO\nEND:VTODO\n" * count + b"END:VCALENDAR\n"
        if succeeds:
            result = await ics.parse(body, instant("2026-01-01"), instant("2026-01-02"), fallback_zone="UTC")
            assert result.complete and not result.events
        else:
            with pytest.raises(ics.ICSError, match="component_limit"):
                await ics.parse(body, instant("2026-01-01"), instant("2026-01-02"), fallback_zone="UTC")


@pytest.mark.anyio
async def test_cpu_limit_reaps_child(children):
    body = feed("DTSTART:19000101T000000Z\nDURATION:PT1S\nRRULE:FREQ=SECONDLY;BYMONTH=2;BYMONTHDAY=30")
    with pytest.raises(ics.ICSError, match="parser_resource_limit"):
        await ics.parse(body, instant("2026-01-01"), instant("2026-02-01"), fallback_zone="UTC",
                        limits=ics.Limits(cpu_seconds=1, wall_seconds=4))
    reaped(children)


def reaped(children):
    import os
    assert len(children) == 1 and children[0].returncode is not None
    with pytest.raises(ProcessLookupError):
        os.kill(children[0].pid, 0)
    with pytest.raises(ChildProcessError):
        os.waitpid(children[0].pid, os.WNOHANG)
    assert children[0].stdin.is_closing()


@pytest.mark.anyio
async def test_pathological_expansion_wall_timeout_reaps_child_and_keeps_loop_live(children):
    # No matching candidate until the far future: a yielded-occurrence counter
    # cannot bound this. The actual dateutil loop must be killed by the parent.
    body = feed("DTSTART:19000101T000000Z\nDURATION:PT1S\nRRULE:FREQ=SECONDLY;BYMONTH=2;BYMONTHDAY=30")
    ticks = 0
    async def ticker():
        nonlocal ticks
        while True:
            ticks += 1
            await asyncio.sleep(0.005)
    heartbeat = asyncio.create_task(ticker())
    try:
        with pytest.raises(ics.ICSError, match="parser_timeout"):
            await ics.parse(body, instant("2026-01-01"), instant("2026-02-01"), fallback_zone="UTC",
                            limits=ics.Limits(wall_seconds=0.4))
    finally:
        heartbeat.cancel()
        await asyncio.gather(heartbeat, return_exceptions=True)
    assert ticks > 5
    reaped(children)


@pytest.mark.anyio
async def test_caller_cancellation_reaps_child(children):
    body = feed("DTSTART:19000101T000000Z\nDURATION:PT1S\nRRULE:FREQ=SECONDLY;BYMONTH=2;BYMONTHDAY=30")
    task = asyncio.create_task(ics.parse(body, instant("2026-01-01"), instant("2026-02-01"), fallback_zone="UTC"))
    while not children:
        await asyncio.sleep(0.005)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    reaped(children)


@pytest.mark.anyio
async def test_fifty_thousand_occurrences_succeed_and_release_pipes(children):
    result = await ics.parse(feed("DTSTART:20260101T000000Z\nDURATION:PT1S\nRRULE:FREQ=SECONDLY;COUNT=50000"),
                             instant("2026-01-01"), instant("2026-01-02"), fallback_zone="UTC")
    assert len(result.occurrences) == 50000
    assert result.occurrences[0].start_at == instant("2026-01-01T00:00:00")
    assert result.occurrences[-1].start_at == instant("2026-01-01T13:53:19")
    reaped(children)
    assert children[0].stdout.at_eof()


@pytest.mark.anyio
async def test_rdate_utc_spelling_keeps_nominal_master_zone():
    result = await ics.parse(feed("DTSTART;TZID=Europe/Berlin:20260320T120000\nDURATION:P1D\nRDATE:20260328T110000Z"),
                             instant("2026-03-28"), instant("2026-03-30"), fallback_zone="UTC")
    assert len(result.occurrences) == 1
    assert result.occurrences[0].start_at == instant("2026-03-28T11:00:00")
    assert result.occurrences[0].end_at == instant("2026-03-29T10:00:00")


@pytest.mark.anyio
async def test_actual_fetch_to_parser_pipeline(monkeypatch):
    from api.calendar import ics_fetch
    import httpx
    async def resolve(host):
        return ["8.8.8.8"]
    class Stream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield (FIXTURES / "custom-zone.ics").read_bytes()
    transport = httpx.MockTransport(lambda request: httpx.Response(
        200, headers={"content-type": "text/calendar"}, stream=Stream()))
    async def fetch(url, **kwargs):
        return await ics_fetch.fetch(url, resolver=resolve, transport=transport, **kwargs)
    monkeypatch.setattr(ics, "fetch", fetch)
    adapter = ics.ICSAdapter("https://calendar.example.org/test-only", "UTC")
    result = await adapter.snapshot("source", instant("2026-03-28"), instant("2026-04-01"))
    assert len(result.occurrences) == 4 and result.complete
    assert result.occurrences[1].start_at == instant("2026-03-29T07:00:00")


@pytest.mark.anyio
@pytest.mark.parametrize("ending", ["", "DTEND;TZID=Europe/Berlin:20260105T090000", "DURATION:PT0S"])
async def test_timed_points_do_not_reject_other_events(ending):
    body = feed("DTSTART;TZID=Europe/Berlin:20260105T090000\n" + ending).replace(
        b"END:VCALENDAR", b"BEGIN:VEVENT\nUID:other@example.org\nDTSTART;VALUE=DATE:20260105\nEND:VEVENT\nEND:VCALENDAR")
    result = await ics.parse(body, instant("2026-01-05"), instant("2026-01-06"), fallback_zone="UTC")
    assert len(result.occurrences) == 2
    point = next(row for row in result.occurrences if row.start_at is not None)
    assert point.start_at == point.end_at == instant("2026-01-05T08:00:00")


@pytest.mark.anyio
async def test_recurring_points_and_window_boundaries():
    body = feed("DTSTART:20260105T000000Z\nRRULE:FREQ=DAILY;COUNT=3\nRDATE:20260108T000000Z")
    result = await ics.parse(body, instant("2026-01-06"), instant("2026-01-08"), fallback_zone="UTC")
    assert [row.start_at for row in result.occurrences] == [instant("2026-01-06"), instant("2026-01-07")]
    assert all(row.start_at == row.end_at for row in result.occurrences)


@pytest.mark.anyio
async def test_memory_budget_fails_closed_and_reaps_child(children):
    # A lower test-only ceiling, with input large enough to exceed it while parsing.
    body = feed("DTSTART;VALUE=DATE:20260101\nDESCRIPTION:" + "x" * (3 * 1024 * 1024))
    with pytest.raises(ics.ICSError, match="memory_limit|parser_resource_limit"):
        await ics.parse(body, instant("2026-01-01"), instant("2026-01-02"), fallback_zone="UTC",
                        limits=ics.Limits(memory_bytes=32 * 1024 * 1024))
    reaped(children)

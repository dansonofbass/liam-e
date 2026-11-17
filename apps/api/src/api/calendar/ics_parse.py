"""Strict RFC 5545 subset and normalized recurrence model, used ONLY in the worker.

icalendar handles content lines, escaped/folded text, typed values and VTIMEZONE;
python-dateutil handles RRULE iteration in local calendar time. The fixture corpus
covers these libraries together, rather than trusting a second expansion wrapper.
Lazy dateutil iteration avoids an eager wrapper's unbounded between() allocation.
We validate around their permissive parsers: duplicate supported properties/components,
unknown recurrence extensions, RANGE, EXRULE and period-valued RDATE fail closed.
Dateutil's invalid DST candidates are skipped before counting COUNT (RFC 5545).

Schema 1 stores typed local/date/UTC starts, exact or nominal durations, canonical
rule fields, exception components and structured zone observances, never raw ICS.
Custom VTIMEZONE instants use UTC in the shared contract (which requires ZoneInfo
names); the original zone and its definition remain in Event.recurrence.
VTODO/VALARM/ATTACH and transport/HTML metadata are inert and not retained.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from dateutil.rrule import rrulestr
from icalendar import Calendar, Timezone, TimezoneDaylight, TimezoneStandard, vRecur
from icalendar.parser import Contentlines
from icalendar.prop.dt.duration import DURATION_REGEX

from api.calendar.adapters import Event, Occurrence, Snapshot, normalize

MAX_COMPONENTS = 10_000
MAX_OCCURRENCES = 50_000
RULE_KEYS = {"FREQ", "UNTIL", "COUNT", "INTERVAL", "BYSECOND", "BYMINUTE", "BYHOUR",
             "BYDAY", "BYMONTHDAY", "BYYEARDAY", "BYWEEKNO", "BYMONTH", "BYSETPOS", "WKST"}


class InvalidICS(ValueError):
    """Fixed error codes only; never attach parser exceptions."""


def fail(code="invalid_format"):
    raise InvalidICS(code)


def window(start: datetime, end: datetime):
    if any(v.tzinfo is None or v.utcoffset() is None for v in (start, end)):
        fail("invalid_window")
    start, end = start.astimezone(UTC), end.astimezone(UTC)
    if start >= end or any(v.time() != time() for v in (start, end)):
        fail("invalid_window")
    return start, end


def _one(component, name, required=False):
    value = component.get(name)
    if isinstance(value, list) or (required and value is None):
        fail()
    return value


def _rule(value, raw):
    if value is None:
        return None
    if value.params:
        fail("unsupported_semantics")
    # The library accepts duplicate keys and malformed trailing fields. Reject
    # those before using its typed rule; this is not a replacement RRULE grammar.
    pairs = raw.split(";")
    keys = [p.split("=", 1)[0].upper() for p in pairs]
    if any(p.count("=") != 1 for p in pairs) or len(set(keys)) != len(keys):
        fail()
    if set(value) - RULE_KEYS or "FREQ" not in value or ("COUNT" in value and "UNTIL" in value):
        fail("unsupported_semantics")
    for key in ("COUNT", "INTERVAL"):
        if key in value and (len(value[key]) != 1 or int(value[key][0]) <= 0):
            fail()
    if any(int(v) == 60 for v in value.get("BYSECOND", [])):
        fail("unsupported_semantics")
    ranges = {"BYSECOND": (0, 59), "BYMINUTE": (0, 59), "BYHOUR": (0, 23),
              "BYMONTH": (1, 12), "BYMONTHDAY": (-31, 31), "BYYEARDAY": (-366, 366),
              "BYWEEKNO": (-53, 53), "BYSETPOS": (-366, 366)}
    for key, (low, high) in ranges.items():
        if any(not low <= int(v) <= high or (low < 0 and int(v) == 0) for v in value.get(key, [])):
            fail()
    frequency = value["FREQ"]
    if len(frequency) != 1 or frequency[0] not in {"SECONDLY", "MINUTELY", "HOURLY", "DAILY", "WEEKLY", "MONTHLY", "YEARLY"}:
        fail()
    frequency = frequency[0]
    if ("BYWEEKNO" in value and frequency != "YEARLY"
            or "BYYEARDAY" in value and frequency in {"DAILY", "WEEKLY", "MONTHLY"}
            or "BYMONTHDAY" in value and frequency == "WEEKLY"):
        fail()
    for day in value.get("BYDAY", []):
        if day.relative is not None and (not 1 <= abs(day.relative) <= 53
                or frequency not in {"MONTHLY", "YEARLY"} or "BYWEEKNO" in value):
            fail()
    canonical = value.to_ical().decode("ascii")
    # Strings preserve library types such as UNTIL and ordinal weekdays.
    return dict(part.split("=", 1) for part in canonical.split(";"))


def _rule_text(rule):
    return ";".join(f"{k}={v}" for k, v in rule.items())


def _preflight(body, limit):
    stack, raw_events, raw_zones = [], [], []
    components = 0
    active = None
    for line in Contentlines.from_ical(body.decode("utf-8", errors="strict")):
        if not line:
            continue
        name, params, value = line.raw_parts()
        name = name.upper()
        if name in ("BEGIN", "END") and params:
            fail()
        if name in ("DTSTART", "DTEND", "RECURRENCE-ID", "EXDATE", "RDATE") and "TZID" in params and value.endswith("Z"):
            fail()
        if name == "BEGIN":
            components += 1
            if components > limit:
                fail("component_limit")
            kind = value.upper()
            if not stack:
                if kind != "VCALENDAR" or components != 1:
                    fail()
            elif (stack[-1], kind) not in {("VCALENDAR", "VEVENT"), ("VCALENDAR", "VTIMEZONE"),
                    ("VCALENDAR", "VTODO"), ("VEVENT", "VALARM"), ("VTODO", "VALARM"),
                    ("VTIMEZONE", "STANDARD"), ("VTIMEZONE", "DAYLIGHT")}:
                fail("unsupported_semantics")
            stack.append(kind)
            if kind in ("VEVENT", "STANDARD", "DAYLIGHT"):
                active = {}
                (raw_events if kind == "VEVENT" else raw_zones).append(active)
        elif name == "END":
            if not stack or stack.pop() != value.upper():
                fail()
            if value.upper() in ("VEVENT", "STANDARD", "DAYLIGHT"):
                active = None
        elif not stack:
            fail()
        elif active is not None and stack[-1] in ("VEVENT", "STANDARD", "DAYLIGHT"):
            active.setdefault(name, []).append(value)
    if stack or not components:
        fail()
    return raw_events, raw_zones


def _temporal(prop):
    if prop is None or not hasattr(prop, "dt"):
        fail()
    params = dict(prop.params)
    if set(params) - {"VALUE", "TZID"}:
        fail("unsupported_semantics")
    value = prop.dt
    declared = params.get("VALUE")
    if type(value) is date:
        if declared not in (None, "DATE") or "TZID" in params:
            fail()
        return {"kind": "date", "value": value.isoformat()}
    if not isinstance(value, datetime) or declared not in (None, "DATE-TIME"):
        fail("unsupported_semantics")
    zone = params.get("TZID")
    if zone:
        return {"kind": "local", "zone": str(zone), "value": value.replace(tzinfo=None).isoformat()}
    if value.tzinfo is not None:
        return {"kind": "utc", "value": value.astimezone(UTC).isoformat()}
    return {"kind": "floating", "value": value.isoformat()}


def _dates(component, name):
    values = component.get(name, [])
    if not isinstance(values, list):
        values = [values]
    result = []
    for value in values:
        for item in value.dts:
            item.params = value.params
            result.append(_temporal(item))
    return result


def _zones(calendar, raw_zones):
    result, raw_iter = {}, iter(raw_zones)
    for zone in calendar.subcomponents:
        if zone.name != "VTIMEZONE":
            continue
        identifier = str(_one(zone, "TZID", True))
        if not identifier or identifier in result or not zone.subcomponents:
            fail()
        observances = []
        for sub in zone.subcomponents:
            raw = next(raw_iter)
            if sub.name not in ("STANDARD", "DAYLIGHT") or set(sub) - {
                "DTSTART", "TZOFFSETFROM", "TZOFFSETTO", "RRULE", "RDATE", "TZNAME", "COMMENT"}:
                fail("unsupported_semantics")
            start = _temporal(_one(sub, "DTSTART", True))
            dates = _dates(sub, "RDATE")
            if start["kind"] != "floating" or any(d["kind"] != "floating" for d in dates):
                fail()
            rule = _rule(_one(sub, "RRULE"), raw.get("RRULE", [None])[0])
            observances.append({"kind": sub.name, "start": start["value"],
                "from": int(_one(sub, "TZOFFSETFROM", True).td.total_seconds()),
                "to": int(_one(sub, "TZOFFSETTO", True).td.total_seconds()),
                "rule": rule, "dates": [d["value"] for d in dates]})
        if len({obs["start"] for obs in observances}) != len(observances):
            fail()
        result[identifier] = observances
    return result


def _zone_map(definitions):
    result = {}
    for identifier, observances in definitions.items():
        zone = Timezone()
        zone.add("TZID", identifier)
        for obs in observances:
            item = TimezoneStandard() if obs["kind"] == "STANDARD" else TimezoneDaylight()
            item.add("DTSTART", datetime.fromisoformat(obs["start"]))
            item.add("TZOFFSETFROM", timedelta(seconds=obs["from"]))
            item.add("TZOFFSETTO", timedelta(seconds=obs["to"]))
            if obs["rule"]:
                item.add("RRULE", vRecur.from_ical(_rule_text(obs["rule"])))
            if obs["dates"]:
                item.add("RDATE", [datetime.fromisoformat(d) for d in obs["dates"]])
            zone.add_component(item)
        result[identifier] = zone.to_tz(lookup_tzid=False)
    return result


def _value(value, zones, fallback):
    kind = value["kind"]
    if kind == "date":
        return date.fromisoformat(value["value"])
    dt = datetime.fromisoformat(value["value"])
    if kind == "utc":
        return dt.astimezone(UTC)
    name = value.get("zone", fallback)
    zone = zones.get(name)
    if zone is None:
        zone = ZoneInfo(name)
    return dt.replace(tzinfo=zone, fold=0)


def _exists(dt):
    return not isinstance(dt, datetime) or dt.astimezone(UTC).astimezone(dt.tzinfo).replace(tzinfo=None) == dt.replace(tzinfo=None)


def _key(value):
    return "T:" + value.astimezone(UTC).isoformat() if isinstance(value, datetime) else "D:" + value.isoformat()


def _id(uid, key):
    return hashlib.sha256(json.dumps([uid, key], ensure_ascii=True).encode()).hexdigest()


def _component(component, raw, zones, fallback):
    if any(name in component for name in ("EXRULE", "RSCALE")):
        fail("unsupported_semantics")
    uid = str(_one(component, "UID", True))
    if not uid:
        fail()
    status = str(_one(component, "STATUS") or "CONFIRMED").upper()
    if status not in ("TENTATIVE", "CONFIRMED", "CANCELLED"):
        fail()
    rid = _one(component, "RECURRENCE-ID")
    result = {"uid": uid, "status": status,
              "summary": str(_one(component, "SUMMARY") or ""),
              "description": str(_one(component, "DESCRIPTION") or ""),
              "location": str(_one(component, "LOCATION") or ""),
              "rid": _temporal(rid) if rid is not None else None}
    start = _one(component, "DTSTART")
    if start is None and status == "CANCELLED" and rid is not None:
        start = rid
    result["start"] = _temporal(start)
    dt = _value(result["start"], zones, fallback)
    if not _exists(dt):
        fail()
    end, duration = _one(component, "DTEND"), _one(component, "DURATION")
    if end is not None and duration is not None:
        fail()
    if end is not None:
        encoded = _temporal(end)
        finish = _value(encoded, zones, fallback)
        if type(finish) is not type(dt) or not _exists(finish):
            fail()
        delta = finish.astimezone(UTC) - dt.astimezone(UTC) if isinstance(dt, datetime) else finish - dt
        result["duration"] = {"mode": "exact", "days": 0, "seconds": int(delta.total_seconds())}
    elif duration is not None:
        if set(duration.params) - {"VALUE"} or duration.params.get("VALUE", "DURATION") != "DURATION":
            fail("unsupported_semantics")
        # Preserve P1D versus PT24H: timedelta alone loses nominal-day semantics.
        match = DURATION_REGEX.fullmatch(raw["DURATION"][0])
        if not match or match.group(1) == "-":
            fail()
        _, weeks, days, hours, minutes, seconds = match.groups()
        result["duration"] = {"mode": "nominal", "days": int(weeks or 0) * 7 + int(days or 0),
            "seconds": int(hours or 0) * 3600 + int(minutes or 0) * 60 + int(seconds or 0)}
    elif type(dt) is date or status == "CANCELLED":
        result["duration"] = {"mode": "nominal", "days": 1, "seconds": 0}
    else:
        # The shared snapshot interval contract cannot represent instantaneous events.
        fail("unsupported_semantics")
    length = result["duration"]
    if length["days"] * 86400 + length["seconds"] <= 0:
        fail()
    if type(dt) is date and length["seconds"] % 86400:
        fail()
    rule = _rule(_one(component, "RRULE"), raw.get("RRULE", [None])[0])
    if rid is not None and any(name in component for name in ("RRULE", "RDATE", "EXDATE")):
        fail("unsupported_semantics")
    if type(dt) is date and rule and set(rule) & {"BYHOUR", "BYMINUTE", "BYSECOND"}:
        fail("unsupported_semantics")
    result.update(rule=rule, rdates=_dates(component, "RDATE"), exdates=_dates(component, "EXDATE"))
    for value in result["rdates"] + result["exdates"] + ([result["rid"]] if rid else []):
        decoded = _value(value, zones, fallback)
        if type(decoded) is not type(dt) or not _exists(decoded):
            fail()
    return result


def parse_components(body: bytes, fallback: str, component_limit=MAX_COMPONENTS):
    ZoneInfo(fallback)  # Explicit, never the process-local timezone.
    raw_events, raw_zones = _preflight(body, component_limit)
    calendar = Calendar.from_ical(body)
    if calendar.name != "VCALENDAR" or str(_one(calendar, "VERSION", True)) != "2.0":
        fail()
    if (str(_one(calendar, "METHOD") or "PUBLISH").upper() != "PUBLISH"
            or str(_one(calendar, "CALSCALE") or "GREGORIAN").upper() != "GREGORIAN"):
        fail("unsupported_semantics")
    if any(component.errors for component in calendar.walk()):
        fail()
    # Calendar objects contain data only. No URL, attachment or alarm is followed.
    definitions = _zones(calendar, raw_zones)
    zones = _zone_map(definitions)
    groups = {}
    for component, raw in zip([c for c in calendar.subcomponents if c.name == "VEVENT"], raw_events, strict=True):
        item = _component(component, raw, zones, fallback)
        groups.setdefault(item["uid"], []).append(item)
    events = []
    for uid, items in groups.items():
        masters = [item for item in items if item["rid"] is None]
        if len(masters) != 1:
            fail()
        master = masters[0]
        exceptions = [item for item in items if item["rid"] is not None]
        if exceptions and not (master["rule"] or master["rdates"]):
            fail()
        keys = [_key(_value(item["rid"], zones, fallback)) for item in exceptions]
        if len(set(keys)) != len(keys):
            fail()
        # Repeat only referenced custom zones, not every zone per event.
        referenced = {v["zone"] for item in items for v in
                      [item["start"], item["rid"], *item["rdates"], *item["exdates"]]
                      if v is not None and "zone" in v}
        events.append(Event(_id(uid, "master"), master["summary"], {
            "version": 1, "fallback": fallback, "master": master, "exceptions": exceptions,
            "zones": {name: definitions[name] for name in referenced if name in definitions},
        }))
    return events


def _finish(start, duration):
    days, seconds = duration["days"], duration["seconds"]
    if type(start) is date:
        return start + timedelta(days=days, seconds=seconds)
    nominal = start + timedelta(days=days)
    if not _exists(nominal):
        fail()
    return (nominal.astimezone(UTC) + timedelta(seconds=seconds)).astimezone(start.tzinfo)


def _candidates(master, zones, fallback, until, spend):
    start = _value(master["start"], zones, fallback)
    yield start
    if master["rule"]:
        rule = dict(master["rule"])
        count = int(rule.pop("COUNT")) if "COUNT" in rule else None
        initial = datetime.combine(start, time()) if type(start) is date else start
        if type(start) is date and "UNTIL" in rule:
            # dateutil represents DATE recurrences as naive midnight datetimes.
            if len(rule["UNTIL"]) != 8:
                fail()
            rule["UNTIL"] += "T000000"
        elif master["start"]["kind"] == "floating" and "UNTIL" in rule:
            if len(rule["UNTIL"]) != 15:
                fail()
            local_until = datetime.strptime(rule["UNTIL"], "%Y%m%dT%H%M%S").replace(tzinfo=initial.tzinfo)
            if not _exists(local_until):
                fail()
            rule["UNTIL"] = local_until.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
        iterator = rrulestr(_rule_text(rule), dtstart=initial, cache=False)
        valid, first = 0, True
        for candidate in iterator:
            if count is not None and valid >= count:
                break
            value = candidate.date() if type(start) is date else candidate
            if first:
                if value != start:
                    fail()  # RFC 5545 leaves a non-matching DTSTART undefined.
                first = False
            if value >= until:
                break
            spend()
            if not _exists(value):
                continue
            valid += 1
            yield value
        if first:
            fail()
    for value in master["rdates"]:
        spend()
        extra = _value(value, zones, fallback)
        # RDATE may spell an instant in UTC or another TZID. Nominal durations
        # still use the master's calendar zone, not that alternative spelling.
        yield extra.astimezone(start.tzinfo) if isinstance(extra, datetime) else extra


def expand(events: list[Event], start: datetime, end: datetime, occurrence_limit=MAX_OCCURRENCES):
    start, end = window(start, end)
    if len({event.external_id for event in events}) != len(events):
        fail()
    rows, spent = [], 0

    def spend():
        nonlocal spent
        spent += 1
        if spent > occurrence_limit:
            fail("expansion_limit")

    for event in events:
        data = event.recurrence
        if data["version"] != 1:
            fail("unsupported_semantics")
        master, exceptions, fallback = data["master"], data["exceptions"], data["fallback"]
        zones = _zone_map(data["zones"])
        initial = _value(master["start"], zones, fallback)
        exception_map = {_key(_value(item["rid"], zones, fallback)): item for item in exceptions}
        if len(exception_map) != len(exceptions) or event.external_id != _id(master["uid"], "master"):
            fail()
        for item in exceptions:
            if item["uid"] != master["uid"] or type(_value(item["rid"], zones, fallback)) is not type(initial):
                fail()
        excluded = {_key(_value(d, zones, fallback)) for d in master["exdates"]}
        # Validate exception membership even when its original lies outside the window;
        # process moved starts independently, so moves into/out of the window work.
        until = end.date() if type(initial) is date else end
        for item in exceptions:
            rid = _value(item["rid"], zones, fallback)
            until = max(until, rid + timedelta(days=1))
        seen, matched = set(), set()
        for original in _candidates(master, zones, fallback, until, spend):
            key = _key(original)
            if key in seen:
                continue
            seen.add(key)
            if not master["rule"] and key == _key(initial):
                spend()
            override = exception_map.get(key)
            if override:
                matched.add(key)
            item = override or master
            if master["status"] == "CANCELLED" or item["status"] == "CANCELLED" or (key in excluded and not override):
                continue
            actual = _value(item["start"], zones, fallback) if override else original
            finish = _finish(actual, item["duration"])
            if not _exists(actual):
                fail()
            recurring = bool(master["rule"] or master["rdates"] or exceptions)
            identity = _id(master["uid"], key if recurring else "master")
            if type(actual) is date:
                row = Occurrence(identity, event.external_id, item["summary"], start_date=actual, end_date=finish)
                overlaps = actual < end.date() and finish > start.date()
            else:
                zone_name = item["start"].get("zone", fallback if item["start"]["kind"] == "floating" else "UTC")
                if zone_name in zones:
                    zone_name = "UTC"
                row = Occurrence(identity, event.external_id, item["summary"], start_at=actual,
                                 end_at=finish, timezone=zone_name)
                overlaps = actual.astimezone(UTC) < end and finish.astimezone(UTC) > start
            row = normalize(row)
            if overlaps:
                rows.append(row)
        if matched != set(exception_map):
            fail()
    if len(rows) > occurrence_limit or len({row.external_id for row in rows}) != len(rows):
        fail("expansion_limit")
    rows.sort(key=lambda row: (row.start_at or datetime.combine(row.start_date, time(), UTC), row.external_id))
    return Snapshot(events, rows, True)

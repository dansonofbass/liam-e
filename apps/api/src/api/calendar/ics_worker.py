"""Private exec worker. stdin/stdout carry bounded JSON, never diagnostics."""

import json
import sys


def main():
    # Set hard ceilings before importing parser libraries or decoding the payload.
    try:
        import resource
        resource.setrlimit(resource.RLIMIT_AS, (256 * 1024 * 1024,) * 2)
        resource.setrlimit(resource.RLIMIT_CPU, (5, 5))
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    except Exception:
        sys.stdout.write('{"error":"isolation_unavailable"}')
        return
    import logging
    import warnings
    logging.disable(sys.maxsize)
    warnings.simplefilter("ignore")

    def no_network(event, args):
        if event.startswith("socket."):
            raise ValueError("network_disabled")
    sys.addaudithook(no_network)
    try:
        import base64
        from dataclasses import asdict
        from datetime import date, datetime
        from api.calendar.ics_parse import InvalidICS, expand, parse_components, window
        from api.calendar.adapters import Event

        raw = sys.stdin.buffer.read(16 * 1024 * 1024 + 1)
        if len(raw) > 16 * 1024 * 1024:
            raise InvalidICS("input_limit")
        payload = json.loads(raw)
        limits = payload["limits"]
        resource.setrlimit(resource.RLIMIT_AS, (limits["memory_bytes"],) * 2)
        resource.setrlimit(resource.RLIMIT_CPU, (limits["cpu_seconds"],) * 2)
        start, end = window(datetime.fromisoformat(payload["start"]), datetime.fromisoformat(payload["end"]))
        if "body" in payload:
            body = base64.b64decode(payload["body"], validate=True)
            if len(body) > 5 * 1024 * 1024:
                raise InvalidICS("input_limit")
            events = parse_components(body, payload["fallback"], limits["components"])
        else:
            events = [Event(**item) for item in payload["events"]]
            zones = {}
            for event in events:
                for name, definition in event.recurrence["zones"].items():
                    if name in zones and zones[name] != definition:
                        raise InvalidICS("invalid_format")
                    zones[name] = definition
            count = (1 + len(events) + sum(len(e.recurrence["exceptions"]) for e in events)
                     + len(zones) + sum(len(definition) for definition in zones.values()))
            if count > limits["components"]:
                raise InvalidICS("component_limit")
        snapshot = expand(events, start, end, limits["occurrences"])

        def encode(value):
            if isinstance(value, (date, datetime)):
                return value.isoformat()
            raise ValueError("invalid_output")

        output = json.dumps(asdict(snapshot), default=encode, ensure_ascii=True)
        if len(output) > 32 * 1024 * 1024:
            raise InvalidICS("output_limit")
    except MemoryError:
        output = '{"error":"memory_limit"}'
    except Exception as exc:
        # Never serialize library exception messages, reprs or tracebacks.
        code = str(exc) if type(exc).__name__ == "InvalidICS" else "invalid_format"
        if code not in {"invalid_format", "unsupported_semantics", "invalid_window",
                        "component_limit", "expansion_limit", "input_limit", "output_limit"}:
            code = "invalid_format"
        output = json.dumps({"error": code})
    sys.stdout.write(output)


if __name__ == "__main__":
    main()

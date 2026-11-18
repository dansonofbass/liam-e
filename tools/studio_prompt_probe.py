"""Can the app read one fixed version of a Studio prompt (#37, phase 1)?

Offline by default: prints the probe plan and runs nothing. With ``--live`` it sends read-only
``GET`` requests to the Mistral prompt registry (``/v2/prompts``, beta) with the app's own
credential (``utils.mistral``) and prints one redacted line per case. It never prints prompt names,
titles, descriptions, contents, ids or tokens; for a fixed version only key names, the sharing
scope, the number of variables and the content length.

    bash tools/uv.sh run --no-sync python tools/studio_prompt_probe.py --live
    bash tools/uv.sh run --no-sync python tools/studio_prompt_probe.py --live --prompt-id <id> --version 1

``--prompt-id`` must name a synthetic prompt released for this probe. The probe never creates,
changes, shares or deletes a prompt.
"""

from __future__ import annotations

import argparse
import re
import sys
import uuid
from dataclasses import dataclass
from typing import NoReturn

LIST_PAGE_SIZE = 1
TIMEOUT_SECONDS = 15.0
# One path segment: a registry id or a `prompt:<name>` reference. No dots, slashes, queries or fragments.
PROMPT_ID = re.compile(r"^[A-Za-z0-9_:-]{1,128}$")


@dataclass(frozen=True)
class Outcome:
    label: str
    status: int | str
    detail: str = ""

    def line(self) -> str:
        return f"{self.label}: {self.status}" + (f" {self.detail}" if self.detail else "")


def summarize_list(body: object) -> str:
    """Count and key names of a list page; never values."""
    if not isinstance(body, dict):
        return "body=not-an-object"
    items = body.get("data")
    count = len(items) if isinstance(items, list) else "?"
    first = sorted(items[0].keys()) if isinstance(items, list) and items and isinstance(items[0], dict) else []
    return f"keys={sorted(body.keys())} items={count} next={bool(body.get('nextPageToken'))} item_keys={first}"


def summarize_version(body: object) -> str:
    """Shape of one prompt version: key names, sharing scope, variable count and content length."""
    if not isinstance(body, dict):
        return "body=not-an-object"
    raw = body.get("definition")
    definition: dict = raw if isinstance(raw, dict) else {}
    content = definition.get("content")
    variables = definition.get("variables")
    scope = body.get("sharingScope", body.get("sharing_scope"))
    scope = scope if scope in ("private", "workspace", "sharing_scope_unspecified") else ("other" if scope else None)
    return (f"keys={sorted(body.keys())} version={'int' if isinstance(body.get('version'), int) else '?'} "
            f"sharing_scope={scope} variables={len(variables) if isinstance(variables, list) else 0} "
            f"content_chars={len(content) if isinstance(content, str) else '?'}")


def run_live(prompt_id: str | None, version: int | None) -> list[Outcome]:
    import httpx
    from utils.mistral import mistral_api_url, mistral_app_token

    base = mistral_api_url().rstrip("/")
    key = mistral_app_token()
    outcomes = []

    def get(client: httpx.Client, label: str, path: str, summary=None, **params) -> None:
        try:
            response = client.get(path, params=params or None)
        except httpx.TimeoutException as exc:
            outcomes.append(Outcome(label, f"timeout:{type(exc).__name__}"))
            return
        except httpx.HTTPError as exc:
            outcomes.append(Outcome(label, f"transport:{type(exc).__name__}"))
            return
        detail = ""
        if summary and response.status_code == 200:
            try:
                detail = summary(response.json())
            except ValueError:
                detail = "body=not-json"
        outcomes.append(Outcome(label, response.status_code, detail))

    auth = {"Authorization": f"Bearer {key}"}
    with httpx.Client(base_url=base, headers=auth, timeout=TIMEOUT_SECONDS) as client:
        get(client, "list, page size 1", "/v2/prompts", summarize_list, pageSize=LIST_PAGE_SIZE)
        missing = str(uuid.uuid4())
        get(client, "unknown prompt", f"/v2/prompts/{missing}")
        get(client, "unknown prompt, version 1", f"/v2/prompts/{missing}/versions/1")
        if prompt_id and version is not None:
            get(client, "fixed version", f"/v2/prompts/{prompt_id}/versions/{version}", summarize_version)
            get(client, "missing version", f"/v2/prompts/{prompt_id}/versions/{version + 10_000}")
    with httpx.Client(base_url=base, headers={"Authorization": "Bearer invalid-test-only"}, timeout=TIMEOUT_SECONDS) as client:
        get(client, "invalid key", "/v2/prompts", pageSize=LIST_PAGE_SIZE)
    with httpx.Client(base_url=base, headers=auth, timeout=0.001) as client:
        get(client, "1 ms client timeout", "/v2/prompts", pageSize=LIST_PAGE_SIZE)
    return outcomes


class _QuietParser(argparse.ArgumentParser):
    """Reports a fixed usage error; argparse would echo argument values, which can be URLs or tokens."""

    def error(self, message: str) -> NoReturn:
        self.exit(2, "invalid arguments; see --help\n")


def main(argv: list[str] | None = None) -> int:
    parser = _QuietParser(description="Read-only capability probe for Studio prompt versions")
    parser.add_argument("--live", action="store_true", help="send the read-only requests")
    parser.add_argument("--prompt-id", help="id of a synthetic prompt released for this probe")
    parser.add_argument("--version", type=int, help="fixed version number to read")
    args = parser.parse_args(argv)
    if (args.prompt_id is None) != (args.version is None):
        print("--prompt-id and --version go together", file=sys.stderr)
        return 2
    if args.prompt_id is not None and (not PROMPT_ID.match(args.prompt_id) or args.version < 1):
        print("--prompt-id must be one id segment and --version a positive number", file=sys.stderr)
        return 2
    if not args.live:
        print("Offline. --live reads (GET only): /v2/prompts?pageSize=1, an unknown prompt and version,"
              " optionally one fixed version, with an invalid key and with a 1 ms timeout.")
        return 0
    try:
        outcomes = run_live(args.prompt_id, args.version)
    except Exception as exc:  # noqa: BLE001 - exception texts can carry a URL, token path or id
        print(f"probe_failed: {type(exc).__name__}", file=sys.stderr)
        return 1
    for outcome in outcomes:
        print(outcome.line())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

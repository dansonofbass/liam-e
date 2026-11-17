"""Tracked files stay publishable: no private identifiers of the owner or of the environment.

liam-e is meant to become public (AGENTS.md, section "Veröffentlichung und private Daten"). These
checks cover what a secret scanner does not look for: the Mistral tenant IDs outside the
`mistral.json` that deploys need, links to private claude.ai resources, absolute home paths, and
mail addresses that could belong to a real person. Credentials are the job of gitleaks
(`.gitleaks.toml`, CI job `secrets`).

The checks read `git ls-files`, so they see exactly what a clone would publish. Tenant IDs and
private links are looked for in every tracked text file. The address and home-path heuristics
skip lock files, the generated API client and vendored agent skills, which nobody writes by hand
and which hold upstream examples.
"""

from __future__ import annotations

import json
import re
import subprocess
from functools import cache
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

SKIPPED_PREFIXES = (".agents/", ".mistral/", "apps/web/src/api/generated/")
SKIPPED_NAMES = {"bun.lock", "uv.lock", "package-lock.json"}

# Domains that can never reach a real mailbox (RFC 2606, RFC 6761), plus the pseudo-domain that
# api/mail connector accounts get when the connector names no sender address.
RESERVED_DOMAINS = ("example.com", "example.net", "example.org", "connector.mistral")
RESERVED_SUFFIXES = (".example", ".test", ".invalid", ".localhost")
# Local parts that name nobody. Provider presets (gmail.com, icloud.com, ...) are configuration,
# and tests that exercise them use one of these.
SYNTHETIC_LOCAL_PART = re.compile(r"^(?:[a-z]|me|test|user|noreply|no-reply)$")

ADDRESS = re.compile(r"(?<![\w.%+-])([A-Za-z0-9._%+-]+)@((?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,})(?![\w.-]*\w)")
HOME_PATH = re.compile(r"(?<![\w.~-])/(?:home|Users)/[A-Za-z_][\w.-]*(?![\w-])")
# One or two backslashes: a plain path or one escaped in JSON or a string literal.
WINDOWS_HOME = re.compile(r"(?i)(?<![\w])[a-z]:\\{1,2}Users\\{1,2}[^\\\s\"'<>]+")
# The host must be claude.ai itself: after "//" (with a scheme or protocol-relative, but not a
# doubled slash inside another URL's path), or standing alone (not a path segment or the tail of
# another host). Hosts are case-insensitive.
PRIVATE_LINK = re.compile(
    r"(?i)(?:(?<=//)(?<![\w.-]//)|(?<![\w./-]))(?:www\.)?claude\.ai/(?:artifact|chat|code|project|public|share)/[a-z0-9_-]+"
)
# Paths that look like a home directory but are not one, such as a web route under "/home". Each
# entry is (file, the whole path as written there) with a comment saying why it is harmless. The
# same path in another file, or a longer path that starts with it, is still reported.
NOT_HOME_PATHS: frozenset[tuple[str, str]] = frozenset()
WHOLE_PATH = re.compile(r"[^\s\"'`<>()\[\]{},;]+")
DEPLOYMENT_KEYS = ("organizationId", "workspaceId", "appId")


@cache
def tracked_texts(*, everything: bool = False) -> dict[str, str]:
    try:
        listing = subprocess.run(
            ["git", "ls-files", "-z"], cwd=ROOT, check=True, capture_output=True
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        listing = b""
    if not listing:
        pytest.skip("not a git checkout")
    texts: dict[str, str] = {}
    for raw in listing.split(b"\0"):
        path = raw.decode()
        if not path:
            continue
        if not everything and (path.startswith(SKIPPED_PREFIXES) or Path(path).name in SKIPPED_NAMES):
            continue
        file = ROOT / path
        if not file.is_file():
            continue
        try:
            texts[path] = file.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
    return texts


def hits(pattern: re.Pattern[str], *, keep=lambda _match: True, everything: bool = False) -> list[str]:
    found = []
    for path, text in tracked_texts(everything=everything).items():
        for number, line in enumerate(text.splitlines(), start=1):
            for match in pattern.finditer(line):
                if keep(match):
                    found.append(f"{path}:{number}: {match.group(0)}")
    return found


def test_tenant_ids_appear_only_in_mistral_json() -> None:
    deployment = json.loads((ROOT / "mistral.json").read_text(encoding="utf-8")).get("deployment", {})
    ids = {key: deployment.get(key) for key in DEPLOYMENT_KEYS}
    # Without the IDs there is nothing to look for, and the test would pass vacuously.
    assert all(isinstance(value, str) and value for value in ids.values()), "mistral.json lacks deployment IDs"
    leaks = [
        f"{path}: {key}"
        for path, text in tracked_texts(everything=True).items()
        if path != "mistral.json"
        for key, value in ids.items()
        if value.lower() in text.lower()
    ]
    assert leaks == [], "Mistral tenant IDs belong in mistral.json only; write <organization-id> etc."


def test_no_links_to_private_claude_resources() -> None:
    assert hits(PRIVATE_LINK, everything=True) == [], "name the artifact or session instead of linking it"


def home_path_hits(texts: dict[str, str], allowed: frozenset[tuple[str, str]]) -> list[str]:
    found = []
    for path, text in texts.items():
        for number, line in enumerate(text.splitlines(), start=1):
            for match in HOME_PATH.finditer(line):
                whole = WHOLE_PATH.match(line, match.start()).group(0)
                if (path, whole) not in allowed:
                    found.append(f"{path}:{number}: {match.group(0)}")
    return found


def test_no_absolute_home_paths() -> None:
    found = home_path_hits(tracked_texts(), NOT_HOME_PATHS) + hits(WINDOWS_HOME)
    assert found == [], "use repository-relative paths or a placeholder; a route is listed in NOT_HOME_PATHS"


def test_home_path_exception_is_bound_to_file_and_whole_path() -> None:
    route = "/home" + "/settings"
    allowed = frozenset({("apps/web/src/routes.ts", route)})
    assert home_path_hits({"apps/web/src/routes.ts": f'route = "{route}"'}, allowed) == []
    assert home_path_hits({"apps/web/src/routes.ts": f'path = "{route}/.ssh/config"'}, allowed) != []
    assert home_path_hits({"docs/notes.md": f'route = "{route}"'}, allowed) != []


def is_personal_address(match: re.Match[str]) -> bool:
    local, domain = match.group(1).lower(), match.group(2).lower()
    if domain in RESERVED_DOMAINS or domain.endswith(RESERVED_SUFFIXES):
        return False
    if any(domain.endswith("." + reserved) for reserved in RESERVED_DOMAINS):
        return False
    return not SYNTHETIC_LOCAL_PART.match(local)


def test_mail_addresses_are_synthetic() -> None:
    assert hits(ADDRESS, keep=is_personal_address) == [], (
        "use an address under example.org/.com/.net or *.test, or a local part like me@ or x@"
    )


@pytest.mark.parametrize(
    ("address", "personal"),
    [
        ("mira.beispiel@example.org", False),
        ("news@shop.example", False),
        ("x@yahoo.com", False),
        ("gmail@connector.mistral", False),
        # Split so that this file, which the scan reads too, holds no personal-looking address.
        ("anna.schmidt" + "@gmail.com", True),
        ("info" + "@some-company.de", True),
    ],
)
def test_address_rule(address: str, personal: bool) -> None:
    match = ADDRESS.search(address)
    assert match is not None
    assert is_personal_address(match) is personal


@pytest.mark.parametrize(
    ("text", "flagged"),
    # Split like the addresses above.
    [
        ("/home" + "/someone/project", True),
        ("/home" + "/someone", True),
        ("/home" + "/_build/project", True),
        ("/Users" + "/someone/x", True),
        ("C:" + "\\Users\\Someone\\project", True),
        ('{"path": "C:' + '\\\\Users\\\\Someone\\\\project"}', True),
        ("~/project", False),
        ("/home/", False),
        ("apps/home/view.tsx", False),
    ],
)
def test_home_path_rule(text: str, flagged: bool) -> None:
    assert bool(HOME_PATH.search(text) or WINDOWS_HOME.search(text)) is flagged


@pytest.mark.parametrize(
    ("text", "flagged"),
    # Split so that this file holds no link the scan would flag.
    [
        ("https://claude" + ".ai/artifact/test-only", True),
        ("https://claude" + ".ai/code/session_test-only", True),
        ("https://claude" + ".ai/chat/00000000-0000-4000-8000-000000000000", True),
        ("https://claude" + ".ai/project/test-only", True),
        ("https://claude" + ".ai/share/test-only", True),
        ("https://CLAUDE" + ".AI/chat/test-only", True),
        ("(see claude" + ".ai/share/test-only)", True),
        ("[chat](//claude" + ".ai/chat/test-only)", True),
        ("//claude" + ".ai/chat/test-only", True),
        ("https://notclaude" + ".ai/artifact/test-only", False),
        ("https://example.org/claude" + ".ai/chat/test-only", False),
        ("https://example.org//claude" + ".ai/chat/test-only", False),
        ("https://sub.claude" + ".ai.example/chat/test-only", False),
        ("https://claude" + ".ai/", False),
    ],
)
def test_private_link_rule(text: str, flagged: bool) -> None:
    assert bool(PRIVATE_LINK.search(text)) is flagged

"""tools/studio_prompt_probe.py stays offline by default and never prints values (#37)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

TOOLS = Path(__file__).resolve().parents[3] / "tools"
SECRET = "test-only-0123456789"
PRIVATE_TEXT = "Private Notiz an someone@example.org"


def load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, TOOLS / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module  # dataclasses resolve their module through sys.modules
    spec.loader.exec_module(module)
    return module


prompts = load("studio_prompt_probe")


def test_offline_by_default_sends_nothing(monkeypatch: pytest.MonkeyPatch,
                                          capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(prompts, "run_live", lambda *a, **k: pytest.fail("offline run reached the network"))
    assert prompts.main([]) == 0
    assert "Offline" in capsys.readouterr().out


def test_prompt_list_summary_has_no_values() -> None:
    body = {"data": [{"id": "p-1", "name": PRIVATE_TEXT, "definition": {"content": SECRET}}], "nextPageToken": "t"}
    summary = prompts.summarize_list(body)
    assert "items=1" in summary and "next=True" in summary
    assert SECRET not in summary and "Notiz" not in summary and "p-1" not in summary


def test_prompt_version_summary_has_shape_only() -> None:
    body = {"id": "p-1", "name": PRIVATE_TEXT, "version": 3, "sharingScope": "private",
            "definition": {"content": "Hallo {{name}} " + SECRET, "variables": [{"name": "name"}]}}
    summary = prompts.summarize_version(body)
    assert "sharing_scope=private" in summary and "variables=1" in summary and "version=int" in summary
    assert SECRET not in summary and "Notiz" not in summary and "Hallo" not in summary


def test_prompt_probe_needs_id_and_version_together(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(prompts, "run_live", lambda *a, **k: pytest.fail("ran with half a target"))
    assert prompts.main(["--live", "--prompt-id", "x"]) == 2


@pytest.mark.parametrize("prompt_id", ["../..", "a/b", "x?y=1", "x#f", "..", "a.b", ""])
def test_prompt_probe_rejects_ids_that_leave_one_path_segment(prompt_id: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(prompts, "run_live", lambda *a, **k: pytest.fail("sent a request for an unsafe id"))
    assert prompts.main(["--live", "--prompt-id", prompt_id, "--version", "1"]) == 2


def test_prompt_probe_rejects_non_positive_versions(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(prompts, "run_live", lambda *a, **k: pytest.fail("sent a request for version 0"))
    assert prompts.main(["--live", "--prompt-id", "prompt:synthetic-test", "--version", "0"]) == 2


def test_prompt_live_failure_prints_no_exception_text(monkeypatch: pytest.MonkeyPatch,
                                                      capsys: pytest.CaptureFixture[str]) -> None:
    def boom(prompt_id: str | None, version: int | None) -> list:
        raise RuntimeError(f"token file /secret/path {SECRET}")

    monkeypatch.setattr(prompts, "run_live", boom)
    assert prompts.main(["--live"]) == 1
    out = capsys.readouterr()
    assert "probe_failed: RuntimeError" in out.err
    for text in (out.out, out.err):
        assert SECRET not in text and "/secret/path" not in text


@pytest.mark.parametrize("argv", [["--live", "--bogus", "https://private.example.org/secret-test-only"],
                                  ["https://private.example.org/secret-test-only"]])
def test_prompts_argument_errors_do_not_echo_values(argv: list[str], capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exit_info:
        prompts.main(argv)
    assert exit_info.value.code == 2
    out = capsys.readouterr()
    for text in (out.out, out.err):
        assert "private.example.org" not in text and "secret-test-only" not in text


def test_prompts_non_numeric_version_is_not_echoed(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        prompts.main(["--live", "--prompt-id", "test-only", "--version", "https://private.example.org/x"])
    out = capsys.readouterr()
    assert "private.example.org" not in out.out + out.err

"""The synthetic probe's argument parser never repeats raw argument values."""

from pathlib import Path
import subprocess
import sys

import pytest


PROBE = Path(__file__).resolve().parents[1] / "tools" / "audio_provider_probe.py"


@pytest.mark.parametrize(
    "argv",
    [
        ("opaque-test-only", "."),
        ("tts", ".", "--opaque-test-only"),
    ],
)
def test_invalid_argv_is_redacted(argv: tuple[str, ...]) -> None:
    result = subprocess.run(
        [sys.executable, str(PROBE), *argv], capture_output=True, text=True, check=False, timeout=5,
    )
    assert result.returncode == 2
    assert result.stdout == ""
    assert result.stderr == "invalid arguments; see --help\n"

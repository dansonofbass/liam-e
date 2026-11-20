"""Exercise the offline duration candidate with generated media and no provider calls."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


PROBE = Path(__file__).resolve().parents[1] / "tools" / "audio_provider_probe.py"
CODECS = {
    "webm": ("-c:a", "libopus"),
    "mp4": ("-c:a", "aac", "-movflags", "frag_keyframe+empty_moov+default_base_moof"),
}


def run_probe(scratch: Path, kind: str, *, search_path: str | None = None) -> tuple[int, dict]:
    env = None if search_path is None else {**os.environ, "PATH": search_path}
    result = subprocess.run(
        [sys.executable, str(PROBE), kind, str(scratch), "--validate-container"],
        capture_output=True, text=True, check=False, timeout=10, env=env,
    )
    assert result.stderr == ""
    return result.returncode, json.loads(result.stdout)


@pytest.fixture(scope="module")
def ffmpeg() -> str:
    executable = shutil.which("ffmpeg")
    parser = shutil.which("ffprobe")
    if executable is None or parser is None:
        pytest.skip("The generated media cases require FFmpeg and FFprobe")
    for tool in (executable, parser):
        protocols = subprocess.check_output([tool, "-hide_banner", "-protocols"], text=True, timeout=5)
        if "fd" not in protocols.split():
            pytest.skip("The generated media cases require the FFmpeg fd protocol")
    encoders = subprocess.check_output([executable, "-hide_banner", "-encoders"], text=True, timeout=5)
    if not {"libopus", "aac", "alac"}.issubset(encoders.split()):
        pytest.skip("The generated media cases require the Opus, AAC and ALAC encoders")
    return executable


def make_audio(ffmpeg: str, path: Path, seconds: float, *options: str) -> None:
    subprocess.run(
        [ffmpeg, "-v", "error", "-f", "lavfi", "-i", f"anullsrc=r=48000:cl=mono:d={seconds}",
         *CODECS[path.suffix[1:]], *options, str(path)],
        check=True, capture_output=True, timeout=10,
    )


@pytest.mark.parametrize("kind", ["webm", "mp4"])
def test_accepts_audio_just_below_the_duration_limit(ffmpeg: str, tmp_path: Path, kind: str) -> None:
    fixture = tmp_path / f"recorded.{kind}"
    make_audio(ffmpeg, fixture, 119.5)

    code, report = run_probe(tmp_path, kind)

    assert code == 0, report
    assert report["status"] == "accepted"
    assert report["bytes"] == fixture.stat().st_size
    assert 119.45 < report["decoded_seconds"] <= 120
    assert 119.45 < report["packet_span_seconds"] <= 120


@pytest.mark.parametrize("kind", ["webm", "mp4"])
def test_rejects_audio_over_the_duration_limit(ffmpeg: str, tmp_path: Path, kind: str) -> None:
    make_audio(ffmpeg, tmp_path / f"recorded.{kind}", 121)

    code, report = run_probe(tmp_path, kind)

    assert code == 1
    assert report["reason"] == "too_long"


def test_rejects_gap_in_webm_without_duration_metadata(ffmpeg: str, tmp_path: Path) -> None:
    make_audio(
        ffmpeg, tmp_path / "recorded.webm", 1.25,
        "-live", "1", "-af", r"asetpts=PTS+gte(T\,0.5)*121/TB",
    )

    code, report = run_probe(tmp_path, "webm")

    assert code == 1
    assert report["reason"] == "too_long"
    assert report["container_duration_seconds"] is None
    assert report["packet_span_seconds"] > 120


def test_rejects_excess_samples_even_when_timestamps_fit(ffmpeg: str, tmp_path: Path) -> None:
    make_audio(ffmpeg, tmp_path / "recorded.webm", 121, "-af", "asetpts=0.5*PTS")

    code, report = run_probe(tmp_path, "webm")

    assert code == 1
    assert report["reason"] == "too_long"
    assert report["packet_span_seconds"] < 120
    assert report["decoded_seconds"] > 120


def test_rejects_padding_past_the_duration_limit(ffmpeg: str, tmp_path: Path) -> None:
    make_audio(ffmpeg, tmp_path / "recorded.webm", 120)

    code, report = run_probe(tmp_path, "webm")

    assert code == 1
    assert report["reason"] == "too_long"
    assert report["container_duration_seconds"] > 120


def test_rejects_an_mp4_declared_as_webm(ffmpeg: str, tmp_path: Path) -> None:
    mp4 = tmp_path / "recorded.mp4"
    make_audio(ffmpeg, mp4, 1.25)
    (tmp_path / "recorded.webm").write_bytes(mp4.read_bytes())

    code, report = run_probe(tmp_path, "webm")

    assert code == 1
    assert report["reason"] == "invalid_container"


def test_rejects_mp4_with_a_different_audio_codec(ffmpeg: str, tmp_path: Path) -> None:
    make_audio(ffmpeg, tmp_path / "recorded.mp4", 1.25, "-c:a", "alac")

    code, report = run_probe(tmp_path, "mp4")

    assert code == 1
    assert report["reason"] == "invalid_container"


def test_rejects_oversize_before_starting_a_parser(tmp_path: Path) -> None:
    with (tmp_path / "recorded.webm").open("wb") as fixture:
        fixture.truncate(10_485_761)

    code, report = run_probe(tmp_path, "webm", search_path="")

    assert code == 1
    assert report["reason"] == "too_large"


@pytest.mark.parametrize(("data", "reason"), [
    (b"", "empty"),
    (b"\x1a\x45\xdf\xa3\xff", "invalid_container"),
])
def test_rejects_empty_and_truncated_inputs(tmp_path: Path, data: bytes, reason: str) -> None:
    (tmp_path / "recorded.webm").write_bytes(data)

    code, report = run_probe(tmp_path, "webm")

    assert code == 1
    assert report["reason"] == reason


def test_rejects_webm_truncated_after_the_header(ffmpeg: str, tmp_path: Path) -> None:
    fixture = tmp_path / "recorded.webm"
    make_audio(ffmpeg, fixture, 4.0)
    with fixture.open("r+b") as audio:
        audio.truncate(fixture.stat().st_size // 2)

    code, report = run_probe(tmp_path, "webm")

    assert code == 1
    assert report["reason"] == "invalid_container"


def test_reports_a_missing_parser_without_echoing_the_path(ffmpeg: str, tmp_path: Path) -> None:
    make_audio(ffmpeg, tmp_path / "recorded.webm", 1.25)

    code, report = run_probe(tmp_path, "webm", search_path=str(tmp_path))

    assert code == 1
    assert report["reason"] == "tool_unavailable"
    assert str(tmp_path) not in json.dumps(report)


def test_times_out_without_exposing_parser_diagnostics(ffmpeg: str, tmp_path: Path) -> None:
    make_audio(ffmpeg, tmp_path / "recorded.webm", 1.25)
    slow_probe = tmp_path / "ffprobe"
    slow_probe.write_text("#!/bin/sh\nprintf 'synthetic-parser-diagnostic\\n' >&2\nexec sleep 8\n")
    slow_probe.chmod(0o700)

    code, report = run_probe(tmp_path, "webm", search_path=f"{tmp_path}{os.pathsep}{os.defpath}")

    assert code == 1
    assert report["reason"] == "timeout"
    assert "synthetic-parser-diagnostic" not in json.dumps(report)

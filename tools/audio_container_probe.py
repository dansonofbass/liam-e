"""Offline candidate size, container and duration checks for synthetic audio fixtures."""

from fractions import Fraction
import json
import os
from pathlib import Path
import subprocess
from typing import BinaryIO


MAX_BYTES = 10 * 1024 * 1024
MAX_SECONDS = 120
MAX_PACKETS = 50_000
PCM_RATE = 48_000
TOOL_TIMEOUT_SECONDS = 3
FORMATS = {"webm": ("matroska", "opus"), "mp4": ("mov", "aac")}
MP4_BRANDS = frozenset({b"isom", b"iso2", b"iso5", b"iso6", b"mp41", b"mp42", b"M4A "})


class _Rejected(ValueError):
    """Carry a fixed reason that can be shown without exposing input data."""


def _read_ebml_number(data: bytes, offset: int, *, size: bool) -> tuple[int, int]:
    first = data[offset]
    width = 9 - first.bit_length()
    end = offset + width
    if first == 0 or end > len(data):
        raise _Rejected("invalid_container")
    value = int.from_bytes(data[offset:end], "big")
    if size:
        value ^= 1 << (7 * width)
    return value, end


def _is_webm(header: bytes) -> bool:
    if not header.startswith(b"\x1a\x45\xdf\xa3"):
        return False
    length, offset = _read_ebml_number(header, 4, size=True)
    end = offset + length
    if end > len(header):
        return False
    header = header[:end]
    doc_type = None
    while offset < end:
        element, offset = _read_ebml_number(header, offset, size=False)
        length, offset = _read_ebml_number(header, offset, size=True)
        item_end = offset + length
        if item_end > end:
            return False
        if element == 0x4282:  # DocType
            if doc_type is not None:
                return False
            doc_type = header[offset:item_end]
        offset = item_end
    return doc_type == b"webm"


def _is_mp4(header: bytes) -> bool:
    size = int.from_bytes(header[:4], "big")
    if header[4:8] != b"ftyp" or not 16 <= size <= len(header) or size % 4:
        return False
    brands = {header[8:12], *(header[offset:offset + 4] for offset in range(16, size, 4))}
    return not MP4_BRANDS.isdisjoint(brands)


def _run(command: list[str], audio: BinaryIO) -> bytes:
    audio.seek(0)
    try:
        process = subprocess.run(
            command, stdin=audio, capture_output=True,
            timeout=TOOL_TIMEOUT_SECONDS, check=True,
        )
    except OSError as exc:
        raise _Rejected("tool_unavailable") from exc
    # Demuxers can report an error, including premature EOF, even when the tool exits with 0.
    if process.stderr:
        raise _Rejected("invalid_container")
    return process.stdout


def _packet_span(packets: list[dict], time_base: Fraction) -> Fraction:
    if not 0 < len(packets) <= MAX_PACKETS or time_base <= 0:
        raise _Rejected("invalid_container")
    timings = [(int(packet["pts"]), int(packet["duration"])) for packet in packets]
    if any(duration <= 0 for _, duration in timings):
        raise _Rejected("invalid_container")
    return (max(start + duration for start, duration in timings) - min(start for start, _ in timings)) * time_base


def _check_audio(audio: BinaryIO, kind: str, report: dict) -> None:
    size = os.fstat(audio.fileno()).st_size
    report["bytes"] = size
    if size == 0:
        raise _Rejected("empty")
    if size > MAX_BYTES:
        raise _Rejected("too_large")
    header = audio.read(1024)
    matches = _is_webm(header) if kind == "webm" else _is_mp4(header)
    if not matches:
        raise _Rejected("invalid_container")

    demuxer, codec = FORMATS[kind]
    input_options = [
        "-v", "error", "-max_alloc", "67108864", "-max_streams", "1", "-threads", "1",
        "-protocol_whitelist", "fd", "-f", demuxer,
    ]
    if kind == "mp4":
        input_options.extend(["-enable_drefs", "0"])
    metadata = json.loads(_run([
        "ffprobe", *input_options, "-read_intervals", f"%+#{MAX_PACKETS + 1}",
        "-show_entries", "packet=pts,duration:stream=codec_type,codec_name,time_base:format=duration",
        "-of", "json", "fd:",
    ], audio))
    streams = metadata["streams"]
    if len(streams) != 1 or streams[0]["codec_type"] != "audio" or streams[0]["codec_name"] != codec:
        raise _Rejected("invalid_container")

    span = _packet_span(metadata["packets"], Fraction(streams[0]["time_base"]))
    duration = metadata["format"].get("duration")
    container_seconds = Fraction(duration) if duration is not None else None
    if container_seconds is not None and container_seconds < 0:
        raise _Rejected("invalid_container")
    report.update(
        packet_span_seconds=float(span),
        container_duration_seconds=float(container_seconds) if container_seconds is not None else None,
    )
    if span > MAX_SECONDS or (container_seconds is not None and container_seconds > MAX_SECONDS):
        raise _Rejected("too_long")

    # Regenerate timestamps from samples so declared or discontinuous timing cannot clip the count.
    pcm = _run([
        "ffmpeg", "-nostdin", "-xerror", *input_options, "-err_detect", "explode", "-i", "fd:",
        "-map", "0:a:0", "-filter_threads", "1", "-af", "asetpts=N/SR/TB",
        "-t", str(MAX_SECONDS + 1), "-ar", str(PCM_RATE), "-ac", "1", "-f", "s16le", "pipe:1",
    ], audio)
    report["decoded_seconds"] = len(pcm) / (2 * PCM_RATE)
    if not pcm:
        raise _Rejected("empty")
    if len(pcm) > 2 * PCM_RATE * MAX_SECONDS:
        raise _Rejected("too_long")


def check_container(kind: str, fixture: Path) -> dict:
    report = {"probe": kind, "mode": "container", "status": "rejected"}
    try:
        if not fixture.is_file():
            raise _Rejected("fixture_unreadable")
        # The child and Python share the descriptor offset. Keep the header read unbuffered.
        with fixture.open("rb", buffering=0) as audio:
            _check_audio(audio, kind, report)
    except _Rejected as exc:
        report["reason"] = str(exc)
    except subprocess.TimeoutExpired:
        report["reason"] = "timeout"
    except (subprocess.CalledProcessError, ValueError, LookupError, TypeError, ZeroDivisionError):
        report["reason"] = "invalid_container"
    except OSError:
        report["reason"] = "fixture_unreadable"
    else:
        report["status"] = "accepted"
    return report

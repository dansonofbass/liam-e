"""Reproduce #26 against Mistral with the app's own credential and disposable synthetic fixtures.

Offline by default. Container validation runs locally. The live probe makes one stateless
provider call and reports fixed status metadata and the outcome of comparing synthetic text
in memory. See the dated audio-capabilities report for the separate browser checks.
"""

import argparse
import base64
from datetime import datetime, timezone
from importlib.metadata import version
import json
from pathlib import Path
import re
import time
from typing import NoReturn

SYNTHETIC = "Eine gelbe Ente schwimmt im Teich."
TRANSCRIPTION_MODEL = "voxtral-mini-transcribe-3"
SPEECH_MODEL = "voxtral-mini-tts-3-0"
PRESET_VOICE = "voice_481"
MAX_SAMPLE_BYTES = 256 * 1024
FIXTURES = {
    "wav": ("synthetic.wav", "audio/wav"),
    "webm": ("recorded.webm", "audio/webm"),
    "mp4": ("recorded.mp4", "audio/mp4"),
}
KNOWN_ERROR_CODES = frozenset({
    "invalid_model", "model_not_found", "unauthorized", "forbidden",
    "rate_limit_exceeded", "invalid_audio_format", "unsupported_audio_format", "invalid_request_error",
})


def run_probe(task: str, scratch: Path, result: dict) -> None:
    import httpx
    from utils.mistral import mistral_app_token

    if task == "tts":
        result.update(path="/v1/audio/speech", requested_model=SPEECH_MODEL, preset=PRESET_VOICE)
        request = {
            "json": {
                "model": SPEECH_MODEL, "voice_id": PRESET_VOICE, "input": SYNTHETIC, "response_format": "mp3",
            }
        }
    else:
        filename, mime = FIXTURES[task]
        with (scratch / filename).open("rb") as file:
            data = file.read(MAX_SAMPLE_BYTES + 1)
        if not 0 < len(data) <= MAX_SAMPLE_BYTES:
            raise ValueError("probe fixture size")
        result.update(path="/v1/audio/transcriptions", requested_model=TRANSCRIPTION_MODEL, bytes=len(data), mime=mime)
        request = {
            "data": {"model": TRANSCRIPTION_MODEL, "language": "de"},
            "files": {"file": (filename, data, mime)},
        }

    token = mistral_app_token()
    with httpx.Client(
        base_url="https://api.mistral.ai", timeout=20, trust_env=False, follow_redirects=False,
    ) as client:
        with client.stream("POST", result["path"], headers={"Authorization": f"Bearer {token}"}, **request) as response:
            result["status"] = response.status_code
            raw = bytearray()
            for chunk in response.iter_bytes():
                if len(raw) + len(chunk) > MAX_SAMPLE_BYTES:
                    raise ValueError("probe response size")
                raw.extend(chunk)

    parsed = json.loads(raw)
    if result["status"] != 200:
        code = (parsed.get("code") or parsed.get("type")) if isinstance(parsed, dict) else None
        result["error"] = code if isinstance(code, str) and code in KNOWN_ERROR_CODES else "unclassified"
        return

    model = parsed.get("model")
    result["returned_model"] = (
        model if isinstance(model, str) and re.fullmatch(r"voxtral-[a-zA-Z0-9._-]{1,80}", model) else None
    )
    if task == "tts":
        audio = base64.b64decode(parsed["audio_data"], validate=True)
        if not audio:
            raise ValueError("empty speech response")
        result["bytes"] = len(audio)
        with (scratch / "output.mp3").open("xb") as file:
            file.write(audio)
    else:
        normalized = parsed["text"].strip().lower().rstrip(".")
        result["exact_text_match"] = normalized == SYNTHETIC.lower().rstrip(".")
        seconds = (parsed.get("usage") or {}).get("prompt_audio_seconds")
        result["provider_audio_seconds"] = seconds if isinstance(seconds, (int, float)) else None


class _QuietParser(argparse.ArgumentParser):
    """Emit fixed usage errors because argparse can echo argument values."""

    def error(self, message: str) -> NoReturn:
        self.exit(2, "invalid arguments; see --help\n")


def main() -> int:
    parser = _QuietParser(description="Probe Mistral speech APIs with synthetic data")
    parser.add_argument("task", choices=("tts", *FIXTURES))
    parser.add_argument("scratch", type=Path, help="private scratch directory holding synthetic fixtures")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--live", action="store_true", help="send one synthetic request to the official Mistral API")
    mode.add_argument("--validate-container", action="store_true", help="check a synthetic WebM or MP4 fixture locally")
    args = parser.parse_args()
    if args.validate_container:
        from audio_container_probe import FORMATS, check_container

        if args.task not in FORMATS:
            parser.error("a WebM or MP4 fixture is required")
        report = check_container(args.task, args.scratch / FIXTURES[args.task][0])
        print(json.dumps(report))
        return int(report["status"] != "accepted")
    if not args.live:
        print("Offline. Use --validate-container for a local check or --live for one synthetic request.")
        return 0

    started = time.monotonic()
    result = {
        "probe": args.task,
        "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "installed_sdk": version("mistralai"),
    }
    try:
        run_probe(args.task, args.scratch, result)
    except Exception as exc:
        # SDK and HTTP errors can include request or response data.
        result["probe_exception"] = type(exc).__name__
    result["elapsed_ms"] = round((time.monotonic() - started) * 1000)
    print(json.dumps(result))
    return int("probe_exception" in result or result.get("status") != 200 or result.get("exact_text_match") is False)


if __name__ == "__main__":
    raise SystemExit(main())

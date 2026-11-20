"""Offline wrapper for running the recording validator against synthetic files."""

from pathlib import Path
import sys

# The offline CLI runs on system Python as well as in the workspace virtualenv.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "api" / "src"))
from api.audio.containers import FORMATS, check_recording

__all__ = ["FORMATS", "check_container"]


def check_container(kind: str, fixture: Path) -> dict:
    try:
        if fixture.is_file():
            # The probes and Python share a descriptor offset. Keep header reads unbuffered.
            with fixture.open("rb", buffering=0) as audio:
                return check_recording(kind, audio)
    except OSError:
        pass
    return {"probe": kind, "mode": "container", "status": "rejected", "reason": "fixture_unreadable"}

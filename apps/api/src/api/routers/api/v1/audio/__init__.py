"""Browser audio routes require a verified owner."""

from fastapi import Depends

from api.audio.access import require_audio_owner

dependencies = (Depends(require_audio_owner),)

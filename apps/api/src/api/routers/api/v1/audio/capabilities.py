"""Report the independently verified state of transcription and speech."""

from fastapi import APIRouter, Response

from api.audio.capabilities import AudioCapabilitiesOut, audio_capabilities

router = APIRouter()


@router.get(
    "",
    operation_id="audio_capabilities_get",
    summary="Get audio capabilities",
    responses={401: {"description": "Owner access could not be verified"}},
)
async def audio_capabilities_get(response: Response) -> AudioCapabilitiesOut:
    """Return the audio settings and verified capabilities without contacting the provider."""
    response.headers["Cache-Control"] = "no-store"
    return audio_capabilities()

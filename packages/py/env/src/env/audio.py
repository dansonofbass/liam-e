"""Model selection and reviewed Studio release evidence for the two audio capabilities."""

from env._base import BaseEnv


class Env(BaseEnv):
    audio_stt_model: str = "voxtral-mini-transcribe-3"
    audio_tts_model: str = "voxtral-mini-tts-3-0"
    # Parse each independently. Invalid evidence must not prevent the app from starting.
    audio_stt_verification: str | None = None
    audio_tts_verification: str | None = None


env = Env()

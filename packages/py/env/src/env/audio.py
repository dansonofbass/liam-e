"""Model selection and reviewed Studio release evidence for the two audio capabilities."""

from env._base import BaseEnv


class Env(BaseEnv):
    audio_stt_model: str = "voxtral-mini-transcribe-3"
    audio_tts_model: str = "voxtral-mini-tts-3-0"
    # Per deployment. The bound user, tenant and browser origin are supplied by the operator.
    audio_studio_owner: str | None = None
    audio_device_test_until: str | None = None
    # Opt-in for a separately bound test deployment; never a production attestation.
    audio_live_test_enabled: bool = False
    audio_live_test_origin: str | None = None
    audio_live_test_until: str | None = None
    # Parse each independently. Invalid evidence must not prevent the app from starting.
    audio_stt_verification: str | None = None
    audio_tts_verification: str | None = None


env = Env()

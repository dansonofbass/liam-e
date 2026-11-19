"""Read independently reviewed audio release evidence without contacting Mistral."""

from datetime import datetime, timezone
import re
from typing import Annotated, Literal

from env.audio import env
from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    PositiveInt,
    StringConstraints,
    ValidationError,
    model_validator,
)

MODEL_PATTERN = r"^voxtral-[a-zA-Z0-9][a-zA-Z0-9._-]{0,79}$"
AudioModelId = Annotated[str, StringConstraints(pattern=MODEL_PATTERN)]
TranscriptionFormat = Literal["audio/webm;codecs=opus", "audio/mp4;codecs=mp4a.40.2"]
SpeechFormat = Literal["audio/mpeg"]


class _CapabilityState(BaseModel):
    status: Literal["available", "unavailable", "unknown"]
    reason: Literal["invalid_model_configuration", "verification_missing_or_invalid", "verification_failed"] | None
    model: str | None
    resolved_model: str | None = None
    checked_at: AwareDatetime | None = None


class TranscriptionLimitsOut(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    max_upload_bytes: int
    max_duration_seconds: int
    max_concurrent_requests: int


_TRANSCRIPTION_APP_LIMITS = TranscriptionLimitsOut(
    max_upload_bytes=10 * 1024 * 1024, max_duration_seconds=120, max_concurrent_requests=1,
)


class SpeechLimitsOut(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    max_input_characters: PositiveInt
    max_response_bytes: PositiveInt
    timeout_seconds: PositiveInt


class TranscriptionCapabilityOut(_CapabilityState):
    formats: tuple[TranscriptionFormat, ...]
    app_limits: TranscriptionLimitsOut


class SpeechCapabilityOut(_CapabilityState):
    formats: tuple[SpeechFormat, ...]
    app_limits: SpeechLimitsOut | None


class AudioCapabilitiesOut(BaseModel):
    stt: TranscriptionCapabilityOut
    tts: SpeechCapabilityOut


class _Verification(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    model: AudioModelId
    checked_at: AwareDatetime
    resolved_model: AudioModelId | None = None
    outcome: Literal["verified", "failed"]
    scope: Literal["provider", "studio_release"] | None = None

    @model_validator(mode="after")
    def require_studio_release_scope(self):
        if self.outcome == "verified" and self.scope != "studio_release":
            raise ValueError("availability requires a reviewed Studio release attestation")
        return self


class _TranscriptionVerification(_Verification):
    formats: tuple[TranscriptionFormat, ...] = Field(default=(), max_length=2)
    app_limits: TranscriptionLimitsOut | None = None

    @model_validator(mode="after")
    def require_format_and_limits(self):
        if self.outcome == "verified" and (not self.formats or self.app_limits != _TRANSCRIPTION_APP_LIMITS):
            raise ValueError("verified transcription requires checked formats and the current application limits")
        return self


class _SpeechVerification(_Verification):
    formats: tuple[SpeechFormat, ...] = Field(default=(), max_length=1)
    app_limits: SpeechLimitsOut | None = None

    @model_validator(mode="after")
    def require_format_and_limits(self):
        if self.outcome == "verified" and (not self.formats or self.app_limits is None):
            raise ValueError("a verified speech capability requires a checked format and application limits")
        return self


def _resolve_verification[T: _Verification](
    model: str, raw: str | None, schema: type[T]
) -> tuple[_CapabilityState, T | None]:
    if re.fullmatch(MODEL_PATTERN, model) is None:
        return _CapabilityState(status="unknown", reason="invalid_model_configuration", model=None), None
    unknown = _CapabilityState(status="unknown", reason="verification_missing_or_invalid", model=model)
    if not raw or len(raw) > 2048:
        return unknown, None
    try:
        evidence = schema.model_validate_json(raw)
    except ValidationError:
        return unknown, None

    if evidence.model != model or evidence.checked_at > datetime.now(timezone.utc):
        return unknown, None
    if evidence.outcome == "failed":
        return _CapabilityState(
            status="unavailable", reason="verification_failed", model=model,
            resolved_model=evidence.resolved_model, checked_at=evidence.checked_at,
        ), None
    return _CapabilityState(
        status="available", reason=None, model=model,
        resolved_model=evidence.resolved_model, checked_at=evidence.checked_at,
    ), evidence


def audio_capabilities() -> AudioCapabilitiesOut:
    stt, stt_evidence = _resolve_verification(env.audio_stt_model, env.audio_stt_verification, _TranscriptionVerification)
    tts, tts_evidence = _resolve_verification(env.audio_tts_model, env.audio_tts_verification, _SpeechVerification)
    return AudioCapabilitiesOut(
        stt=TranscriptionCapabilityOut(
            **stt.model_dump(),
            formats=stt_evidence.formats if stt_evidence else (),
            app_limits=_TRANSCRIPTION_APP_LIMITS,
        ),
        tts=SpeechCapabilityOut(
            **tts.model_dump(),
            formats=tts_evidence.formats if tts_evidence else (),
            app_limits=tts_evidence.app_limits if tts_evidence else None,
        ),
    )

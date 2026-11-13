"""Settings for reading back from Mistral Studio observability and the object registry.

This mirrors write-only ``env.telemetry``. Studio's read surface is a plain REST API on the regular
API host, so the read path needs its own base URL. Two surfaces share this module because they share
a host and bearer: ``/v1/observability/*`` and ``/v2/prompts``. Auth is ``MISTRAL_API_KEY``, but
reading is off by default and requires Studio observability access, granted per workspace.
"""

from pydantic import Field

from env._base import BaseEnv


class Env(BaseEnv):
    # The read API's base URL. Same deployment as the chat/completions API, not the OTLP
    # endpoint URL in `env.telemetry`, which only accepts OTLP.
    observability_api_base_url: str = "https://api.mistral.ai"

    # Off by default, because `/v1/observability/*` reads require Studio observability access
    # for the workspace. Turning this on without that access makes every call 404; code that
    # reads should check this setting and skip the read when it is off.
    observability_read_enabled: bool = False

    # One request's budget. A wide time range is paginated rather than fetched at once, but a
    # single page can still be slow.
    observability_request_timeout_seconds: float = Field(default=30.0, gt=0)

    # Rows per page. The API caps this server-side; a smaller value only costs round trips.
    observability_page_size: int = Field(default=100, ge=1, le=1000)

    # A ceiling on pagination, so one read cannot walk an unbounded backlog into memory.
    # Reaching the cap is worth logging rather than raising: a truncated read is still useful.
    observability_max_pages: int = Field(default=50, ge=1)


env = Env()

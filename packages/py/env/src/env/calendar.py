"""Calendar polling while the API instance is running."""

from pydantic import Field

from env._base import BaseEnv


class Env(BaseEnv):
    calendar_sync_interval_minutes: int = Field(default=30, ge=1)


env = Env()

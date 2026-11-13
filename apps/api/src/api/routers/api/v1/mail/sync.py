"""Schedule account synchronization."""

from datetime import datetime, timezone

from fastapi import APIRouter
from pydantic import BaseModel, Field

from api.mail import jobs

router = APIRouter()


class SyncAllRequest(BaseModel):
    only_if_older_than_minutes: int | None = Field(default=None, ge=0)


class SyncAllOut(BaseModel):
    queued: list[str]


@router.post("", operation_id="mail_sync_all", status_code=202)
async def mail_sync_all(body: SyncAllRequest) -> SyncAllOut:
    """Queue active accounts, optionally only those last synced before the given age."""
    return SyncAllOut(queued=await jobs.enqueue_due_syncs(datetime.now(timezone.utc), older_than_minutes=body.only_if_older_than_minutes, skip_auth_expired=False))

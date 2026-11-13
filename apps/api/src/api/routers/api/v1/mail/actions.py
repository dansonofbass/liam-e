"""Undo one or more recent mail actions."""

from dataclasses import asdict
from datetime import UTC, datetime

from fastapi import APIRouter

from api.mail.actions import undo_actions
from api.routers.api.v1.mail.schemas import UndoIn, UndoOut

router = APIRouter()


@router.post("/undo", operation_id="mail_actions_undo", summary="Undo recent mail actions")
async def undo(body: UndoIn) -> UndoOut:
    """Undo up to 200 actions, newest first, within 24 hours; report individual failures."""
    return UndoOut(**asdict(await undo_actions(body.action_ids, now=datetime.now(UTC))))

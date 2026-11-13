"""Cancel a pending draft without sending it."""

import json

from db.accessors import chat_message as message_access
from fastapi import APIRouter, HTTPException

from api.routers.api.v1.chat import schemas

router = APIRouter()


@router.delete("", operation_id="chat_draft_cancel", summary="Cancel a pending draft")
async def cancel_draft(draft_id: str) -> schemas.ChatMessageOut:
    """Discard a pending draft without sending it — no mail is delivered.

    ``draft_id`` identifies the draft chat message; it answers 404 when the id is not a draft
    and 409 when the draft was already handled (sent, failed or cancelled). The returned message
    carries the draft with status ``cancelled``.
    """
    message = await message_access.get_message(draft_id)
    if message is None or message.role != "draft":
        raise HTTPException(status_code=404, detail="Entwurf nicht gefunden.")
    draft = json.loads(message.draft_json) if message.draft_json else {}
    if draft.get("status") != "pending":
        raise HTTPException(
            status_code=409,
            detail=f"Entwurf wurde bereits behandelt (Status: {draft.get('status')}).",
        )
    draft["status"] = "cancelled"
    updated = await message_access.update_draft_json(
        draft_id, json.dumps(draft, ensure_ascii=False)
    )
    assert updated is not None
    return schemas.ChatMessageOut.from_model(updated)

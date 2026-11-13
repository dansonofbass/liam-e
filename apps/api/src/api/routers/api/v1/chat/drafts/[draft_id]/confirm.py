"""Confirm a pending draft: this is the one and only path that sends a mail."""

import json

from db.accessors import chat_message as message_access
from db.accessors import mail_account as account_access
from fastapi import APIRouter, HTTPException

from api.mail import send as send_service
from api.mail.service import CredentialError, load_credentials
from api.routers.api.v1.chat import schemas as chat_schemas

router = APIRouter()


@router.post(
    "", operation_id="chat_draft_confirm", summary="Send the confirmed draft for real"
)
async def confirm_draft(draft_id: str) -> chat_schemas.ChatMessageOut:
    message = await message_access.get_message(draft_id)
    if message is None or message.role != "draft":
        raise HTTPException(status_code=404, detail="Entwurf nicht gefunden.")
    draft = json.loads(message.draft_json) if message.draft_json else {}
    if draft.get("status") != "pending":
        raise HTTPException(
            status_code=409,
            detail=f"Entwurf wurde bereits behandelt (Status: {draft.get('status')}).",
        )
    account = await account_access.get_account(draft.get("account_id", ""))
    if account is None:
        raise HTTPException(
            status_code=404, detail="Das Konto des Entwurfs existiert nicht mehr."
        )
    try:
        credentials = await load_credentials(account)
        result = await send_service.send_message(
            account,
            to=list(draft.get("to", [])),
            subject=str(draft.get("subject", "")),
            body=str(draft.get("body", "")),
            credentials=credentials,
        )
    except CredentialError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except Exception as error:
        draft["status"] = "failed"
        draft["error"] = str(error)
        updated = await message_access.update_draft_json(
            draft_id, json.dumps(draft, ensure_ascii=False)
        )
        raise HTTPException(
            status_code=502, detail=f"Versand fehlgeschlagen: {error}"
        ) from error
    draft["status"] = "sent"
    draft["send_result"] = result
    updated = await message_access.update_draft_json(
        draft_id, json.dumps(draft, ensure_ascii=False)
    )
    assert updated is not None
    return chat_schemas.ChatMessageOut.from_model(updated)

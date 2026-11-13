"""Confirm a pending draft: this is the one and only path that sends a mail."""

import json
import logging

from db.accessors import chat_message as message_access
from db.accessors import mail_account as account_access
from fastapi import APIRouter, HTTPException

from api.mail import send as send_service
from api.errors import refuse
from api.mail import netguard, transport
from api.mail.service import CredentialError
from api.routers.api.v1.chat import schemas as chat_schemas

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post(
    "", operation_id="chat_draft_confirm", summary="Send the confirmed draft for real"
)
async def confirm_draft(draft_id: str) -> chat_schemas.ChatMessageOut:
    """Send the pending draft for real; this is the only path that actually sends a mail.

    ``draft_id`` identifies the pending draft chat message, which is sent to its recipients via
    the account that created it. On success the draft is stored with status ``sent`` and the
    provider's send result; a send failure stores status ``failed`` with a safe error code.
    Blocked hosts answer 422 and other send failures 502. Unknown or already handled
    drafts answer 404 and 409.
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
    account = await account_access.get_account(draft.get("account_id", ""))
    if account is None:
        raise HTTPException(
            status_code=404, detail="Das Konto des Entwurfs existiert nicht mehr."
        )
    try:
        result = await send_service.send_message(
            account,
            to=list(draft.get("to", [])),
            subject=str(draft.get("subject", "")),
            body=str(draft.get("body", "")),
        )
    except CredentialError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except Exception as error:
        logger.exception("Draft send failed")
        blocked = isinstance(error, (transport.MailHostNotAllowedError, netguard.BlockedAddressError))
        code = "host_not_allowed" if blocked else "send_failed"
        draft["status"] = "failed"
        draft["error"] = code
        await message_access.update_draft_json(
            draft_id, json.dumps(draft, ensure_ascii=False)
        )
        if blocked:
            raise refuse(422, code, "Der Mailserver dieses Kontos ist nicht freigegeben. Trag ihn in Mistral Studio unter MAIL_IMAP_ALLOWED_HOSTS ein und lass den Entwurf dann neu erstellen.") from error
        raise refuse(502, code, "Die Mail ließ sich nicht senden. Prüf das Konto unter Konten und lass den Entwurf dann neu erstellen.") from error
    draft["status"] = "sent"
    draft["send_result"] = result
    updated = await message_access.update_draft_json(
        draft_id, json.dumps(draft, ensure_ascii=False)
    )
    assert updated is not None
    return chat_schemas.ChatMessageOut.from_model(updated)

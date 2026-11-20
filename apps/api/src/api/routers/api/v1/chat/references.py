"""Short live mail previews for the chat UI."""
from db.accessors import chat_settings, mail_account
from fastapi import APIRouter, Query
from sqlalchemy.exc import SQLAlchemyError

from api.errors import refuse
from api.mail.chat_events import MailRefOut
from api.mail.headers import sender_name
from api.mail.state import color_indexes

router = APIRouter()


@router.get('/{message_id}', operation_id='chat_mail_reference_get')
async def mail_reference(message_id: str, expected_version: int = Query(ge=1), context_id: str | None = None) -> MailRefOut:
    try:
        preview = await chat_settings.mail_preview(message_id, expected_version, context_id)
        if preview is None:
            raise refuse(404, 'message_not_found', 'Diese Mail ist im Chat nicht verfügbar.')
        row, insight = preview
        colors = color_indexes(await mail_account.list_accounts())
        return MailRefOut(id=row.id, account_id=row.account_id, color_index=colors.get(row.account_id, 0),
                          subject=row.subject, sender_name=sender_name(row.sender), snippet=row.snippet,
                          internal_date=row.internal_date, deadline=insight.deadline if insight else None, is_flagged=row.is_flagged)
    except SQLAlchemyError:
        raise refuse(503, 'settings_unavailable', 'Die Chat-Freigaben sind gerade nicht erreichbar.') from None

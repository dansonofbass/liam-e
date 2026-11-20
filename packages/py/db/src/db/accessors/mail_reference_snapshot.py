"""Read-only source links, outside the live mail index and provider action paths."""
import json

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from db.engine import get_session_maker
from db.models.mail_message import MailMessage
from db.models.mail_reference_snapshot import MailReferenceSnapshot


async def preserve(session: AsyncSession, message: MailMessage) -> None:
    fields = {"subject", "sender", "sender_address", "recipients_json", "cc_json", "snippet", "body_text",
              "internal_date", "is_read", "is_flagged", "attachments_json", "has_attachments"}
    content = message.model_dump_json(include=fields)
    ids = set(message.connector_alias_ids) | {message.id}
    await session.execute(insert(MailReferenceSnapshot).values([
        {"id": id, "account_id": message.account_id, "content_json": content} for id in ids
    ]).on_conflict_do_nothing(index_elements=[MailReferenceSnapshot.id]))


async def read(message_id: str) -> MailMessage | None:
    async with get_session_maker()() as session:
        row = await session.get(MailReferenceSnapshot, message_id)
        if row is None:
            return None
        return MailMessage.model_validate({
            **json.loads(row.content_json), "id": row.id, "account_id": row.account_id,
            "folder": "ARCHIVE", "provider_uid": "", "unverified_connector": True,
        })

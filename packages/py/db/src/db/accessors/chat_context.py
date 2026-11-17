"""Resolve and persist a turn snapshot under conversation and template locks."""
import json
from sqlalchemy import select
from db.engine import get_session_maker
from db.models._common import utcnow
from db.models.chat_context import ChatContext
from db.models.chat_conversation import ChatConversation
from db.models.chat_message import ChatMessage
from db.models.mail_account import MailAccount
from db.models.prompt_revision import PromptRevision
from db.models.prompt_template import OWNER_SCOPE, PromptTemplate
from db.accessors.prompt_template import StaleVersion


class ContextUnavailable(Exception):
    pass


class ScopeChange(Exception):
    pass


async def lock_revision(session, revision_id):
    if revision_id is None:
        return None
    revision = await session.get(PromptRevision, revision_id)
    if revision is None or revision.removed or revision.owner_scope != OWNER_SCOPE:
        raise ContextUnavailable
    template = (await session.execute(select(PromptTemplate).where(
        PromptTemplate.id == revision.template_id, PromptTemplate.owner_scope == OWNER_SCOPE
    ).with_for_update())).scalar_one_or_none()
    if template is None:
        raise ContextUnavailable
    await session.refresh(revision)
    if revision.removed:
        raise ContextUnavailable
    return revision


async def configure(conversation_id, expected_version, *, revision_id=None, change_revision=False,
                    model=None, title=None):
    async with get_session_maker()() as session:
        if change_revision:
            await lock_revision(session, revision_id)
        row = (await session.execute(select(ChatConversation).where(
            ChatConversation.id == conversation_id).with_for_update())).scalar_one_or_none()
        if row is None:
            raise ContextUnavailable
        if row.version != expected_version:
            raise StaleVersion
        if change_revision:
            row.prompt_revision_id = revision_id
        if model is not None:
            row.model = model
        if title is not None:
            row.title = title
        row.version += 1
        row.updated_at = utcnow()
        await session.commit()
        return row


async def resolve(*, conversation_id, title, model, revision_id, account_id, app_prompt_version):
    async with get_session_maker()() as session:
        # Lock order matches deletion: template before conversation.
        existing = await session.get(ChatConversation, conversation_id) if conversation_id else None
        if conversation_id and existing is None:
            raise ContextUnavailable
        if existing and revision_id is not None:
            raise ValueError("selection_requires_patch")
        selected = existing.prompt_revision_id if existing else revision_id
        revision = await lock_revision(session, selected)
        if existing:
            await session.refresh(existing, with_for_update=True)
            if existing.prompt_revision_id != selected:
                raise StaleVersion
            conversation = existing
        else:
            conversation = ChatConversation(title=title, model=model or "", prompt_revision_id=selected)
            session.add(conversation)
        accounts = list((await session.execute(select(MailAccount.id))).scalars())
        if account_id is not None and account_id not in accounts:
            raise ValueError("account_invalid")
        scope = json.dumps(sorted([account_id] if account_id is not None else accounts))
        provenance = json.dumps({'account_ids': json.loads(scope), 'selection': account_id})
        has_history = (await session.execute(select(ChatMessage.id).where(
            ChatMessage.conversation_id == conversation.id).limit(1))).first() is not None
        legacy_mixed = (has_history and conversation.account_scope_json is None) or (
            conversation.account_scope_json is not None and
            json.loads(conversation.account_scope_json).get('legacy_mixed', False))
        if legacy_mixed:
            provenance = json.dumps({'account_ids': json.loads(scope), 'selection': account_id, 'legacy_mixed': True})
        if conversation.account_scope_json is not None:
            # "Alle Konten" stays the same choice when accounts are added or removed; only another
            # selection would carry history from one scope into another.
            if json.loads(conversation.account_scope_json).get('selection') != account_id:
                raise ScopeChange
        elif has_history and account_id is not None:
            # Unknown historical provenance is mixed, never attributed to one account.
            raise ScopeChange
        conversation.account_scope_json = provenance
        snapshot = ChatContext(conversation_id=conversation.id, prompt_revision_id=selected,
                               prompt_hash=revision.content_hash if revision else None,
                               app_prompt_version=app_prompt_version, account_scope_json=provenance)
        session.add(snapshot)
        await session.commit()
        return conversation, snapshot, revision.content if revision else None


async def get_context(context_id: str) -> ChatContext | None:
    async with get_session_maker()() as session:
        return await session.get(ChatContext, context_id)


async def is_live(context_id: str) -> bool:
    async with get_session_maker()() as session:
        row = await session.get(ChatContext, context_id)
        return row is not None and not row.revoked

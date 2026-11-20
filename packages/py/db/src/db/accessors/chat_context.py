"""Resolve and persist a turn snapshot under conversation and template locks.

Task provenance is independent of preferences: legacy turns have source=none.
Any task selection change requires a fresh conversation, including expansion.
Task sources must also fit the central mail grant and any focused account.
"""
import json
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from db.accessors import chat_settings, user_preference
from db.engine import get_session_maker
from db.models._common import utcnow
from db.models.chat_context import ChatContext
from db.models.chat_conversation import ChatConversation
from db.models.chat_message import ChatMessage
from db.models.mail_message import MailMessage
from db.models.calendar_source import CalendarSource
from db.models.prompt_revision import PromptRevision
from db.models.prompt_template import OWNER_SCOPE, PromptTemplate
from db.accessors.prompt_template import StaleVersion


class PreferencesUnavailable(Exception):
    pass


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


async def resolve(*, conversation_id, title, model, revision_id, account_id, app_prompt_version, calendar_source_ids=None,
                  task_source='none', task_source_account_id=None, without_preferences=False, context_message_id=None, expected_mail_scope_version=None):
    async with get_session_maker()() as session:
        await user_preference.lock(session)
        grants = await chat_settings.in_session(session)
        if expected_mail_scope_version is not None and expected_mail_scope_version != grants.version:
            raise chat_settings.GrantsChanged
        accounts = await chat_settings.active_ids(session, grants.account_ids)
        if account_id is not None and account_id not in accounts:
            raise chat_settings.AccountNotGranted
        if context_message_id is not None:
            source_account = (await session.execute(select(MailMessage.account_id).where(
                MailMessage.id == context_message_id, MailMessage.account_id.in_(accounts)
            ))).scalar_one_or_none()
            if source_account is None or (account_id is not None and account_id != source_account):
                raise chat_settings.AccountNotGranted
            if conversation_id is None:
                account_id = source_account
        enabled, preference_ids = False, []
        if not without_preferences:
            try:
                enabled, preference_ids = await user_preference.resolve_in_session(session, account_id)
            except SQLAlchemyError:
                raise PreferencesUnavailable from None
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
        account_scope = {'account_ids': [account_id] if account_id else accounts, 'selection': account_id}
        provenance = json.dumps(account_scope)
        # Keep missing or cross-conversation context references as an unverified history.
        history = (await session.execute(select(ChatContext).select_from(ChatMessage).outerjoin(
            ChatContext, (ChatMessage.context_id == ChatContext.id)
            & (ChatMessage.conversation_id == ChatContext.conversation_id)
        ).where(ChatMessage.conversation_id == conversation.id).distinct())).scalars().all() if existing else []
        calendar_ids = sorted(set(calendar_source_ids or []))
        active_ids = set((await session.execute(select(CalendarSource.id).where(
            CalendarSource.is_active.is_(True), CalendarSource.id.in_(calendar_ids)))).scalars()) if calendar_ids else set()
        if active_ids != set(calendar_ids):
            if history:
                raise ScopeChange
            raise ValueError('calendar_invalid')
        if task_source not in {'none', 'all', 'unlinked', 'account', 'account_and_unlinked'}:
            raise ValueError('task_scope_invalid')
        if (task_source in {'account', 'account_and_unlinked'}) != bool(task_source_account_id):
            raise ValueError('task_scope_invalid')
        if task_source_account_id and task_source_account_id not in account_scope['account_ids']:
            raise ValueError('task_scope_invalid')
        if account_id is not None and task_source != 'none' and (
            task_source not in {'account', 'account_and_unlinked'} or task_source_account_id != account_id
        ):
            raise ValueError('task_scope_invalid')
        if task_source == 'account_and_unlinked' and account_id is None:
            raise ValueError('task_scope_invalid')
        task_scope = {'source': task_source}
        if task_source_account_id:
            task_scope['account_id'] = task_source_account_id
        for prior in history:
            if (prior is None or prior.mail_scope_version != grants.version
                    or json.loads(prior.account_scope_json) != account_scope
                    or sorted(json.loads(prior.calendar_scope_json)) != calendar_ids
                    or json.loads(prior.task_scope_json) != task_scope):
                raise ScopeChange
        conversation.account_scope_json = provenance
        snapshot = ChatContext(conversation_id=conversation.id, prompt_revision_id=selected,
                               prompt_hash=revision.content_hash if revision else None,
                               app_prompt_version=app_prompt_version, account_scope_json=provenance, mail_scope_version=grants.version,
                               calendar_scope_json=json.dumps(calendar_ids), task_scope_json=json.dumps(task_scope),
                               preferences_enabled=enabled, preference_revision_ids_json=json.dumps(preference_ids))
        session.add(snapshot)
        await session.commit()
        return conversation, snapshot, revision.content if revision else None


async def get_context(context_id: str) -> ChatContext | None:
    async with get_session_maker()() as session:
        return await session.get(ChatContext, context_id)


async def get_context_in_session(session, context_id: str) -> ChatContext | None:
    """Read provenance inside a local proposal transaction; never commit here."""
    return await session.get(ChatContext, context_id)


async def get_contexts(context_ids: set[str]) -> dict[str, ChatContext]:
    if not context_ids:
        return {}
    async with get_session_maker()() as session:
        rows = (await session.execute(select(ChatContext).where(ChatContext.id.in_(context_ids)))).scalars().all()
        return {row.id: row for row in rows}


async def is_live(context_id: str) -> bool:
    async with get_session_maker()() as session:
        row = await session.get(ChatContext, context_id)
        if row is None or row.revoked or not await chat_settings.permits_context(session, row):
            return False
        ids = json.loads(row.calendar_scope_json)
        if not ids:
            return True
        active = set((await session.execute(select(CalendarSource.id).where(
            CalendarSource.id.in_(ids), CalendarSource.is_active.is_(True)))).scalars())
        return active == set(ids)

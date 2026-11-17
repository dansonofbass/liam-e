"""Resolve and persist a turn snapshot under conversation and template locks.

Task provenance is independent of preferences: legacy turns have source=none.
Any task selection change requires a fresh conversation, including expansion.
A mail-account selection also bounds task sources; it cannot include personal tasks.
"""
import json
from sqlalchemy import select
from db.engine import get_session_maker
from db.models._common import utcnow
from db.models.chat_context import ChatContext
from db.models.chat_conversation import ChatConversation
from db.models.chat_message import ChatMessage
from db.models.mail_account import MailAccount
from db.models.calendar_source import CalendarSource
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


async def resolve(*, conversation_id, title, model, revision_id, account_id, app_prompt_version, calendar_source_ids=None,
                  task_source='none', task_source_account_id=None):
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
        # Any calendar selection change (including expansion) starts fresh. Legacy turns
        # have no calendar access. Check every historical context, not just the latest turn.
        calendar_ids = sorted(set(calendar_source_ids or []))
        active_ids = set((await session.execute(select(CalendarSource.id).where(
            CalendarSource.is_active.is_(True), CalendarSource.id.in_(calendar_ids)))).scalars()) if calendar_ids else set()
        previous = list((await session.execute(select(ChatContext).where(
            ChatContext.conversation_id == conversation.id))).scalars()) if has_history else []
        if has_history:
            context_ids = list((await session.execute(select(ChatMessage.context_id).where(
                ChatMessage.conversation_id == conversation.id))).scalars())
            by_id = {row.id: row for row in previous}
            for id in context_ids:
                prior = json.loads(by_id[id].calendar_scope_json) if id in by_id else []
                if sorted(prior) != calendar_ids:
                    raise ScopeChange
            if active_ids != set(calendar_ids):
                raise ScopeChange
        elif active_ids != set(calendar_ids):
            raise ValueError('calendar_invalid')
        if task_source not in {'none', 'all', 'unlinked', 'account'}:
            raise ValueError('task_scope_invalid')
        if (task_source == 'account') != bool(task_source_account_id):
            raise ValueError('task_scope_invalid')
        if task_source_account_id and task_source_account_id not in accounts:
            raise ValueError('task_scope_invalid')
        if account_id is not None and task_source != 'none' and (
            task_source != 'account' or task_source_account_id != account_id
        ):
            raise ValueError('task_scope_invalid')
        task_scope = {'source': task_source}
        if task_source_account_id:
            task_scope['account_id'] = task_source_account_id
        if has_history:
            for id in context_ids:
                prior_task = json.loads(by_id[id].task_scope_json) if id in by_id else {'source': 'none'}
                if prior_task != task_scope:
                    raise ScopeChange
        conversation.account_scope_json = provenance
        snapshot = ChatContext(conversation_id=conversation.id, prompt_revision_id=selected,
                               prompt_hash=revision.content_hash if revision else None,
                               app_prompt_version=app_prompt_version, account_scope_json=provenance,
                               calendar_scope_json=json.dumps(calendar_ids), task_scope_json=json.dumps(task_scope))
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
        if row is None or row.revoked:
            return False
        ids = json.loads(row.calendar_scope_json)
        if not ids:
            return True
        active = set((await session.execute(select(CalendarSource.id).where(
            CalendarSource.id.in_(ids), CalendarSource.is_active.is_(True)))).scalars())
        return active == set(ids)

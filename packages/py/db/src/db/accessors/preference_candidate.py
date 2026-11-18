"""Candidate lifecycle under the shared preference lock; callers own transactions.

The source/key/scope unique key is a content-free rejection tombstone. Deletion
also compares source time with the preference's removal marker, allowing a new
explicit request but never replay of an old source. Cards hold only candidate IDs.
"""
import json
from sqlalchemy import select, and_, or_
from sqlalchemy.exc import IntegrityError
from db.accessors import user_preference as preferences
from db.models.preference_candidate import PreferenceCandidate
from db.models.preference_revision import PreferenceRevision
from db.models.user_preference import UserPreference
from db.models.chat_message import ChatMessage
from db.models.chat_conversation import ChatConversation
from db.models.chat_context import ChatContext
from db.models.prompt_template import OWNER_SCOPE


class CandidateGone(Exception):
    pass


class CandidateConflict(Exception):
    pass


async def get(session, id):
    row = await session.get(PreferenceCandidate, id)
    if row is None or row.owner_scope != OWNER_SCOPE:
        raise CandidateGone
    return row


async def source(session, conversation_id, source_message_id):
    message = await session.get(ChatMessage, source_message_id)
    conversation = await session.get(ChatConversation, conversation_id)
    if (message is None or message.role != 'user' or message.conversation_id != conversation_id
            or conversation is None):
        raise CandidateGone
    if message.context_id:
        context = await session.get(ChatContext, message.context_id)
        if context is None or context.revoked or context.conversation_id != conversation_id:
            raise CandidateGone
    return message


async def current(session, row):
    return (await session.execute(select(UserPreference).where(
        UserPreference.owner_scope == OWNER_SCOPE, UserPreference.key == row.key,
        UserPreference.scope == row.scope, UserPreference.status == 'active'
    ))).scalar_one_or_none()


async def snapshot(session, row):
    target = await current(session, row)
    row.target_id = target.id if target else None
    row.expected_version = target.version if target else 0
    row.expected_revision_id = target.revision_id if target else None


async def validate(session, row):
    message = await source(session, row.conversation_id, row.source_message_id)
    if row.status not in {'pending', 'accepted'} or row.value is None:
        raise CandidateGone
    await preferences.validate(session, row.key, row.scope, row.value, 'active')
    removed = (await session.execute(select(UserPreference).where(
        UserPreference.owner_scope == OWNER_SCOPE, UserPreference.key == row.key,
        UserPreference.scope == row.scope, UserPreference.status == 'removed'
    ))).scalars()
    if any(p.removed_at is None or message.created_at <= p.removed_at for p in removed):
        raise CandidateGone
    return message


async def erase(session, row, status='expired'):
    row.value, row.status = None, status
    if row.proposal_id:
        card = await session.get(ChatMessage, row.proposal_id)
        if card and card.proposal_status == 'pending':
            card.proposal_status = 'cancelled'


async def expire_scope(session, key=None, scope=None, preference_id=None):
    rows = (await session.execute(select(PreferenceCandidate).where(
        PreferenceCandidate.owner_scope == OWNER_SCOPE,
        or_(and_(PreferenceCandidate.key == key if key else True,
                 PreferenceCandidate.scope == scope if scope else True),
            PreferenceCandidate.target_id == preference_id if preference_id else False,
            PreferenceCandidate.accepted_preference_id == preference_id if preference_id else False),
    ))).scalars()
    for row in rows:
        await erase(session, row)


async def create(session, *, conversation_id, source_message_id, key, scope, value):
    """Idempotent per source and field. A replay never changes a rejected candidate."""
    await source(session, conversation_id, source_message_id)
    await preferences.validate(session, key, scope, value, 'active')
    previous = (await session.execute(select(PreferenceCandidate).where(
        PreferenceCandidate.owner_scope == OWNER_SCOPE,
        PreferenceCandidate.source_message_id == source_message_id,
        PreferenceCandidate.key == key, PreferenceCandidate.scope == scope,
    ))).scalar_one_or_none()
    if previous:
        return previous
    row = PreferenceCandidate(conversation_id=conversation_id, source_message_id=source_message_id,
                              key=key, scope=scope, value=value)
    await validate(session, row)
    await snapshot(session, row)
    await preferences._quota(session, key, scope, 'active', row.target_id)
    count = len(list((await session.execute(select(PreferenceCandidate.id).where(
        PreferenceCandidate.owner_scope == OWNER_SCOPE, PreferenceCandidate.status == 'pending'
    ))).scalars()))
    if count >= 50:
        raise preferences.PreferenceConflict
    session.add(row)
    await session.flush()
    return row


async def open_card(session, row, *, refresh=False):
    """Never cancel an existing card. The DB partial unique index arbitrates other kinds."""
    await validate(session, row)
    if row.status != 'pending':
        return None
    if refresh:
        await snapshot(session, row)
    if row.proposal_id:
        card = await session.get(ChatMessage, row.proposal_id)
        if card:
            if card.proposal_status != 'pending':
                await erase(session, row, 'rejected')
            return card
    existing = (await session.execute(select(ChatMessage).where(
        ChatMessage.conversation_id == row.conversation_id,
        ChatMessage.proposal_status.in_(['pending', 'running'])
    ))).scalars().first()
    if existing:
        return None
    message = await source(session, row.conversation_id, row.source_message_id)
    card = ChatMessage(conversation_id=row.conversation_id, context_id=message.context_id,
        role='proposal', proposal_status='pending', proposal_json=json.dumps({
            'kind': 'preference', 'reason': '', 'items': [], 'preference': {'candidate_id': row.id}}))
    try:
        async with session.begin_nested():
            session.add(card)
            await session.flush()
    except IntegrityError:
        return None
    row.proposal_id = card.id
    return card


async def accept(session, row, *, decision, expected_version, expected_revision_id):
    await validate(session, row)
    if row.status != 'pending':
        raise CandidateGone
    target = await current(session, row)
    actual = (target.id, target.version, target.revision_id) if target else (None, 0, None)
    if (actual != (row.target_id, row.expected_version, row.expected_revision_id)
            or (expected_version, expected_revision_id) != (row.expected_version, row.expected_revision_id)):
        raise CandidateConflict
    if decision == 'keep':
        await erase(session, row, 'rejected')
        return 'kept'
    if decision != 'replace':
        raise preferences.InvalidPreference
    await preferences._quota(session, row.key, row.scope, 'active', row.target_id)
    previous = await session.get(PreferenceRevision, target.revision_id) if target else None
    if previous and not previous.removed and previous.value == row.value:
        row.status, row.accepted_preference_id = 'accepted', target.id
        return 'unchanged'
    if target is None:
        target = UserPreference(key=row.key, scope=row.scope)
        session.add(target)
    else:
        target.version += 1
    revision = PreferenceRevision(preference_id=target.id, number=target.version,
        key=row.key, scope=row.scope, value=row.value, source='confirmed_candidate')
    target.revision_id = revision.id
    session.add(revision)
    row.status, row.accepted_preference_id = 'accepted', target.id
    return 'saved'


async def presentation(session, row):
    from db.models.mail_account import MailAccount
    previous = await session.get(PreferenceRevision, row.expected_revision_id) if row.expected_revision_id else None
    target = await current(session, row)
    revision = await session.get(PreferenceRevision, target.revision_id) if target else None
    account = await session.get(MailAccount, row.scope) if row.scope != '*' else None
    return previous, target, revision, account


async def cancel_card(session, row):
    card = await session.get(ChatMessage, row.proposal_id) if row.proposal_id else None
    if card is None or card.proposal_status != 'pending':
        return None
    await erase(session, row, 'rejected')
    return card


async def list_rows(session, candidate_id=None):
    """The inbox is bounded by the pending quota; history loads one exact reference."""
    rows = list((await session.execute(select(PreferenceCandidate).where(
        PreferenceCandidate.owner_scope == OWNER_SCOPE,
        PreferenceCandidate.id == candidate_id if candidate_id else PreferenceCandidate.status == 'pending',
    ).order_by(PreferenceCandidate.created_at.desc()))).scalars())
    for row in rows:
        if row.status in {'pending', 'accepted'}:
            try:
                await validate(session, row)
            except (CandidateGone, preferences.InvalidPreference):
                await erase(session, row)
            if row.status == 'pending' and row.proposal_id:
                card = await session.get(ChatMessage, row.proposal_id)
                if card is None or card.proposal_status == 'cancelled':
                    await erase(session, row, 'rejected')
    return rows

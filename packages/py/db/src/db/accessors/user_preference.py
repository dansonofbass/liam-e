"""Single-owner preference transactions. Never log values or database exceptions.

One transaction advisory lock serializes opt-in, quotas, resolution and account removal.
Acquire it before template/conversation/account locks. Revisions hold the only value copy.
Removed objects retain key/scope only for future candidate suppression (#39).
"""
import json
from sqlalchemy import select, text, update
from db.engine import get_session_maker
from db.models.user_preference import UserPreference, GLOBAL_SCOPE
from db.models.preference_revision import PreferenceRevision
from db.accessors.personalization_settings import settings_in_session, settings as settings, update_settings as update_settings
from db.models.prompt_template import OWNER_SCOPE
from db.models.mail_account import MailAccount
from db.models.chat_context import ChatContext
from db.accessors.prompt_template import StaleVersion


class InvalidPreference(ValueError):
    pass


class PreferenceConflict(Exception):
    pass


async def lock(session):
    await session.execute(text('SELECT pg_advisory_xact_lock(380038)'))


async def revoke(session, revision_ids=None):
    """Revoke turns that used the given revisions, or any revision at all; turns without one are unaffected."""
    rows = (await session.execute(select(ChatContext).where(
        ChatContext.preferences_enabled.is_(True), ChatContext.revoked.is_(False),
        ChatContext.preference_revision_ids_json != '[]'))).scalars()
    for row in rows:
        if revision_ids is None or set(json.loads(row.preference_revision_ids_json)) & set(revision_ids):
            row.revoked = True


async def validate(session, key, scope, value, status):
    if key not in {'answer_length', 'salutation', 'signature'} or status not in {'active', 'paused'}:
        raise InvalidPreference
    if not isinstance(value, str) or not value.strip() or len(value) > 500:
        raise InvalidPreference
    if scope == GLOBAL_SCOPE:
        if key != 'answer_length':
            raise InvalidPreference
    elif not scope or await session.get(MailAccount, scope) is None:
        raise InvalidPreference


async def list_preferences():
    async with get_session_maker()() as session:
        return list((await session.execute(select(UserPreference).where(
            UserPreference.owner_scope == OWNER_SCOPE, UserPreference.status != 'removed'
        ).order_by(UserPreference.key, UserPreference.scope, UserPreference.id))).scalars())


async def _quota(session, key, scope, status, exclude=None):
    rows = list((await session.execute(select(UserPreference).where(
        UserPreference.owner_scope == OWNER_SCOPE, UserPreference.status != 'removed',
        UserPreference.id != exclude if exclude else True))).scalars())
    if len(rows) >= 50 or (status == 'active' and sum(r.status == 'active' for r in rows) >= 20):
        raise PreferenceConflict
    if status == 'active' and any(r.status == 'active' and r.key == key and r.scope == scope for r in rows):
        raise PreferenceConflict


async def create(*, key, scope=GLOBAL_SCOPE, value, status='active'):
    async with get_session_maker()() as session:
        await lock(session)
        await validate(session, key, scope, value, status)
        await _quota(session, key, scope, status)
        row = UserPreference(key=key, scope=scope, status=status)
        rev = PreferenceRevision(preference_id=row.id, number=1, key=key, scope=scope, value=value)
        row.revision_id = rev.id
        session.add_all([row, rev])
        await session.commit()
        return row


async def remove_in_session(session, row):
    from db.accessors.preference_candidate import expire_scope
    from db.models._common import utcnow
    await expire_scope(session, key=row.key, scope=row.scope, preference_id=row.id)
    row.removed_at = utcnow()
    ids = list((await session.execute(select(PreferenceRevision.id).where(
        PreferenceRevision.preference_id == row.id))).scalars())
    await revoke(session, ids)
    await session.execute(update(PreferenceRevision).where(PreferenceRevision.preference_id == row.id)
                          .values(value=None, removed=True))
    row.status = 'removed'
    row.revision_id = None
    row.version += 1


async def remove_account_in_session(session, account_id):
    """Caller holds the preference lock; deletion and account removal commit together."""
    from db.accessors.preference_candidate import expire_scope
    await expire_scope(session, scope=account_id)
    rows = (await session.execute(select(UserPreference).where(
        UserPreference.owner_scope == OWNER_SCOPE, UserPreference.scope == account_id,
        UserPreference.status != 'removed'))).scalars()
    for row in rows:
        await remove_in_session(session, row)


async def change(id, expected_version, *, delete=False, **changes):
    async with get_session_maker()() as session:
        await lock(session)
        row = await session.get(UserPreference, id)
        if row is None or row.owner_scope != OWNER_SCOPE or row.status == 'removed':
            return None
        if row.version != expected_version:
            raise StaleVersion
        if delete:
            await remove_in_session(session, row)
        else:
            if set(changes) - {'value', 'scope', 'status'}:
                raise InvalidPreference
            previous = await session.get(PreferenceRevision, row.revision_id)
            value = changes.get('value', previous.value)
            scope = changes.get('scope', row.scope)
            status = changes.get('status', row.status)
            await validate(session, row.key, scope, value, status)
            await _quota(session, row.key, scope, status, row.id)
            if status == 'paused' or scope != row.scope:
                ids = list((await session.execute(select(PreferenceRevision.id).where(
                    PreferenceRevision.preference_id == row.id))).scalars())
                await revoke(session, ids)
            row.version += 1
            row.scope, row.status = scope, status
            rev = PreferenceRevision(preference_id=row.id, number=row.version, key=row.key, scope=scope, value=value)
            row.revision_id = rev.id
            session.add(rev)
        await session.commit()
        return row


async def resolve_in_session(session, account_id, *, skip=False):
    """Explicit account overrides global per key; all-accounts never mixes signatures."""
    config = await settings_in_session(session)
    if skip or not config.use_preferences:
        return False, []
    rows = list((await session.execute(select(UserPreference).where(
        UserPreference.owner_scope == OWNER_SCOPE, UserPreference.status == 'active',
        UserPreference.scope.in_([GLOBAL_SCOPE, account_id] if account_id else [GLOBAL_SCOPE])
    ).order_by(UserPreference.key, UserPreference.scope))).scalars())
    selected = {}
    for row in rows:
        if row.key not in selected or row.scope == account_id:
            selected[row.key] = row
    return True, [selected[key].revision_id for key in sorted(selected)]

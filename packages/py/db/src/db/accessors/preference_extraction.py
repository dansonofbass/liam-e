"""Once-only extraction claims and opt-in/suppression checks under the preference lock."""
import json
from db.engine import get_session_maker
from db.accessors import preference_candidate as candidates, user_preference as preferences
from db.accessors.personalization_settings import settings_in_session
from db.models.preference_extraction import PreferenceExtraction
from db.models.chat_context import ChatContext
from db.models.preference_candidate import PreferenceCandidate
from db.models.preference_revision import PreferenceRevision
from sqlalchemy import select


async def eligible(session, conversation_id, message_id):
    settings = await settings_in_session(session)
    message = await candidates.source(session, conversation_id, message_id)
    if (not settings.suggest_preferences or not settings.suggestion_activation
            or settings.suggestion_activated_at is None
            or message.created_at <= settings.suggestion_activated_at
            or not 0 < len(message.content) <= 2000):
        return None
    return settings, message


async def claim(conversation_id, message_id, version):
    async with get_session_maker()() as session:
        await preferences.lock(session)
        result = await eligible(session, conversation_id, message_id)
        if result is None or await session.get(PreferenceExtraction, (message_id, version)):
            return None
        settings, message = result
        activation = settings.suggestion_activation
        session.add(PreferenceExtraction(source_message_id=message_id, extractor_version=version, activation=activation))
        await session.commit()
        return activation, message.content


async def store(conversation_id, message_id, version, activation, items):
    async with get_session_maker()() as session:
        await preferences.lock(session)
        result = await eligible(session, conversation_id, message_id)
        claim = await session.get(PreferenceExtraction, (message_id, version))
        if result is None or claim is None or claim.activation != activation:
            return
        settings, message = result
        if settings.suggestion_activation != activation:
            return
        # Consume the result slot while retaining the durable once-only claim.
        claim.activation = ''
        context = await session.get(ChatContext, message.context_id) if message.context_id else None
        scope = json.loads(context.account_scope_json) if context else {}
        selection = scope.get('selection')
        for item in items:
            account = selection if item.scope == 'account' else '*'
            if not account or (account != '*' and account not in scope.get('account_ids', [])):
                continue
            # Exact duplicates of pending suggestions or the active value add no information.
            duplicate = (await session.execute(select(PreferenceCandidate.id).where(
                PreferenceCandidate.key == item.key, PreferenceCandidate.scope == account,
                PreferenceCandidate.value == item.value, PreferenceCandidate.status == 'pending',
            ))).first()
            if duplicate:
                continue
            probe = PreferenceCandidate(key=item.key, scope=account)
            target = await candidates.current(session, probe)
            revision = await session.get(PreferenceRevision, target.revision_id) if target else None
            if revision and not revision.removed and revision.value == item.value:
                continue
            await candidates.create(session, conversation_id=conversation_id,
                source_message_id=message_id, key=item.key, scope=account, value=item.value,
                origin='extractor')
        await session.commit()

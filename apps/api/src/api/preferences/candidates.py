"""Browser candidate views and the single proposal/confirmation transaction."""
from contextlib import asynccontextmanager
from typing import Literal
from sqlalchemy.exc import SQLAlchemyError
from pydantic import BaseModel, ConfigDict, Field
from fastapi import HTTPException
from db.engine import get_session_maker
from db.accessors import preference_candidate as candidates, user_preference as preferences
from db.accessors import chat_message as messages
from api.errors import refuse


@asynccontextmanager
async def private_session():
    """Never let database diagnostics expose candidate values through API errors."""
    try:
        async with get_session_maker()() as session:
            yield session
    except SQLAlchemyError:
        raise refuse(503, 'preferences_unavailable', 'Die Präferenzen sind gerade nicht erreichbar. Versuch es gleich noch einmal.') from None


class PreferenceReference(BaseModel):
    model_config = ConfigDict(extra='forbid')
    candidate_id: str


class PreferenceDecision(BaseModel):
    model_config = ConfigDict(extra='forbid')
    choice: Literal['replace', 'keep']
    expected_version: int = Field(ge=0)
    expected_revision_id: str | None


class CandidateInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    source_message_id: str
    key: Literal['answer_length', 'salutation', 'signature']
    scope: str = Field(default='*', min_length=1, max_length=100)
    value: str = Field(min_length=1, max_length=500)


class CandidateOut(BaseModel):
    origin: Literal['explicit', 'extractor'] = 'explicit'
    id: str
    conversation_id: str
    source_message_id: str
    source_text: str | None = None
    key: Literal['answer_length', 'salutation', 'signature']
    scope: str
    account_name: str | None = None
    value: str | None
    status: Literal['pending', 'accepted', 'rejected', 'expired']
    proposal_id: str | None
    expected_version: int
    expected_revision_id: str | None
    previous_value: str | None = None
    current_value: str | None = None
    current_version: int = 0
    current_revision_id: str | None = None
    use_preferences: bool


async def view(session, row):
    previous, current, revision, account = await candidates.presentation(session, row)
    visible = row.status in {'pending', 'accepted'}
    source = await candidates.source(session, row.conversation_id, row.source_message_id) if visible else None
    return CandidateOut(origin=row.origin, id=row.id, conversation_id=row.conversation_id, source_message_id=row.source_message_id,
        source_text=source.content if source else None, key=row.key, scope=row.scope,
        account_name=(account.display_name or account.email_address) if account else None,
        value=row.value if visible else None, status=row.status, proposal_id=row.proposal_id,
        expected_version=row.expected_version, expected_revision_id=row.expected_revision_id,
        previous_value=previous.value if visible and previous and not previous.removed else None,
        current_value=revision.value if visible and revision and not revision.removed else None,
        current_version=current.version if current else 0, current_revision_id=current.revision_id if current else None,
        use_preferences=(await preferences.settings_in_session(session)).use_preferences)


def unavailable():
    return refuse(409, 'preference_candidate_gone', 'Dieser Vorschlag ist nicht mehr verfügbar. Prüfe das Konto und starte bei Bedarf eine neue Bitte.')


async def listing(candidate_id=None):
    async with private_session() as session:
        await preferences.lock(session)
        rows = await candidates.list_rows(session, candidate_id)
        result = [await view(session, row) for row in rows]
        await session.commit()
        return result


async def propose(id, *, refresh=False):
    async with private_session() as session:
        await preferences.lock(session)
        row = await candidates.get(session, id)
        try:
            await candidates.open_card(session, row, refresh=refresh)
        except (candidates.CandidateGone, preferences.InvalidPreference):
            await candidates.erase(session, row)
            await session.commit()
            raise unavailable() from None
        result = await view(session, row)
        await session.commit()
        return result


async def prepare(arguments, ctx):
    """Only the current, server-stored user message can originate an explicit request."""
    data = CandidateInput.model_validate(arguments)
    if not ctx.source_message_id or data.source_message_id != ctx.source_message_id:
        raise candidates.CandidateGone
    if data.scope != '*' and data.scope not in ctx.account_ids:
        raise preferences.InvalidPreference
    async with private_session() as session:
        await preferences.lock(session)
        source = await candidates.source(session, ctx.conversation_id, data.source_message_id)
        # A conservative explicit-request gate, not a classifier. Quoted/forwarded text
        # alone cannot open this flow. Ambiguous wording requires a new direct request.
        import re
        direct_request = (
            r'(?is)^\s*(?:(?:bitte\s+)?(?:merke?\s+dir|speichere?\s+(?:dir\s+)?(?:als\s+präferenz|dauerhaft))'
            r'|(?:please\s+)?(?:remember\s+(?:that|this)|save\s+(?:this\s+)?as\s+a\s+preference))\b'
        )
        if not re.match(direct_request, source.content):
            raise preferences.InvalidPreference
        row = await candidates.create(session, conversation_id=ctx.conversation_id, **data.model_dump())
        card = await candidates.open_card(session, row) if row.status == 'pending' else None
        await session.commit()
        return row, card


async def cancel(message, proposal_id):
    """Cancel exactly the requested card; a displaced or stale card never reaches its successor."""
    from api.mail.proposals import ProposalStateError
    async with private_session() as session:
        await preferences.lock(session)
        row = await candidates.get(session, message.preference.candidate_id)
        card = await candidates.cancel_card(session, row, proposal_id)
        if card is None:
            raise ProposalStateError
        await session.commit()
        return card


async def confirm(message_id, decision):
    from api.mail import proposals
    async with private_session() as session:
        await preferences.lock(session)
        claimed = await messages.claim_proposal_in_session(session, message_id)
        if claimed is None:
            current = await messages.get_message(message_id)
            if current and current.proposal_status == 'pending':
                raise proposals.ProposalContextRevokedError
            raise proposals.ProposalStateError
        proposal = proposals.proposal_view(claimed)
        row = await candidates.get(session, proposal.preference.candidate_id)
        if row.proposal_id != claimed.id or row.conversation_id != claimed.conversation_id:
            raise unavailable()
        try:
            outcome = await candidates.accept(session, row, decision=decision.choice,
                expected_version=decision.expected_version, expected_revision_id=decision.expected_revision_id)
        except candidates.CandidateConflict:
            current = await view(session, row)
            raise HTTPException(409, detail={'code': 'preference_candidate_conflict', 'current': current.model_dump()},
                                headers={'Cache-Control': 'no-store'}) from None
        except (candidates.CandidateGone, preferences.InvalidPreference):
            raise unavailable() from None
        except preferences.PreferenceConflict:
            raise refuse(409, 'preference_quota', 'Die Grenze für Präferenzen ist erreicht. Entferne zuerst einen gespeicherten Wert.') from None
        proposal.result = proposals.ProposalResult(done=1 if outcome == 'saved' else 0,
            preference_outcome=outcome, preferences_enabled=(await preferences.settings_in_session(session)).use_preferences)
        updated = await messages.finish_proposal_in_session(session, claimed.id, proposal_json=proposal.model_dump_json())
        await session.commit()
        return updated

"""Typed candidate dispatch and browser-only confirmation contracts."""
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock
import json
import pytest
from pydantic import ValidationError
from api.mail.agent_tools import TurnContext, execute_tool, TOOLS
from api.mail import proposals
from api.preferences import candidates
from api.routers.api.v1.chat.proposals import ProposalConfirmIn


def test_tool_is_proposal_only_and_has_bounded_fields():
    tool = next(t['function'] for t in TOOLS if t['function']['name'] == 'propose_preference')
    assert set(tool['parameters']['properties']) == {'source_message_id', 'key', 'scope', 'value'}
    assert tool['parameters']['properties']['value']['maxLength'] == 500
    assert not any('confirm' in t['function']['name'] for t in TOOLS)


@pytest.mark.parametrize('extra', [{'confirmed': True}, {'origin': 'user'}, {'owner_scope': 'other'}])
def test_claimed_authority_is_rejected(extra):
    with pytest.raises(ValidationError):
        candidates.CandidateInput.model_validate(dict(source_message_id='user', key='answer_length', value='Kurz', **extra))


@pytest.mark.asyncio
async def test_free_source_id_rejected_before_database():
    ctx = TurnContext('conversation', None, date.today(), source_message_id='current')
    with pytest.raises(candidates.candidates.CandidateGone):
        await candidates.prepare({'source_message_id': 'other', 'key': 'answer_length', 'value': 'Kurz'}, ctx)


@pytest.mark.asyncio
async def test_account_outside_turn_rejected_before_database():
    ctx = TurnContext('conversation', 'one', date.today(), account_ids=['one'], source_message_id='current')
    with pytest.raises(candidates.preferences.InvalidPreference):
        await candidates.prepare({'source_message_id': 'current', 'key': 'signature', 'scope': 'two', 'value': 'test-only'}, ctx)


@pytest.mark.asyncio
async def test_dispatch_returns_ids_not_values_and_never_confirms(monkeypatch):
    prepare = AsyncMock(return_value=(SimpleNamespace(id='candidate', proposal_id=None, status='pending'), None))
    monkeypatch.setattr(candidates, 'prepare', prepare)
    confirm = AsyncMock()
    monkeypatch.setattr(proposals, 'confirm', confirm)
    outcome = await execute_tool('propose_preference', {}, TurnContext('conversation', None, date.today()))
    assert json.loads(outcome.content) == {'candidate_id': 'candidate', 'proposal_id': None, 'status': 'pending', 'requires_confirmation': True}
    assert outcome.proposal_message is None
    confirm.assert_not_called()


@pytest.mark.asyncio
async def test_typed_confirmation_cannot_be_used_on_other_kinds(monkeypatch):
    message = SimpleNamespace(role='proposal', proposal_json=proposals.Proposal(kind='archive', reason='', items=[]).model_dump_json())
    monkeypatch.setattr(proposals, '_get_proposal', AsyncMock(return_value=message))
    with pytest.raises(proposals.ProposalSelectionError):
        await proposals.confirm('card', selected_ids=[], preference_decision=candidates.PreferenceDecision(choice='replace', expected_version=0, expected_revision_id=None))


def test_confirm_rejects_untyped_or_extra_authority():
    with pytest.raises(ValidationError):
        ProposalConfirmIn.model_validate({'selected_ids': [], 'confirmed': True})
    with pytest.raises(ValidationError):
        candidates.PreferenceDecision.model_validate({'choice': 'merge', 'expected_version': 1, 'expected_revision_id': 'revision'})
    with pytest.raises(ValidationError):
        candidates.PreferenceDecision.model_validate({'choice': 'replace', 'expected_version': 1, 'expected_revision_id': 'revision', 'value': 'override'})


def test_card_payload_has_no_value_copy():
    proposal = proposals.Proposal(kind='preference', reason='', items=[], preference=candidates.PreferenceReference(candidate_id='candidate'))
    assert proposal.preference.model_dump() == {'candidate_id': 'candidate'}
    with pytest.raises(ValidationError):
        proposals.Proposal(kind='preference', reason='', items=[], preference={'candidate_id': 'candidate', 'value': 'hidden'})

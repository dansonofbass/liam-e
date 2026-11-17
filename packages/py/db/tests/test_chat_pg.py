"""Live Postgres contracts for chat proposals."""

import asyncio
import os

import pytest
from sqlalchemy.exc import IntegrityError

pytestmark = pytest.mark.skipif(not os.getenv("RUN_PG_CONTRACT"), reason="RUN_PG_CONTRACT is not set")


def test_only_one_pending_proposal_per_conversation(pg_db):
    async def run():
        from db.accessors import chat_message as m
        await m.add_message(conversation_id="a", role="proposal", proposal_status="pending")
        with pytest.raises(IntegrityError):
            await m.add_message(conversation_id="a", role="proposal", proposal_status="pending")
        await m.add_message(conversation_id="b", role="proposal", proposal_status="pending")
    asyncio.run(run())


def test_claim_proposal_is_atomic(pg_db):
    async def run():
        from db.accessors import chat_message as m
        row = await m.add_message(conversation_id="a", role="proposal", proposal_status="pending")
        results = await asyncio.gather(*(m.claim_proposal(row.id) for _ in range(2)))
        assert sum(x is not None for x in results) == 1
        assert next(x for x in results if x is not None).proposal_status == "running"
    asyncio.run(run())


def test_claim_requires_live_context_or_legacy(pg_db):
    async def run():
        from db.accessors import chat_message as m
        from db.engine import get_session_maker
        from db.models.chat_context import ChatContext
        async with get_session_maker()() as session:
            live = ChatContext(conversation_id="live", app_prompt_version="1", account_scope_json="{}")
            revoked = ChatContext(conversation_id="revoked", app_prompt_version="1", account_scope_json="{}", revoked=True)
            session.add_all([live, revoked])
            await session.commit()
        denied = await m.add_message(conversation_id="revoked", role="proposal", proposal_status="pending", context_id=revoked.id)
        assert await m.claim_proposal(denied.id) is None
        assert (await m.get_message(denied.id)).proposal_status == "pending"
        assert (await m.cancel_proposal(denied.id)).proposal_status == "cancelled"
        allowed = await m.add_message(conversation_id="live", role="proposal", proposal_status="pending", context_id=live.id)
        assert (await m.claim_proposal(allowed.id)).proposal_status == "running"
        legacy = await m.add_message(conversation_id="legacy", role="proposal", proposal_status="pending")
        assert (await m.claim_proposal(legacy.id)).proposal_status == "running"
    asyncio.run(run())


def test_cancel_open_proposals(pg_db):
    async def run():
        from db.accessors import chat_message as m
        row = await m.add_message(conversation_id="a", role="proposal", proposal_status="pending")
        assert (await m.open_proposal("a")).id == row.id
        assert await m.cancel_open_proposals("a") == 1
        assert await m.open_proposal("a") is None
        assert (await m.get_message(row.id)).proposal_status == "cancelled"
        assert await m.cancel_open_proposals("a") == 0
    asyncio.run(run())


def test_cancel_proposal_only_from_pending(pg_db):
    async def run():
        from db.accessors import chat_message as m
        row = await m.add_message(conversation_id="a", role="proposal", proposal_status="pending")
        assert (await m.cancel_proposal(row.id)).proposal_status == "cancelled"
        assert await m.cancel_proposal(row.id) is None
        assert await m.cancel_proposal("missing") is None
        for status in ("running", "done", "partial", "failed"):
            await m.set_proposal(row.id, proposal_json="{}", proposal_status=status)
            assert await m.cancel_proposal(row.id) is None
            assert (await m.get_message(row.id)).proposal_status == status
    asyncio.run(run())


def test_conversation_and_message_fields(pg_db):
    async def run():
        from db.accessors import chat_conversation as c, chat_message as m
        conversation = await c.create_conversation(title="old", model="one")
        row = await m.add_message(conversation_id=conversation.id, role="proposal", proposal_json="{}", proposal_status="pending", stopped=True, extras_json="{}")
        assert (row.proposal_json, row.stopped, row.extras_json) == ("{}", True, "{}")
        updated = await m.set_proposal(row.id, proposal_json='{"x":1}', proposal_status="done")
        assert (updated.proposal_json, updated.proposal_status) == ('{"x":1}', "done")
        assert await m.set_proposal("missing", proposal_json="", proposal_status="failed") is None
    asyncio.run(run())

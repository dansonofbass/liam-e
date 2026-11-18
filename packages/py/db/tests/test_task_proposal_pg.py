"""Caller-owned proposal transactions for local task mutations (no providers)."""

import asyncio
import os
from datetime import date

import pytest

pytestmark = pytest.mark.skipif(not os.getenv('RUN_PG_CONTRACT'), reason='RUN_PG_CONTRACT is not set')


@pytest.mark.parametrize('failure_point', ['claim', 'mutation', 'finish'])
def test_local_proposal_rollback_concurrency_and_retry(pg_db, failure_point):
    async def run():
        from db.accessors import chat_message
        from db.engine import get_session_maker
        from api.tasks.create import create

        message = await chat_message.add_message(conversation_id='synthetic', role='proposal',
                                                 proposal_status='pending', proposal_json='{}')

        async def execute(fail=False):
            async with get_session_maker()() as session:
                claimed = await chat_message.claim_proposal_in_session(session, message.id)
                if claimed is None:
                    return False
                if fail and failure_point == 'claim':
                    raise RuntimeError('test-only interruption')
                await create(session, creation_key=message.id, title='Example',
                             start=date(2027, 1, 1), zone='UTC')
                if fail and failure_point == 'mutation':
                    raise RuntimeError('test-only interruption')
                await chat_message.finish_proposal_in_session(session, message.id, proposal_json='{"done":1}')
                if fail and failure_point == 'finish':
                    raise RuntimeError('test-only interruption')
                await session.commit()
                return True

        with pytest.raises(RuntimeError, match='test-only interruption'):
            await execute(fail=True)
        assert (await chat_message.get_message(message.id)).proposal_status == 'pending'
        # A different payload with the same creation key proves the first insert rolled back.
        async with get_session_maker()() as session:
            _, created = await create(session, creation_key=message.id, title='Rollback probe',
                                      start=date(2027, 1, 1), zone='UTC')
            assert created
            await session.rollback()
        assert sorted(await asyncio.gather(execute(), execute())) == [False, True]
        # Simulate losing the response after commit: retry cannot claim or mutate again.
        assert not await execute()
        stored = await chat_message.get_message(message.id)
        assert stored.proposal_status == 'done'
        assert stored.proposal_json == '{"done":1}'

    asyncio.run(run())


def test_local_proposal_revoked_context_cannot_claim(pg_db):
    async def run():
        from db.accessors import chat_message
        from db.engine import get_session_maker
        from db.models.chat_context import ChatContext

        async with get_session_maker()() as session:
            context = ChatContext(conversation_id='synthetic', revoked=True,
                                  app_prompt_version='test-only', account_scope_json='{}')
            session.add(context)
            await session.commit()
        message = await chat_message.add_message(conversation_id='synthetic', role='proposal',
                                                 proposal_status='pending', context_id=context.id)
        async with get_session_maker()() as session:
            assert await chat_message.claim_proposal_in_session(session, message.id) is None
            await session.commit()
        assert (await chat_message.get_message(message.id)).proposal_status == 'pending'

    asyncio.run(run())

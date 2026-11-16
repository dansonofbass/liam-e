"""Live Postgres uniqueness and retry contracts for task rows."""

import asyncio
import os

import pytest

pytestmark = pytest.mark.skipif(not os.getenv('RUN_PG_CONTRACT'), reason='RUN_PG_CONTRACT is not set')


def test_creation_and_occurrence_retries_are_idempotent(pg_db):
    async def run():
        from db.accessors import task_occurrence, task_series
        from db.engine import get_session_maker
        from db.models.task_occurrence import TaskOccurrence
        from db.models.task_series import TaskSeries

        async with get_session_maker()() as session:
            first, created = await task_series.create_once(session, TaskSeries(scope='app', creation_key='request-1', creation_hash='hash-1', title='Example'))
            assert created
            original_id = first.id
            await session.commit()
        async with get_session_maker()() as session:
            duplicate, created = await task_series.create_once(session, TaskSeries(scope='app', creation_key='request-1', creation_hash='hash-2', title='Other'))
            assert not created and duplicate.id == original_id and duplicate.creation_hash == 'hash-1'
            row = TaskOccurrence(series_id=original_id, revision_id='revision-1', occurrence_key='2024-01-01', due_local='2024-01-01')
            assert await task_occurrence.insert_once(session, row)
            await session.commit()
        async with get_session_maker()() as session:
            retry = TaskOccurrence(series_id=original_id, revision_id='revision-1', occurrence_key='2024-01-01', due_local='2024-01-01')
            assert not await task_occurrence.insert_once(session, retry)
            await session.commit()

    asyncio.run(run())

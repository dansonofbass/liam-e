"""Real Postgres preference uniqueness, quotas, revisions and deletion contracts."""
import asyncio
import os
import pytest

pytestmark = pytest.mark.skipif(not os.getenv('RUN_PG_CONTRACT'), reason='RUN_PG_CONTRACT is not set')


def test_revision_concurrency_and_account_removal(pg_db):
    async def run():
        from db.accessors import user_preference as p, preference_revision as r, mail_account as a
        account = await a.create_account(provider='imap', auth_type='imap_password', email_address='pref@example.test')
        row = await p.create(key='signature', scope=account.id, value='test-only')
        results = await asyncio.gather(p.change(row.id, 1, value='test-only two'),
                                       p.change(row.id, 1, value='test-only three'), return_exceptions=True)
        assert sum(isinstance(x, p.StaleVersion) for x in results) == 1
        assert (await r.get_revisions([row.revision_id]))[0].value == 'test-only'
        assert (await p.settings()).use_preferences is False
        await p.update_settings(1, use_preferences=True)
        with pytest.raises(p.StaleVersion):
            await p.update_settings(1, use_preferences=False)
        with pytest.raises(p.InvalidPreference):
            await p.update_settings(2, suggest_preferences=True)
        assert await a.delete_account(account.id)
        assert await p.list_preferences() == []
        old = (await r.get_revisions([row.revision_id]))[0]
        assert old.removed and old.value is None
        with pytest.raises(p.InvalidPreference):
            await p.create(key='signature', scope=account.id, value='test-only')
    asyncio.run(run())


def test_unique_double_click_and_value_limit(pg_db):
    async def run():
        from db.accessors import user_preference as p
        from db.models.user_preference import UserPreference
        from db.engine import get_session_maker
        from sqlalchemy.exc import IntegrityError
        results = await asyncio.gather(*[p.create(key='answer_length', value='test-only') for _ in range(2)], return_exceptions=True)
        assert sum(isinstance(x, p.PreferenceConflict) for x in results) == 1
        async with get_session_maker()() as session:
            session.add(UserPreference(key='answer_length'))
            with pytest.raises(IntegrityError):
                await session.commit()
        row = (await p.list_preferences())[0]
        paused = await p.change(row.id, 1, status='paused')
        replacement = await p.create(key='answer_length', value='x' * 500)
        with pytest.raises(p.PreferenceConflict):
            await p.change(paused.id, 2, status='active')
        with pytest.raises(p.InvalidPreference):
            await p.change(replacement.id, 1, value='x' * 501)
        await p.change(replacement.id, 1, delete=True)
        assert (await p.change(paused.id, 2, status='active')).status == 'active'
    asyncio.run(run())


def test_stored_and_active_limits(pg_db):
    async def run():
        from db.accessors import user_preference as p, mail_account as a
        for i in range(21):
            account = await a.create_account(provider='imap', auth_type='imap_password', email_address=f'pref{i}@example.test')
            if i < 20:
                await p.create(key='signature', scope=account.id, value='test-only')
            else:
                with pytest.raises(p.PreferenceConflict):
                    await p.create(key='signature', scope=account.id, value='test-only')
        for _ in range(30):
            await p.create(key='answer_length', value='test-only', status='paused')
        with pytest.raises(p.PreferenceConflict):
            await p.create(key='answer_length', value='test-only', status='paused')
        assert len(await p.list_preferences()) == 50
    asyncio.run(run())

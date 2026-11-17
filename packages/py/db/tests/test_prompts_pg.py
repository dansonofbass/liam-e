"""Live revision, concurrency, scope and revocation contracts."""
import asyncio
import json
import os
import pytest

pytestmark = pytest.mark.skipif(not os.getenv('RUN_PG_CONTRACT'), reason='RUN_PG_CONTRACT is not set')


def test_revisions_concurrent_updates_and_revocation(pg_db):
    async def run():
        from db.accessors import prompt_template as p, prompt_revision as r, chat_context as c
        from db.accessors import chat_conversation as conversations
        from db.accessors import chat_message as messages
        first = await p.create_template('Test', 'Synthetische Vorlage')
        conversation, snapshot, content = await c.resolve(conversation_id=None, title='Test', model='',
            revision_id=first.revision_id, account_id=None, app_prompt_version='test')
        await messages.add_message(conversation_id=conversation.id, role='user', content='Hallo', context_id=snapshot.id)
        results = await asyncio.gather(
            p.change_template(first.id, 1, content='Zweiter Stand'),
            p.change_template(first.id, 1, content='Dritter Stand'), return_exceptions=True)
        assert sum(isinstance(x, p.StaleVersion) for x in results) == 1
        current = await p.get_template(first.id)
        assert current.version == 2
        assert [rev.number for rev in await r.list_revisions(first.id)] == [2, 1]
        _, pinned, old_content = await c.resolve(conversation_id=None, title='', model='',
            revision_id=first.revision_id, account_id=None, app_prompt_version='test')
        assert pinned.prompt_revision_id == first.revision_id and old_content == content
        assert (await r.get_revision(first.revision_id)).content == content
        assert (await conversations.get_conversation(conversation.id)).prompt_revision_id == first.revision_id
        changes = await asyncio.gather(
            c.configure(conversation.id, 1, revision_id=current.revision_id, change_revision=True),
            c.configure(conversation.id, 1, revision_id=None, change_revision=True), return_exceptions=True)
        assert sum(isinstance(x, p.StaleVersion) for x in changes) == 1
        configured = await conversations.get_conversation(conversation.id)
        await conversations.touch_conversation(conversation)
        assert (await conversations.get_conversation(conversation.id)).prompt_revision_id == configured.prompt_revision_id
        assert (await c.get_context(snapshot.id)).prompt_revision_id == first.revision_id
        assert await c.is_live(snapshot.id)
        await p.change_template(first.id, 2, delete=True)
        assert not await c.is_live(snapshot.id)
        assert (await c.get_context(snapshot.id)).prompt_hash is None
        removed = await r.get_revision(first.revision_id)
        assert removed.removed and removed.content is None and removed.content_hash is None
        assert await p.get_template(first.id) is None
        assert (await conversations.get_conversation(conversation.id)).prompt_revision_id is None
        assert (await messages.list_messages(conversation.id))[0].content == 'Hallo'
        _, next_snapshot, next_content = await c.resolve(conversation_id=conversation.id, title='', model='',
            revision_id=None, account_id=None, app_prompt_version='test')
        assert next_snapshot.prompt_revision_id is None and next_content is None
        with pytest.raises(c.ContextUnavailable):
            await c.resolve(conversation_id=None, title='', model='', revision_id=first.revision_id,
                            account_id=None, app_prompt_version='test')
    asyncio.run(run())


def test_account_scope_and_unknown_history(pg_db):
    async def run():
        from db.accessors import mail_account as accounts, chat_context as c
        from db.accessors import chat_conversation as conversations, chat_message as messages
        a = await accounts.create_account(provider='imap', auth_type='imap_password', email_address='a@example.test')
        async def resolve(id=None, account=None):
            return await c.resolve(conversation_id=id, title='', model='', revision_id=None,
                                   account_id=account, app_prompt_version='test')
        legacy_single = await conversations.create_conversation()
        await messages.add_message(conversation_id=legacy_single.id, role='user', content='Unbelegte Herkunft')
        await resolve(legacy_single.id)
        with pytest.raises(c.ScopeChange):
            await resolve(legacy_single.id, a.id)
        b = await accounts.create_account(provider='imap', auth_type='imap_password', email_address='b@example.test')
        with pytest.raises(ValueError):
            await resolve(account='invalid')
        for initial, rejected in [(a.id, b.id), (a.id, None), (None, a.id), (b.id, a.id)]:
            conversation, snapshot, _ = await resolve(account=initial)
            assert json.loads(snapshot.account_scope_json)['account_ids'] == sorted([initial] if initial else [a.id, b.id])
            await messages.add_message(conversation_id=conversation.id, role='user', content='Test')
            with pytest.raises(c.ScopeChange):
                await resolve(conversation.id, rejected)
            await resolve(conversation.id, initial)
        everything, _, _ = await resolve()
        await messages.add_message(conversation_id=everything.id, role='user', content='Test')
        added = await accounts.create_account(provider='imap', auth_type='imap_password', email_address='c@example.test')
        _, snapshot, _ = await resolve(everything.id)
        assert json.loads(snapshot.account_scope_json)['account_ids'] == sorted([a.id, b.id, added.id])
        with pytest.raises(c.ScopeChange):
            await resolve(everything.id, added.id)
        legacy = await conversations.create_conversation()
        await messages.add_message(conversation_id=legacy.id, role='assistant', content='Altverlauf')
        with pytest.raises(c.ScopeChange):
            await resolve(legacy.id, a.id)
        _, snapshot, _ = await resolve(legacy.id)
        assert json.loads(snapshot.account_scope_json)['legacy_mixed'] is True
        with pytest.raises(c.ScopeChange):
            await resolve(legacy.id, a.id)
    asyncio.run(run())


def test_unchanged_update_keeps_version_and_revision(pg_db):
    async def run():
        from db.accessors import prompt_template as p
        row = await p.create_template('Name', 'Text')
        for same in (await p.change_template(row.id, 1), await p.change_template(row.id, 1, name='Name', content='Text')):
            assert (same.version, same.revision_id) == (1, row.revision_id)
        with pytest.raises(p.StaleVersion):
            await p.change_template(row.id, 2)
        renamed = await p.change_template(row.id, 1, name='Neu')
        assert renamed.version == 2 and renamed.revision_id != row.revision_id
    asyncio.run(run())

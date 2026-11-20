"""Live PostgreSQL contracts for skill revisions, concurrency, turn binding, and revocation."""

import asyncio
import json
import os

import pytest

pytestmark = pytest.mark.skipif(not os.getenv("RUN_PG_CONTRACT"), reason="RUN_PG_CONTRACT is not set")


def test_builtin_sync_concurrency_and_custom_revision_conflicts(pg_db):
    async def run():
        from api.skills.catalog import ensure_builtin_skills
        from db.accessors import skill_definition as s, skill_revision as r

        # Concurrent builtin catalog sync creates one daily_briefing row cleanly
        synced = await asyncio.gather(*(ensure_builtin_skills() for _ in range(3)))
        assert len({row.id for batch in synced for row in batch if row.slug == "daily_briefing"}) == 1

        builtin = await s.get_skill("daily_briefing")
        assert builtin is not None and builtin.origin == "builtin" and builtin.status == "active"

        # Owner disables builtin; re-syncing builtin catalog preserves disabled status
        disabled = await s.change_skill(builtin.id, 1, status="disabled")
        assert disabled.version == 2 and disabled.status == "disabled"
        await ensure_builtin_skills()
        assert (await s.get_skill("daily_briefing")).status == "disabled"

        # Custom skill concurrent creation with same slug allows only one winner
        created = await asyncio.gather(
            s.create_custom_skill(
                slug="concurrent_skill",
                name="One",
                description="Desc",
                instructions="Step 1",
                workflow_steps_json="[]",
                allowed_tools_json='["search_messages"]',
            ),
            s.create_custom_skill(
                slug="concurrent_skill",
                name="Two",
                description="Desc",
                instructions="Step 1",
                workflow_steps_json="[]",
                allowed_tools_json='["search_messages"]',
            ),
            return_exceptions=True,
        )
        assert sum(isinstance(x, s.DuplicateSkillSlug) for x in created) == 1
        custom = next(x for x in created if not isinstance(x, Exception))

        # Concurrent PATCH with same expected_version allows exactly one update
        updates = await asyncio.gather(
            s.change_skill(custom.id, 1, instructions="Updated A"),
            s.change_skill(custom.id, 1, instructions="Updated B"),
            return_exceptions=True,
        )
        assert sum(isinstance(x, s.StaleVersion) for x in updates) == 1
        current = await s.get_skill(custom.id)
        assert current.version == 2
        assert [rev.number for rev in await r.list_revisions(custom.id)] == [2, 1]

    asyncio.run(run())


def test_skill_turn_binding_revocation_tombstones_and_proposal_claims(pg_db):
    async def run():
        from db.accessors import chat_context as c
        from db.accessors import chat_message as m
        from db.accessors import skill_definition as s
        from db.accessors import skill_revision as r
        from db.engine import get_session_maker

        custom = await s.create_custom_skill(
            slug="weekly_summary",
            name="Wochenrückblick",
            description="Fasst ungelesene Mails zusammen",
            instructions="Lies nur den Posteingang.",
            workflow_steps_json='[{"id":"read","title":"Lesen","description":"Suche Mails","tool_names":["search_messages"]}]',
            allowed_tools_json='["get_message","search_messages"]',
        )
        first_rev_id = custom.revision_id

        # Turn 1 binds skill_id, skill_revision_id, skill_hash
        conv, snap1, _ = await c.resolve(
            conversation_id=None,
            title="Skill Chat",
            model="",
            revision_id=None,
            account_id=None,
            app_prompt_version="15",
            skill_id=custom.slug,
            allowed_tool_names={"get_message", "search_messages"},
        )
        assert snap1.skill_id == custom.id
        assert snap1.skill_revision_id == first_rev_id
        assert snap1.skill_hash is not None
        await m.add_message(conversation_id=conv.id, role="user", content="Start", context_id=snap1.id)
        prop1 = await m.add_message(
            conversation_id=conv.id,
            role="proposal",
            proposal_status="pending",
            context_id=snap1.id,
        )

        # Turn 2 in same conversation without skill_id runs with skill_revision_id=None
        _, snap2, _ = await c.resolve(
            conversation_id=conv.id,
            title="",
            model="",
            revision_id=None,
            account_id=None,
            app_prompt_version="15",
        )
        assert snap2.skill_id is None and snap2.skill_revision_id is None and snap2.skill_hash is None
        assert await c.is_live(snap1.id) and await c.is_live(snap2.id)

        # Expanding allowed_tools keeps existing context live; narrowing revokes it
        v2 = await s.change_skill(
            custom.id,
            1,
            allowed_tools_json='["get_message","list_accounts","search_messages"]',
        )
        assert v2.version == 2 and await c.is_live(snap1.id)

        v3 = await s.change_skill(
            custom.id,
            2,
            allowed_tools_json='["search_messages"]',
        )
        assert v3.version == 3
        assert not await c.is_live(snap1.id)
        assert (await c.get_context(snap1.id)).revoked is True
        # Non-skill turn in the same conversation remains unaffected
        assert await c.is_live(snap2.id)
        # Claiming pending proposal from revoked skill turn fails atomically; cancelling still succeeds
        assert await m.claim_proposal(prop1.id) is None
        assert await m.cancel_proposal(prop1.id) is not None

        # Bind a new turn on v3, then disable -> blocks new turns and proposal claims
        conv2, snap3, _ = await c.resolve(
            conversation_id=None,
            title="Skill Chat 2",
            model="",
            revision_id=None,
            account_id=None,
            app_prompt_version="15",
            skill_id=custom.slug,
            allowed_tool_names={"search_messages"},
        )
        prop3 = await m.add_message(
            conversation_id=conv2.id,
            role="proposal",
            proposal_status="pending",
            context_id=snap3.id,
        )
        # Verify claim_proposal_in_session (used by task/preference confirmations) respects active skill check
        await s.change_skill(custom.id, 3, status="disabled")
        assert not await c.is_live(snap3.id)
        async with get_session_maker()() as session:
            assert await m.claim_proposal_in_session(session, prop3.id) is None
        assert await m.claim_proposal(prop3.id) is None
        with pytest.raises(c.SkillDisabled):
            await c.resolve(
                conversation_id=None,
                title="Blocked",
                model="",
                revision_id=None,
                account_id=None,
                app_prompt_version="15",
                skill_id=custom.slug,
            )

        # Legacy context without skill_revision_id remains unaffected
        from db.models.chat_context import ChatContext
        async with get_session_maker()() as session:
            legacy = ChatContext(
                conversation_id="legacy-conv",
                app_prompt_version="14",
                account_scope_json='{"account_ids":[],"selection":null}',
                mail_scope_version=1,
            )
            session.add(legacy)
            await session.commit()
            assert legacy.skill_id is None and legacy.skill_revision_id is None and legacy.skill_hash is None
            assert await c.is_live(legacy.id)

        # Delete custom skill -> tombstones all revisions, clears skill_hash, leaves non-skill turn intact
        await s.change_skill(custom.id, 4, delete=True)
        assert await s.get_skill(custom.id) is None
        tombstone = await r.get_revision(first_rev_id)
        assert tombstone is not None and tombstone.removed is True
        assert tombstone.instructions is None and tombstone.allowed_tools_json is None
        assert (await c.get_context(snap3.id)).skill_hash is None
        assert await m.cancel_proposal(prop3.id) is not None
        assert await c.is_live(snap2.id)

        # Missing tool in server code refuses before creating any context
        recreated = await s.create_custom_skill(
            slug="tool_gone",
            name="Tool Gone",
            description="Uses missing tool",
            instructions="Test",
            workflow_steps_json="[]",
            allowed_tools_json='["removed_server_tool"]',
        )
        with pytest.raises(c.SkillToolUnavailable):
            await c.resolve(
                conversation_id=None,
                title="Fail",
                model="",
                revision_id=None,
                account_id=None,
                app_prompt_version="15",
                skill_id=recreated.slug,
                allowed_tool_names={"search_messages"},
            )
        async with get_session_maker()() as session:
            # Verify no context leaked on SkillToolUnavailable
            from sqlalchemy import select
            from db.models.chat_context import ChatContext
            leaked = (await session.execute(select(ChatContext).where(ChatContext.skill_id == recreated.id))).scalars().all()
            assert leaked == []

    asyncio.run(run())

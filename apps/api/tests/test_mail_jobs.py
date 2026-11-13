from datetime import datetime, timedelta, timezone

import pytest
from db.models.mail_account import MailAccount
from db.models.mail_sync_state import MailSyncState

from api.mail import jobs
from api.lifespan.startup import mail_worker


def account(store, name):
    row = MailAccount(provider="imap", auth_type="imap_password", email_address=f"{name}@example.test")
    store.accounts[row.id] = row
    return row


@pytest.mark.anyio
async def test_run_once_runs_handler_and_finishes(fake_store):
    seen = []
    async def handler(payload):
        seen.append(payload)
    jobs.register_handler("test", handler)
    await fake_store.enqueue("test", {"account_id": "a"}, dedupe_key="test:a")
    assert await jobs.run_once()
    assert seen == [{"account_id": "a"}]
    assert next(iter(fake_store.jobs.values())).status == "done"


@pytest.mark.anyio
async def test_run_once_retries_then_fails_for_good(fake_store):
    async def handler(payload):
        raise ValueError("provider text")
    jobs.register_handler("failing", handler)
    job = await fake_store.enqueue("failing", {}, dedupe_key="failing")
    now = datetime.now(timezone.utc) + timedelta(seconds=1)
    for attempt in range(1, 4):
        assert await jobs.run_once(now)
        assert job.attempts == attempt
        assert job.last_error == "ValueError"
        if attempt < 3:
            assert job.status == "queued"
            assert job.run_after == now + timedelta(seconds=30 * attempt)
            now = job.run_after
    assert job.status == "failed"


@pytest.mark.anyio
async def test_job_for_deleted_account_fails_without_retry(fake_store):
    await jobs.enqueue_sync("missing")
    assert await jobs.run_once(datetime.now(timezone.utc) + timedelta(seconds=1))
    assert next(iter(fake_store.jobs.values())).status == "failed"


@pytest.mark.anyio
async def test_poll_enqueues_due_accounts(fake_store):
    now = datetime.now(timezone.utc)
    a, b, c, d = [account(fake_store, str(i)) for i in range(4)]
    for row, minutes, error in [(a, 2, ""), (b, 7, ""), (d, 30, "auth_expired")]:
        fake_store.states[row.id] = MailSyncState(account_id=row.id, last_sync_at=now-timedelta(minutes=minutes), last_error=error)
    assert await jobs.enqueue_due_syncs(now, older_than_minutes=5, skip_auth_expired=True) == [b.id, c.id]


def test_worker_loop_polls_once_per_interval():
    now = datetime.now(timezone.utc)
    assert jobs.poll_due(now, None, 5)
    assert not jobs.poll_due(now + timedelta(minutes=4), now, 5)
    assert jobs.poll_due(now + timedelta(minutes=5), now, 5)
    assert not jobs.poll_due(now, None, 0)


@pytest.mark.anyio
async def test_worker_not_started_when_disabled(monkeypatch):
    from fastapi import FastAPI
    monkeypatch.setattr(mail_worker.mail_env, "mail_worker_enabled", False)
    app = FastAPI()
    await mail_worker.startup(app)
    assert not hasattr(app.state, "mail_worker")

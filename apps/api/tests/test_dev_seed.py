"""Tests for the local development seed's database safety guard."""

import pytest

from datetime import UTC, datetime

from api.mail import dev_seed
from api.mail.dev_seed import SeedRefusedError, db_env, require_local_database
from db.models.mail_account import MailAccount
from db.models.mail_message import MailMessage


@pytest.mark.parametrize("url", [
    "postgresql+asyncpg://u:p@db.example.com:5432/x",
    "postgresql+asyncpg://u:p@10.0.0.5:5432/x",
    "postgresql+asyncpg:///x",
    "postgresql+asyncpg:///x?host=/var/run/postgresql",
    "postgresql+asyncpg://u:p@localhost/x?host=db.example.com",
])
def test_refuses_nonlocal_database(monkeypatch, url):
    monkeypatch.setattr(db_env, "database_url", url)
    with pytest.raises(SeedRefusedError) as error:
        require_local_database()
    assert "u:p" not in str(error.value)


@pytest.mark.parametrize("host", ["localhost", "LOCALHOST", "127.0.0.1", "[::1]"])
def test_allows_local_database(monkeypatch, host):
    monkeypatch.setattr(db_env, "database_url", f"postgresql+asyncpg://u:p@{host}/x")
    require_local_database()


@pytest.mark.anyio
async def test_seed_is_repeatable_and_preserves_other_rows(fake_store, monkeypatch):
    monkeypatch.setattr(db_env, "database_url", "postgresql+asyncpg://localhost/test")
    outsider = MailAccount(id="other", email_address="other@example.org", provider="imap", auth_type="imap_password")
    other_mail = MailMessage(id="other-mail", account_id=outsider.id, provider_uid="other")
    fake_store.accounts[outsider.id] = outsider
    fake_store.messages[other_mail.id] = other_mail
    insights = {}

    async def replace(accounts, states, messages, rows, jobs):
        for account in accounts:
            fake_store.accounts.pop(account.id, None)
        for state in states:
            fake_store.states.pop(state.account_id, None)
        for message in messages:
            fake_store.messages.pop(message.id, None)
            insights.pop(message.id, None)
        fake_store.jobs.update({row.id: row for row in jobs})
        fake_store.accounts.update({row.id: row for row in accounts})
        fake_store.states.update({row.account_id: row for row in states})
        fake_store.messages.update({row.id: row for row in messages})
        insights.update({row.message_id: row for row in rows})

    monkeypatch.setattr(dev_seed.seed_access, "replace_mail_data", replace)
    now = datetime(2026, 11, 13, 12, 30, tzinfo=UTC)
    for _ in range(2):
        result = await dev_seed.seed(now)
        assert (result.accounts, result.mails, result.unread, result.insights) == (4, 67, 47, 1)
        assert len(fake_store.accounts) == 5
        assert len(fake_store.messages) == 68
        assert len(insights) == 1
        assert sum(not mail.is_read and mail.folder == "INBOX" for mail in fake_store.messages.values() if mail.id != "other-mail") == 47
        assert fake_store.states[dev_seed.seed_id("account", "arbeit")].last_error == "auth_expired"
        job = fake_store.jobs[dev_seed.seed_id("job", "familie")]
        assert job.status == "running"
        assert job.locked_at == datetime(2026, 11, 13, 12, 29, tzinfo=UTC)
        assert fake_store.accounts["other"] == outsider
        assert fake_store.messages["other-mail"] == other_mail
        house = fake_store.messages[dev_seed.seed_id("mail", "hausverwaltung-nebenkosten")]
        assert house.internal_date == datetime(2026, 11, 13, 7, 57, tzinfo=UTC)
        assert insights[house.id].deadline.isoformat() == "2026-11-20"


@pytest.mark.anyio
async def test_seed_refuses_before_access(monkeypatch):
    monkeypatch.setattr(db_env, "database_url", "postgresql+asyncpg://u:p@db.example.com/x")

    async def forbidden(*args):
        pytest.fail("database accessor called")

    monkeypatch.setattr(dev_seed.seed_access, "replace_mail_data", forbidden)
    with pytest.raises(SeedRefusedError):
        await dev_seed.seed()


def test_main_refusal(monkeypatch, capsys):
    monkeypatch.setattr(db_env, "database_url", "postgresql+asyncpg://u:p@db.example.com/x")
    with pytest.raises(SystemExit) as error:
        dev_seed.main()
    assert error.value.code == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert output.err == "Database host refused: db.example.com\n"

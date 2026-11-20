from datetime import datetime, timedelta, timezone

from db.models.mail_account import MailAccount
from db.models.mail_sync_state import MailSyncState

from api.mail import jobs, state


def make_account(store, name):
    a = MailAccount(provider="imap", auth_type="imap_password", email_address=f"{name}@example.test")
    store.accounts[a.id] = a
    return a


def test_color_index_cycles_after_four_accounts():
    accounts = [MailAccount(provider="imap", auth_type="imap_password", email_address=f"{i}@example.test") for i in range(5)]
    indexes = state.color_indexes(accounts)
    assert [indexes[a.id] for a in accounts] == [0, 1, 2, 3, 0]


def test_summary_counts_unread_and_maps_states(client, fake_store):
    a = make_account(fake_store, "a")
    b = make_account(fake_store, "b")
    fake_store.unread = {a.id: 2, b.id: 3}
    fake_store.states[a.id] = MailSyncState(account_id=a.id, last_error="auth_expired")
    response = client.get('/api/v1/mail/summary')
    assert response.status_code == 200
    result = response.json()
    assert result['unread_total'] == 5
    assert [r['state'] for r in result['accounts']] == ['auth_expired', 'never']
    import asyncio
    asyncio.run(jobs.enqueue_sync(b.id))
    result = client.get('/api/v1/mail/summary').json()
    assert result['accounts'][1]['state'] == 'syncing'


def test_summary_never_contains_provider_text(client, fake_store):
    a = make_account(fake_store, 'a')
    fake_store.states[a.id] = MailSyncState(account_id=a.id, last_error='private provider detail')
    response = client.get('/api/v1/mail/summary')
    assert 'private provider detail' not in response.text
    assert response.json()['accounts'][0]['error_code'] == 'provider_error'


def test_account_sync_returns_202_and_dedupes(client, fake_store):
    a = make_account(fake_store, 'a')
    for _ in range(2):
        response = client.post(f'/api/v1/mail/accounts/{a.id}/sync')
        assert response.status_code == 202
        assert response.json()['state'] == 'syncing'
    assert len(fake_store.jobs) == 1


def test_sync_all_respects_staleness(client, fake_store):
    a, b = make_account(fake_store, 'a'), make_account(fake_store, 'b')
    now = datetime.now(timezone.utc)
    for row, minutes in [(a, 5), (b, 20)]:
        fake_store.states[row.id] = MailSyncState(account_id=row.id, last_sync_at=now-timedelta(minutes=minutes))
    response = client.post('/api/v1/mail/sync', json={'only_if_older_than_minutes': 10})
    assert response.status_code == 202
    assert response.json()['queued'] == [b.id]


def test_chat_summary_uses_only_granted_active_accounts(client, fake_store, monkeypatch):
    from unittest.mock import AsyncMock
    from db.accessors import chat_settings
    from db.models.chat_settings import ChatSettings
    from api.mail import newsletters
    a, b, hidden = (make_account(fake_store, name) for name in ('a', 'b', 'hidden'))
    fake_store.unread = {a.id: 2, b.id: 3, hidden.id: 10}
    senders = AsyncMock(return_value=[])
    monkeypatch.setattr(newsletters, 'find_newsletters', senders)
    for ids, count in [([a.id, b.id], 5), ([], 0)]:
        monkeypatch.setattr(chat_settings, 'get', AsyncMock(return_value=ChatSettings(account_ids=ids, version=3)))
        response = client.get('/api/v1/mail/summary', params={'chat_scope': True})
        assert response.status_code == 200
        summary = response.json()
        assert summary['mail_scope_version'] == 3 and summary['unread_total'] == count
        assert [item['id'] for item in summary['accounts']] == ids
        senders.assert_awaited_with(account_ids=ids)
    assert client.get('/api/v1/mail/summary').json()['unread_total'] == 15

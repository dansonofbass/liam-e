from db.models.mail_account import MailAccount
from db.accessors import mail_insight, mail_message, mail_action, mail_job, mail_credential, mail_sync_state
from api.mail import providers, connectors, transport

BASE = '/api/v1/mail/accounts'


def account(store):
    row = MailAccount(provider='google', auth_type='oauth2', email_address='a@example.test')
    store.accounts[row.id] = row
    return row


def oauth(monkeypatch, email='a@example.test'):
    monkeypatch.setattr(providers, 'verify_state', lambda state: {'provider': 'google', 'redirect_uri': 'https://example.test'})
    async def exchange(*args, **kwargs):
        return {'access_token': 'invented'}
    async def fetch(*args, **kwargs):
        return email
    monkeypatch.setattr(providers, 'exchange_code', exchange)
    monkeypatch.setattr(providers, 'fetch_account_email', fetch)
    monkeypatch.setattr('api.mail.crypto.encrypt_payload', lambda payload: 'encrypted')


def test_callback_redirects_to_accounts_with_connected_id(client, fake_store, monkeypatch):
    oauth(monkeypatch)
    r = client.get(BASE + '/oauth/google/callback?code=x&state=y', follow_redirects=False)
    assert r.status_code == 303
    assert r.headers['location'] == '/accounts?connected=' + next(iter(fake_store.accounts))
    assert len(fake_store.jobs) == 1


def test_callback_error_redirects_with_code_and_no_provider_text(client, fake_store, monkeypatch):
    oauth(monkeypatch)
    async def fail(*args, **kwargs):
        raise ValueError('private@example.test')
    monkeypatch.setattr(providers, 'exchange_code', fail)
    r = client.get(BASE + '/oauth/google/callback?code=x&state=y', follow_redirects=False)
    assert r.status_code == 303
    assert r.headers['location'] == '/accounts?error=oauth_exchange_failed'
    assert 'private' not in r.headers['location']
    r = client.get(BASE + '/oauth/google/callback?error=private@example.test', follow_redirects=False)
    assert r.headers['location'] == '/accounts?error=oauth_denied'


def test_reconnect_with_other_mailbox_is_refused(client, fake_store, monkeypatch):
    row = account(fake_store)
    oauth(monkeypatch, 'other@example.test')
    monkeypatch.setattr(providers, 'verify_state', lambda state: {'provider': 'google', 'redirect_uri': 'https://example.test', 'account_id': row.id})
    r = client.get(BASE + '/oauth/google/callback?code=x&state=y', follow_redirects=False)
    assert r.headers['location'] == '/accounts?error=oauth_account_mismatch'
    assert not fake_store.credentials


def test_patch_display_name(client, fake_store):
    row = account(fake_store)
    r = client.patch(f'{BASE}/{row.id}', json={'display_name': '  Arbeit  '})
    assert r.status_code == 200 and r.json()['display_name'] == 'Arbeit'
    assert client.patch(f'{BASE}/{row.id}', json={'display_name': '  '}).status_code == 422


def test_delete_removes_local_data_only(client, fake_store, monkeypatch):
    row = account(fake_store)
    calls = []
    for module in (mail_insight, mail_message, mail_action, mail_job, mail_credential, mail_sync_state):
        async def delete(account_id, name=module.__name__):
            calls.append(name.rsplit('.', 1)[-1])
        monkeypatch.setattr(module, 'delete_for_account', delete)
    async def forbidden(*args, **kwargs):
        raise AssertionError('external call')
    monkeypatch.setattr(connectors, 'list_connectors', forbidden)
    monkeypatch.setattr(providers, 'fetch_account_email', forbidden)
    monkeypatch.setattr(transport, 'check_mail_host', forbidden)
    assert client.delete(f'{BASE}/{row.id}').status_code == 204
    assert calls == ['mail_insight', 'mail_message', 'mail_action', 'mail_job', 'mail_credential', 'mail_sync_state']


def test_options_hide_google_oauth_when_gmail_connector_exists(client, fake_store, monkeypatch):
    async def listing():
        return [{'name': 'gmail', 'id': 'example'}]
    monkeypatch.setattr(connectors, 'list_connectors', listing)
    monkeypatch.setattr(providers, 'oauth_configured', lambda provider: True)
    r = client.get(BASE + '/options')
    assert r.status_code == 200
    assert r.json()['gmail_connector'] is True and r.json()['google_oauth'] is False


def test_authorize_reconnect_signs_account_id_and_validates(client, fake_store, monkeypatch):
    row = account(fake_store)
    signed = {}
    monkeypatch.setattr(providers, 'oauth_configured', lambda provider: True)
    def sign(payload):
        signed.update(payload)
        return 'signed'
    monkeypatch.setattr(providers, 'sign_state', sign)
    monkeypatch.setattr(providers, 'authorization_url', lambda *args, **kwargs: 'https://example.test')
    r = client.get(BASE + '/oauth/google/authorize', params={'account_id': row.id})
    assert r.status_code == 200 and signed['account_id'] == row.id
    assert client.get(BASE + '/oauth/google/authorize', params={'account_id': 'missing'}).status_code == 404
    assert client.get(BASE + '/oauth/microsoft/authorize', params={'account_id': row.id}).status_code == 422


def test_callback_invalid_state_and_missing_code(client, fake_store, monkeypatch):
    monkeypatch.setattr(providers, 'verify_state', lambda state: (_ for _ in ()).throw(ValueError()))
    r = client.get(BASE + '/oauth/google/callback', follow_redirects=False)
    assert r.headers['location'] == '/accounts?error=oauth_state_invalid'
    oauth(monkeypatch)
    r = client.get(BASE + '/oauth/google/callback?state=x', follow_redirects=False)
    assert r.headers['location'] == '/accounts?error=oauth_exchange_failed'


def test_account_rows_include_summary_and_counts(client, fake_store):
    row = account(fake_store)
    fake_store.unread[row.id] = 3
    result = client.get(BASE).json()[0]
    assert result['connection'] == 'oauth'
    assert result['unread'] == 3 and result['message_count'] == 0
    assert result['state'] == 'never' and result['color_index'] == 0

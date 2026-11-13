"""In-memory accessor replacement for mail tests, scoped to each fixture invocation."""

from db.accessors import mail_account, mail_credential, mail_sync_state
from db.models.mail_account import MailAccount
from db.models.mail_sync_state import MailSyncState


class FakeStore:
    def __init__(self, monkeypatch):
        self.accounts = {}
        self.credentials = {}
        self.states = {}
        for module, names in (
            (mail_account, ("list_accounts", "get_account", "get_account_by_email", "create_account", "touch_account", "delete_account")),
            (mail_credential, ("load_credential", "store_credential")),
            (mail_sync_state, ("get_state", "save_state")),
        ):
            for name in names:
                monkeypatch.setattr(module, name, getattr(self, name))
        async def delete_credentials(account_id):
            for key in list(self.credentials):
                if key[0] == account_id:
                    del self.credentials[key]
        async def delete_state(account_id):
            self.states.pop(account_id, None)
        monkeypatch.setattr(mail_credential, "delete_for_account", delete_credentials)
        monkeypatch.setattr(mail_sync_state, "delete_for_account", delete_state)

    async def list_accounts(self, session=None):
        return list(self.accounts.values())

    async def get_account(self, account_id):
        return self.accounts.get(account_id)

    async def get_account_by_email(self, email_address):
        return next((a for a in self.accounts.values() if a.email_address == email_address), None)

    async def create_account(self, **kwargs):
        return await self.touch_account(MailAccount(**kwargs))

    async def touch_account(self, account):
        self.accounts[account.id] = account
        return account

    async def delete_account(self, account_id):
        return self.accounts.pop(account_id, None) is not None

    async def load_credential(self, account_id, kind):
        return self.credentials.get((account_id, kind))

    async def store_credential(self, *, account_id, kind, encrypted_payload):
        self.credentials[account_id, kind] = encrypted_payload

    async def get_state(self, account_id):
        return self.states.get(account_id)

    async def save_state(self, *, account_id, **kwargs):
        state = MailSyncState(account_id=account_id, **kwargs)
        self.states[account_id] = state
        return state

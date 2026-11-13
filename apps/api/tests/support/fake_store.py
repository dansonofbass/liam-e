"""In-memory accessor replacement for mail tests, scoped to each fixture invocation."""

import json
from db.accessors import mail_account, mail_action, mail_credential, mail_sync_state, mail_job, mail_message
from db.models.mail_action import MailAction
from db.models.mail_job import MailJob
from db.models.mail_account import MailAccount
from db.models.mail_sync_state import MailSyncState


class FakeStore:
    def __init__(self, monkeypatch):
        self.accounts = {}
        self.credentials = {}
        self.states = {}
        self.jobs = {}
        self.unread = {}
        self.messages = {}
        self.actions = {}
        for name in ("record", "get_many", "mark_undone", "release", "latest_open", "delete_for_account"):
            monkeypatch.setattr(mail_action, name, getattr(self, "action_" + name))
        monkeypatch.setattr(mail_message, "get_message", self.get_message)
        monkeypatch.setattr(mail_message, "set_state", self.set_message_state)
        for name in ("enqueue", "claim_next", "finish", "fail", "latest_for_account", "delete_for_account"):
            monkeypatch.setattr(mail_job, name, getattr(self, "job_" + name))
        monkeypatch.setattr(mail_message, "count_unread", self.count_unread)
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

    async def get_message(self, message_id):
        row = self.messages.get(message_id)
        return row.model_copy() if row else None

    async def set_message_state(self, message_id, **kwargs):
        row = self.messages.get(message_id)
        if row:
            for key, value in kwargs.items():
                if value is not None:
                    setattr(row, key, value)
            return row.model_copy()
        return None

    async def action_record(self, **kwargs):
        row = MailAction(**kwargs)
        self.actions[row.id] = row
        return row

    async def action_get_many(self, ids):
        return [row for key, row in self.actions.items() if key in ids]

    async def action_mark_undone(self, action_id, at):
        row = self.actions.get(action_id)
        if row is None or row.undone_at is not None:
            return False
        row.undone_at = at
        return True

    async def action_release(self, action_id):
        if action_id in self.actions:
            self.actions[action_id].undone_at = None

    async def action_latest_open(self, message_id):
        return max((row for row in self.actions.values() if row.message_id == message_id and row.undone_at is None), key=lambda row: (row.created_at, row.id), default=None)

    async def action_delete_for_account(self, account_id):
        self.actions = {key: row for key, row in self.actions.items() if row.account_id != account_id}

    async def count_unread(self, *, folder="INBOX"):
        return self.unread

    async def job_enqueue(self, kind, payload, *, dedupe_key, run_after=None):
        if any(j.dedupe_key == dedupe_key and j.status in ("queued", "running") for j in self.jobs.values()):
            return None
        job = MailJob(kind=kind, payload_json=json.dumps(payload), dedupe_key=dedupe_key)
        if run_after is not None:
            job.run_after = run_after
        self.jobs[job.id] = job
        return job

    enqueue = job_enqueue

    async def job_claim_next(self, now, *, stale_after):
        eligible = [j for j in self.jobs.values() if (j.status == "queued" and j.run_after <= now) or (j.status == "running" and j.locked_at and j.locked_at < now - stale_after)]
        if not eligible:
            return None
        job = min(eligible, key=lambda j: (j.run_after, j.id))
        job.status, job.locked_at, job.attempts = "running", now, job.attempts + 1
        return job

    async def job_finish(self, job_id):
        self.jobs[job_id].status = "done"
        self.jobs[job_id].locked_at = None

    async def job_fail(self, job_id, error_code, *, retry_at):
        job = self.jobs[job_id]
        job.status = "queued" if retry_at else "failed"
        job.last_error = error_code
        job.locked_at = None
        if retry_at:
            job.run_after = retry_at

    async def job_latest_for_account(self, account_id, *, kind=None, open_only=False):
        rows = [j for j in self.jobs.values() if json.loads(j.payload_json).get("account_id") == account_id and (kind is None or j.kind == kind) and (not open_only or j.status in ("queued", "running"))]
        return max(rows, key=lambda j: (j.created_at, j.id), default=None)

    async def job_delete_for_account(self, account_id):
        for job in list(self.jobs.values()):
            if json.loads(job.payload_json).get("account_id") == account_id:
                del self.jobs[job.id]

    async def list_accounts(self, session=None):
        return list(self.accounts.values())

    async def get_account(self, account_id):
        return self.accounts.get(account_id)

    async def get_account_by_email(self, email_address):
        return next((a for a in sorted(self.accounts.values(), key=lambda a: (a.created_at, a.id)) if a.email_address.lower() == email_address.lower()), None)

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

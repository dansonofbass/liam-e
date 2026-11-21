"""Run the previous source tree against an upgraded or downgraded scratch database."""

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import AsyncMock

from api.mail import service, sync, sync_imap, transport
from api.routers.api.v1.mail import accounts, messages
from bulk_mailboxes import Mailboxes, YahooConnection
from db import engine
from db.accessors import mail_message, mail_sync_state
from db.models import mail_message as message_model
from env.mail import env as mail_env
from test_mail_trash_sync_pg import MAIL, client


def run_previous(url, **scenario):
    if previous := os.getenv("MAIL_TEST_PREVIOUS_ROOT"):
        root = Path(previous).resolve()
        source = [str(root / path) for path in ("apps/api/src", "packages/py/db/src", "packages/py/env/src", "packages/py/utils/src")]
        subprocess.run([sys.executable, str(Path(__file__).resolve())], cwd=root,
                       env=os.environ | {"PYTHONPATH": os.pathsep.join(source), "DATABASE_URL": url}, check=True,
                       input=json.dumps(scenario), text=True, timeout=30)


async def poll(*, account_id=None, ids=None, token=None, archived=None, archive_control=None, rolling_id=None):
    for module in (sync, sync_imap, messages, mail_message, message_model):
        assert Path(module.__file__).is_relative_to(Path.cwd()), module.__file__
    assert "imap_uidvalidity" not in message_model.MailMessage.model_fields
    provider = Mailboxes(["Yahoo"], False, "move")
    twin = "11" if rolling_id else "twin"
    provider.yahoo_folders["ARCHIVE"] = {"91": twin}
    provider.labels["Yahoo"][twin] = {"ARCHIVE"}
    flag_ranges, body_reads = [], []
    archive_calls = []

    class AfterFlagClear(YahooConnection):
        def list(self, *args):
            status, folders = super().list(*args)
            return status, [*folders, b'(\\Archive) "/" "Archive"']

        def uid(self, cmd, *args):
            if self.folder == "ARCHIVE":
                archive_calls.append(cmd)
            status, data = super().uid(cmd, *args)
            if cmd.upper() == "FETCH":
                if args[1] == "(FLAGS)":
                    flag_ranges.append(args[0])
                    # Another client cleared Deleted and marked the same delivery read after the rollback.
                    data = [row.replace(b"FLAGS ()", b"FLAGS (\\Seen)") if b"UID 11 " in row else row for row in data]
                else:
                    body_reads.append(args[0])
            return status, data

    transport.open_imap = lambda *_: AfterFlagClear(provider)
    transport.check_mail_host = AsyncMock()
    service.load_credentials = AsyncMock(return_value={"imap_host": "imap.example.test"})
    service.imap_password = AsyncMock(return_value="test")
    mail_env.mail_sync_page_size = 1
    try:
        async with client() as browser:
            if rolling_id:
                original = await browser.get(f"{MAIL}/messages/{rolling_id}/original")
                result = await browser.post(MAIL + "/messages/actions", json={"message_ids": [rolling_id], "kind": "trash"})
                row, = result.json()["results"]
                assert (original.status_code, row["status"], row["action_id"], archive_calls) == (409, "unsupported", None, [])
                assert provider.yahoo_folders["ARCHIVE"] == {"91": twin} and not provider.yahoo_folders["TRASH"]
                return
            for _ in range(2):
                assert (await sync.sync_account(account_id)).status == "ok"
                listing = await browser.get(MAIL + "/messages")
                assert listing.status_code == 200
                items = {row["id"]: row for row in listing.json()["items"]}
                assert set(items) == set(ids.values()) and items[ids["11"]]["is_read"]
            assert (await mail_sync_state.get_state(account_id)).cursor == "7:14"
            assert flag_ranges == ["11:14", "11:14"] and not body_reads
            for outcome in ("restored", "skipped"):
                result = await browser.post(MAIL + "/actions/undo", json={"action_ids": [token]})
                assert result.status_code == 200 and result.json()[outcome] == [token]
            for message_id, body in archived.items():
                uri = f"{MAIL}/messages/{message_id}"
                detail = (await browser.get(uri)).json()
                original = await browser.get(uri + "/original")
                result = await browser.post(MAIL + "/messages/actions", json={"message_ids": [message_id], "kind": "trash"})
                row, = result.json()["results"]
                assert (detail["local_reference_only"], detail["can_show_original"], detail["body_text"]) == (True, False, body)
                assert original.status_code == 404 and row["status"] == "not_found" and row["action_id"] is None
            assert archive_calls == []
            assert provider.yahoo_folders["ARCHIVE"] == {"91": "twin"} and not provider.yahoo_folders["TRASH"]
            original = await browser.get(f"{MAIL}/messages/{archive_control}/original")
            assert original.status_code == 200 and "Synthetic message twin." in original.json()["source"]
            await accounts.delete_account(account_id)
            for local_id in [*archived, archive_control]:
                assert (await browser.get(f"{MAIL}/messages/{local_id}/insight")).status_code == 404
    finally:
        await engine.dispose_engine()


if __name__ == "__main__":
    asyncio.run(poll(**json.load(sys.stdin)))

"""Normal poll and undo in the previous worker process, on the actually downgraded test DB."""

import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock

from api.mail import service, sync, sync_imap, transport
from api.routers.api.v1.mail import messages
from bulk_mailboxes import Mailboxes, YahooConnection
from db import engine
from db.accessors import mail_message, mail_sync_state
from db.models import mail_message as message_model
from env.mail import env as mail_env
from test_mail_trash_sync_pg import MAIL, client


async def poll(account_id, ids, token):
    for module in (sync, sync_imap, messages, mail_message, message_model):
        assert Path(module.__file__).is_relative_to(Path.cwd()), module.__file__
    assert "imap_uidvalidity" not in message_model.MailMessage.model_fields
    provider = Mailboxes(["Yahoo"], False, "move")
    flag_ranges, body_reads = [], []

    class AfterFlagClear(YahooConnection):
        def uid(self, cmd, *args):
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
    finally:
        await engine.dispose_engine()


if __name__ == "__main__":
    asyncio.run(poll(**json.load(sys.stdin)))

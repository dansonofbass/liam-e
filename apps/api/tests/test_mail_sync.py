"""Incremental inbox sync contracts; all providers are faked."""

from types import SimpleNamespace

import httpx
import pytest

from api.mail import sync, sync_connector, sync_gmail, sync_graph, sync_imap, sync_types
from support.fake_imap import FakeIMAP


def account(provider="imap", auth_type="imap_password"):
    return SimpleNamespace(id="a", provider=provider, auth_type=auth_type, email_address="a@example.org")


async def imap_run(monkeypatch, server, cursor="", known=None, limit=3):
    async def credentials(_):
        return {"imap_host": "example.org", "password": "secret"}
    async def password(_):
        return "secret"
    async def check(_):
        pass
    async def uids(*_):
        return known or {}
    monkeypatch.setattr(sync_imap.service, "load_credentials", credentials)
    monkeypatch.setattr(sync_imap.service, "imap_password", password)
    monkeypatch.setattr(sync_imap.transport, "check_mail_host", check)
    monkeypatch.setattr(sync_imap.transport, "open_imap", lambda *_: server)
    monkeypatch.setattr(sync_imap.message_access, "known_uids", uids)
    return await sync_imap.fetch_changes(account(), cursor=cursor, folders=["INBOX"], limit=limit, max_body_chars=100)


@pytest.mark.anyio
async def test_imap_first_sync_takes_newest_limit(monkeypatch):
    changes = await imap_run(monkeypatch, FakeIMAP(range(1, 7)))
    assert [m["provider_uid"] for m in changes.upserts] == ["4", "5", "6"]
    assert changes.full_rebuild


@pytest.mark.anyio
async def test_imap_incremental_fetches_only_new_uids(monkeypatch):
    changes = await imap_run(monkeypatch, FakeIMAP(range(118, 124)), "7:120")
    assert [m["provider_uid"] for m in changes.upserts] == ["121", "122", "123"]


@pytest.mark.anyio
async def test_imap_incremental_cursor_stops_at_limit(monkeypatch):
    changes = await imap_run(monkeypatch, FakeIMAP(range(118, 124)), "7:120", limit=2)
    assert [m["provider_uid"] for m in changes.upserts] == ["121", "122"]
    assert changes.cursor == "7:122"


@pytest.mark.anyio
async def test_imap_uidvalidity_change_rebuilds(monkeypatch):
    assert (await imap_run(monkeypatch, FakeIMAP([1], validity=8), "7:120")).full_rebuild


@pytest.mark.anyio
async def test_imap_flags_update_read_state_and_detect_moved(monkeypatch):
    server = FakeIMAP([118, 120], flags={118: r"\Seen \Flagged"})
    changes = await imap_run(monkeypatch, server, "7:120", {"118": "a", "119": "b", "120": "c"})
    assert changes.read_updates["118"] is True
    assert changes.flag_updates["118"] is True
    assert changes.moved_out == ["119"]


@pytest.mark.anyio
async def test_imap_fetch_never_sets_seen(monkeypatch):
    server = FakeIMAP([1, 2], flags={2: r"\Seen \Flagged"})
    changes = await imap_run(monkeypatch, server)
    fetches = [str(c) for c in server.commands if c[0] == "fetch"]
    assert all("BODY.PEEK[]" in c and "RFC822)" not in c for c in fetches)
    assert changes.upserts[-1]["is_read"] and changes.upserts[-1]["is_flagged"]


def mock_client(monkeypatch, module, handler):
    original = httpx.AsyncClient
    monkeypatch.setattr(module.httpx, "AsyncClient", lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs))


async def token_setup(monkeypatch, module):
    async def credentials(_): return {}
    async def token(*_): return "test"
    monkeypatch.setattr(module.service, "load_credentials", credentials)
    monkeypatch.setattr(module.service, "valid_access_token", token)


@pytest.mark.anyio
async def test_gmail_history_404_triggers_full_rebuild(monkeypatch):
    await token_setup(monkeypatch, sync_gmail)
    def handler(request):
        if request.url.path.endswith("/history"):
            return httpx.Response(404)
        if request.url.path.endswith("/messages"):
            assert request.url.params["q"] == "in:inbox"
            return httpx.Response(200, json={"messages": []})
        return httpx.Response(200, json={"historyId": "42"})
    mock_client(monkeypatch, sync_gmail, handler)
    changes = await sync_gmail.fetch_changes(account("google", "oauth2"), cursor="1", folders=["INBOX"], limit=10, max_body_chars=100)
    assert changes.full_rebuild


@pytest.mark.anyio
async def test_graph_delta_removed_marks_moved_out(monkeypatch):
    await token_setup(monkeypatch, sync_graph)
    mock_client(monkeypatch, sync_graph, lambda request: httpx.Response(200, json={"value": [{"id": "old", "@removed": {"reason": "deleted"}}], "@odata.deltaLink": "https://graph.microsoft.com/v1.0/next"}))
    changes = await sync_graph.fetch_changes(account("microsoft", "oauth2"), cursor="https://graph.microsoft.com/v1.0/delta", folders=["INBOX"], limit=10, max_body_chars=100)
    assert changes.moved_out == ["old"]


@pytest.mark.anyio
async def test_connector_uses_after_query_and_reconciles_unread(monkeypatch):
    queries = []
    async def call(provider, tool, args):
        queries.append(args["query"])
        return {"threads": [{"id": "t"}]} if "after:" not in args["query"] else {"threads": []}
    async def known(*_): return {"m": "local"}
    async def get(_): return SimpleNamespace(thread_id="t", internal_date=None)
    monkeypatch.setattr(sync_connector.connectors, "call_read_tool_json", call)
    monkeypatch.setattr(sync_connector.message_access, "known_uids", known)
    monkeypatch.setattr(sync_connector.message_access, "get_message", get)
    changes = await sync_connector.fetch_changes(account("gmail", "connector"), cursor="123", folders=["INBOX"], limit=10, max_body_chars=100)
    assert "in:inbox after:122" in queries
    assert changes.read_updates["m"] is False


@pytest.mark.anyio
async def test_sync_account_applies_changes_and_reports_new_ids(monkeypatch):
    stored = {}
    async def get_account(_): return account()
    async def get_state(_): return None
    async def save_state(**kwargs): return SimpleNamespace(**kwargs)
    async def known(*_): return {"old": "local-old"}
    async def fetch(*_, **__):
        return sync_types.SyncChanges(upserts=[{"folder": "INBOX", "provider_uid": "old"}, {"folder": "INBOX", "provider_uid": "new"}], read_updates={"old": True}, flag_updates={"old": True}, moved_out=[], cursor="7:2", full_rebuild=False)
    async def upsert(**kwargs): return SimpleNamespace(id="local-new")
    async def set_state(id, **kwargs): stored[id] = kwargs
    monkeypatch.setattr(sync.account_access, "get_account", get_account)
    monkeypatch.setattr(sync.sync_state_access, "get_state", get_state)
    monkeypatch.setattr(sync.sync_state_access, "save_state", save_state)
    monkeypatch.setattr(sync.message_access, "known_uids", known)
    monkeypatch.setattr(sync.message_access, "upsert_message", upsert)
    monkeypatch.setattr(sync.message_access, "set_state", set_state)
    monkeypatch.setattr(sync_imap, "fetch_changes", fetch)
    result = await sync.sync_account("a")
    assert result.new_message_ids == ["local-new"]
    assert stored["local-old"] == {"is_read": True, "is_flagged": True}


@pytest.mark.anyio
async def test_connector_paginates_past_empty_threads(monkeypatch):
    calls = []
    async def call(provider, tool, args):
        calls.append((tool, args.copy()))
        if tool == "get_thread":
            return {"id": args["threadId"], "messages": [] if args["threadId"] == "empty" else [{"id": "m", "date": "2026-11-13T10:00:00+00:00"}]}
        if not args.get("pageToken"):
            return {"threads": [{"id": "empty"}], "nextPageToken": "next"}
        return {"threads": [{"id": "full"}]}
    monkeypatch.setattr(sync_connector.connectors, "call_read_tool_json", call)
    async def known(*_): return {}
    monkeypatch.setattr(sync_connector.message_access, "known_uids", known)
    result = await sync_connector.fetch_changes(account("gmail", "connector"), cursor="", folders=["INBOX"], limit=1, max_body_chars=100)
    assert [m["provider_uid"] for m in result.upserts] == ["m"]
    assert any(args.get("pageToken") == "next" for tool, args in calls if tool == "search_threads")


@pytest.mark.anyio
async def test_gmail_follows_all_history_pages(monkeypatch):
    await token_setup(monkeypatch, sync_gmail)
    requests = []
    def gmail(request):
        requests.append(request)
        if request.url.path.endswith("/history"):
            if not request.url.params.get("pageToken"):
                return httpx.Response(200, json={"historyId": "8", "nextPageToken": "p"})
            return httpx.Response(200, json={"historyId": "9", "history": [{"messagesDeleted": [{"message": {"id": "gone"}}]}]})
        return httpx.Response(404)
    mock_client(monkeypatch, sync_gmail, gmail)
    result = await sync_gmail.fetch_changes(account("google", "oauth2"), cursor="7", folders=["INBOX"], limit=2, max_body_chars=100)
    assert result.cursor == "9" and result.moved_out == ["gone"]
    assert any(r.url.params.get("pageToken") == "p" for r in requests)


@pytest.mark.anyio
async def test_graph_follows_next_link_until_delta(monkeypatch):
    await token_setup(monkeypatch, sync_graph)
    requests = []
    def graph(request):
        requests.append(str(request.url))
        if len(requests) == 1:
            return httpx.Response(200, json={"value": [], "@odata.nextLink": "https://graph.microsoft.com/v1.0/page2"})
        return httpx.Response(200, json={"value": [{"id": "gone", "@removed": {}}], "@odata.deltaLink": "https://graph.microsoft.com/v1.0/delta2"})
    mock_client(monkeypatch, sync_graph, graph)
    result = await sync_graph.fetch_changes(account("microsoft", "oauth2"), cursor="https://graph.microsoft.com/v1.0/delta", folders=["INBOX"], limit=1, max_body_chars=100)
    assert len(requests) == 2 and result.cursor.endswith("delta2")
    assert result.moved_out == ["gone"]


@pytest.mark.anyio
async def test_connector_backlog_and_boundary_progress(monkeypatch):
    from datetime import UTC, datetime
    import re
    known = {"old": "old"}
    messages = {str(i): i for i in range(101, 106)}
    messages["old"] = 100
    async def known_uids(*_): return dict(known)
    async def get(_): return None
    async def call(provider, tool, args):
        if tool == "get_thread":
            uid = args["threadId"]
            date = datetime.fromtimestamp(messages[uid], UTC).isoformat()
            return {"id": uid, "messages": [{"id": uid, "date": date}]}
        query = args["query"]
        if "newer_than" in query:
            return {"threads": []}
        after = re.search(r"after:(-?\d+)", query)
        before = re.search(r"before:(-?\d+)", query)
        ids = [uid for uid, ts in sorted(messages.items(), key=lambda item: -item[1]) if (not after or ts > int(after.group(1))) and (not before or ts < int(before.group(1)))]
        return {"threads": [{"id": uid} for uid in ids]}
    monkeypatch.setattr(sync_connector.message_access, "known_uids", known_uids)
    monkeypatch.setattr(sync_connector.message_access, "get_message", get)
    monkeypatch.setattr(sync_connector.connectors, "call_read_tool_json", call)
    cursor = "100"
    for _ in range(3):
        changes = await sync_connector.fetch_changes(account("gmail", "connector"), cursor=cursor, folders=["INBOX"], limit=2, max_body_chars=100)
        assert len(changes.upserts) <= 2
        known.update({m["provider_uid"]: m["provider_uid"] for m in changes.upserts})
        cursor = changes.cursor
    assert set(known) == set(messages)
    assert cursor == "105"
    known.clear()
    known.update({"105": "105", "104": "104"})
    changes = await sync_connector.fetch_changes(account("gmail", "connector"), cursor="105:100:104", folders=["INBOX"], limit=2, max_body_chars=100)
    assert {m["provider_uid"] for m in changes.upserts} == {"102", "103"}
    assert changes.cursor == "105:100:102"
    messages["same-second"] = 105
    known.update({"102": "102", "103": "103"})
    changes = await sync_connector.fetch_changes(account("gmail", "connector"), cursor="105", folders=["INBOX"], limit=2, max_body_chars=100)
    assert [m["provider_uid"] for m in changes.upserts] == ["same-second"]


@pytest.mark.anyio
async def test_connector_invalid_cursor_rebuilds(monkeypatch):
    async def known(*_): return {}
    async def call(*_): return {"threads": []}
    monkeypatch.setattr(sync_connector.message_access, "known_uids", known)
    monkeypatch.setattr(sync_connector.connectors, "call_read_tool_json", call)
    result = await sync_connector.fetch_changes(account("gmail", "connector"), cursor="not-a-cursor", folders=["INBOX"], limit=2, max_body_chars=100)
    assert result.full_rebuild


@pytest.mark.anyio
async def test_gmail_stops_at_history_page_boundary(monkeypatch):
    await token_setup(monkeypatch, sync_gmail)
    def handler(request):
        if request.url.path.endswith("/history"):
            assert request.url.params["maxResults"] == "1"
            return httpx.Response(200, json={"historyId": "99", "history": [{"id": "11", "messagesDeleted": [{"message": {"id": "gone"}}]}], "nextPageToken": "next"})
        return httpx.Response(404)
    mock_client(monkeypatch, sync_gmail, handler)
    result = await sync_gmail.fetch_changes(account("google", "oauth2"), cursor="10", folders=["INBOX"], limit=1, max_body_chars=100)
    assert result.cursor == "11" and result.moved_out == ["gone"]


@pytest.mark.anyio
async def test_graph_stops_at_page_boundary(monkeypatch):
    await token_setup(monkeypatch, sync_graph)
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={"value": [{"id": "a", "@removed": {}}, {"id": "b", "@removed": {}}], "@odata.nextLink": "https://graph.microsoft.com/v1.0/next"})
    mock_client(monkeypatch, sync_graph, handler)
    result = await sync_graph.fetch_changes(account("microsoft", "oauth2"), cursor="https://graph.microsoft.com/v1.0/delta", folders=["INBOX"], limit=1, max_body_chars=100)
    assert result.cursor.endswith("/next") and result.moved_out == ["a", "b"]
    assert len(calls) == 1 and calls[0].headers["Prefer"] == "odata.maxpagesize=1"


@pytest.mark.anyio
async def test_graph_rejects_network_path_delta_link(monkeypatch):
    await token_setup(monkeypatch, sync_graph)
    requests = []
    def graph(request):
        requests.append(request)
        return httpx.Response(200, json={"value": [], "@odata.nextLink": "//evil.example/path"})
    mock_client(monkeypatch, sync_graph, graph)
    with pytest.raises(ValueError):
        await sync_graph.fetch_changes(account("microsoft", "oauth2"), cursor="", folders=["INBOX"], limit=1, max_body_chars=100)
    assert len(requests) == 1


@pytest.mark.anyio
async def test_sync_error_stores_code_not_provider_text(monkeypatch):
    states = []
    async def get_account(_): return account()
    async def get_state(_): return None
    async def save_state(**kwargs): states.append(kwargs); return SimpleNamespace(**kwargs)
    async def fetch(*_, **__): raise ValueError("token=abc failed")
    monkeypatch.setattr(sync.account_access, "get_account", get_account)
    monkeypatch.setattr(sync.sync_state_access, "get_state", get_state)
    monkeypatch.setattr(sync.sync_state_access, "save_state", save_state)
    monkeypatch.setattr(sync_imap, "fetch_changes", fetch)
    result = await sync.sync_account("a")
    assert result.error_code == "provider_error"
    assert states[-1]["last_error"] == "provider_error"

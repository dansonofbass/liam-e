import json
from pathlib import Path

from api.mail import headers, sync_connector, sync_gmail, sync_graph, sync_imap


def test_sender_address_decodes_and_lowercases():
    value = '=?utf-8?q?M=C3=BCller?= <Max.Mueller@Example.org>'
    assert headers.sender_address(value) == 'max.mueller@example.org'
    assert headers.sender_name(value) == 'Müller'
    assert headers.sender_name('sender@example.org') == 'sender'
    assert headers.parse_list_unsubscribe('<https://example.org/u>, <mailto:u@example.org>') == ['https://example.org/u', 'mailto:u@example.org']


def test_parse_rfc822_reads_unsubscribe_headers():
    parsed = sync_imap.parse_rfc822(RAW, max_body_chars=100)
    assert parsed['list_unsubscribe'] == '<https://news.example/u?id=1>, <mailto:abmelden@news.example>'
    assert parsed['list_unsubscribe_post'] == 'List-Unsubscribe=One-Click'


def test_parse_rfc822_splits_to_and_cc():
    parsed = sync_imap.parse_rfc822(RAW, max_body_chars=100)
    assert json.loads(parsed['recipients_json']) == ['a@example.org']
    assert json.loads(parsed['cc_json']) == ['b@example.org']


def test_parse_rfc822_reads_message_id_and_references():
    parsed = sync_imap.parse_rfc822(RAW, max_body_chars=100)
    assert parsed['rfc_message_id'] == '<id@example.org>'
    assert parsed['references'] == '<parent@example.org>'


def test_parse_rfc822_attachment_metadata():
    parsed = sync_imap.parse_rfc822(RAW, max_body_chars=100)
    assert json.loads(parsed['attachments_json']) == [{'name': 'Abrechnung_2025.pdf', 'size': 217088, 'content_type': 'application/pdf'}]


def test_gmail_parse_flags_and_labels():
    parsed = sync_gmail.parse_message(fixture('gmail_message.json'), max_body_chars=100)
    assert not parsed['is_read'] and parsed['is_flagged']
    assert json.loads(parsed['labels_json']) == ['UNREAD', 'STARRED']


def test_graph_parse_headers_and_flag():
    parsed = sync_graph.parse_message(fixture('graph_message.json'), folder='INBOX', max_body_chars=100)
    assert parsed['rfc_message_id'] == '<id>' and parsed['is_flagged']
    assert parsed['list_unsubscribe'] == '<https://example.org>'


def test_connector_parse_labels():
    parsed = sync_connector.parse_message(fixture('connector_thread.json')['messages'][0], thread_id='1', folder='INBOX', max_body_chars=100)
    assert not parsed['is_read'] and not parsed['is_flagged']
    assert json.loads(parsed['labels_json']) == ['CATEGORY_PROMOTIONS', 'UNREAD', 'INBOX']
    assert parsed['rfc_message_id'] == ''
    assert parsed['references'] == parsed['list_unsubscribe'] == parsed['list_unsubscribe_post'] == ''
    assert parsed['sender_address'] == 'news@gartenmarkt.example'
    assert json.loads(parsed['cc_json']) == json.loads(parsed['attachments_json']) == []


FIXTURES = Path(__file__).parent / 'fixtures'
RAW = (FIXTURES / 'newsletter.eml').read_bytes()


def fixture(name):
    return json.loads((FIXTURES / name).read_text())


def test_sender_address_unknown_charset_does_not_raise():
    value = "=?x-unknown?q?abc?= <a@b.org>"
    assert headers.sender_address(value) == "a@b.org"
    assert headers.sender_name(value)


def test_sender_address_ignores_encoded_word_as_address():
    assert headers.sender_address("=?utf-8?q?boss@corp.example?= <evil@attacker.example>") == "evil@attacker.example"
    assert headers.sender_address("=?utf-8?q?boss@corp.example?=") == ""


def test_sender_address_unquoted_comma_falls_back_to_angle_address():
    assert headers.sender_address("Doe, John <john@example.org>") == "john@example.org"


def test_parse_rfc822_survives_unknown_charset():
    raw = b"From: =?x-unknown?q?abc?= <a@b.org>\r\nSubject: =?x-unknown?q?xyz?=\r\n\r\nBody"
    assert sync_imap.parse_rfc822(raw, max_body_chars=100)["sender_address"] == "a@b.org"


def test_parse_rfc822_display_name_with_encoded_comma():
    raw = b"From: =?utf-8?q?M=C3=BCller=2C_Max?= <max@example.org>\r\n\r\nBody"
    assert sync_imap.parse_rfc822(raw, max_body_chars=100)["sender_address"] == "max@example.org"


def test_graph_fetch_attachments_follows_next_link():
    import asyncio
    import httpx

    def handler(request):
        if request.url.path == "/next":
            return httpx.Response(200, json={"value": [{"name": "second"}]})
        assert request.url.params["$select"] == "name,size,contentType"
        return httpx.Response(200, json={"value": [{"name": "first"}], "@odata.nextLink": "https://graph.example/next"})

    async def run():
        async with httpx.AsyncClient(base_url="https://graph.example", transport=httpx.MockTransport(handler)) as client:
            return await sync_graph.fetch_attachments(client, "id", {})

    assert asyncio.run(run()) == [{"name": "first"}, {"name": "second"}]


def test_graph_fetch_attachments_error_returns_none():
    import asyncio
    import httpx

    async def run():
        async with httpx.AsyncClient(base_url="https://graph.example", transport=httpx.MockTransport(lambda request: httpx.Response(429))) as client:
            return await sync_graph.fetch_attachments(client, "id", {})

    assert asyncio.run(run()) is None


def test_graph_parse_keeps_has_attachments_without_metadata():
    parsed = sync_graph.parse_message({"id": "id", "hasAttachments": True}, folder="INBOX", max_body_chars=100)
    assert parsed["has_attachments"] is True
    assert parsed["attachments_json"] == "[]"


def test_parse_rfc822_recipients_with_encoded_commas():
    raw = (b"From: =?utf-8?q?M=C3=BCller=2C_Max?= <max@example.org>\r\n"
           b"To: =?utf-8?q?M=C3=BCller=2C_Max?= <to@example.org>\r\n"
           b"Cc: =?utf-8?q?M=C3=BCller=2C_Max?= <cc@example.org>\r\n\r\n")
    parsed = sync_imap.parse_rfc822(raw, max_body_chars=100)
    assert json.loads(parsed["recipients_json"]) == ["to@example.org"]
    assert json.loads(parsed["cc_json"]) == ["cc@example.org"]


def test_graph_fetch_attachments_limits_pages():
    import asyncio
    import httpx

    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={"value": [{"name": str(len(calls))}], "@odata.nextLink": "https://graph.example/next"})

    async def run():
        async with httpx.AsyncClient(base_url="https://graph.example", transport=httpx.MockTransport(handler)) as client:
            return await sync_graph.fetch_attachments(client, "id", {})

    assert len(asyncio.run(run())) == 5
    assert len(calls) == 5

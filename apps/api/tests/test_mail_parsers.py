import base64
import json
import time
from email.message import EmailMessage
from pathlib import Path

import pytest

from api.mail import headers, sync_connector, sync_gmail, sync_graph, sync_imap, sync_types


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
        return httpx.Response(200, json={"value": [{"name": "first"}], "@odata.nextLink": "https://graph.microsoft.com/next"})

    async def run():
        async with httpx.AsyncClient(base_url="https://graph.microsoft.com", transport=httpx.MockTransport(handler)) as client:
            return await sync_graph.fetch_attachments(client, "id", {})

    assert asyncio.run(run()) == [{"name": "first"}, {"name": "second"}]


def test_graph_fetch_attachments_error_returns_none():
    import asyncio
    import httpx

    async def run():
        async with httpx.AsyncClient(base_url="https://graph.microsoft.com", transport=httpx.MockTransport(lambda request: httpx.Response(429))) as client:
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
        return httpx.Response(200, json={"value": [{"name": str(len(calls))}], "@odata.nextLink": "https://graph.microsoft.com/next"})

    async def run():
        async with httpx.AsyncClient(base_url="https://graph.microsoft.com", transport=httpx.MockTransport(handler)) as client:
            return await sync_graph.fetch_attachments(client, "id", {})

    assert len(asyncio.run(run())) == 5
    assert len(calls) == 5


def test_sender_address_ignores_angle_address_inside_encoded_word():
    assert headers.sender_address("Doe, John <real@sender.example> =?utf-8?q?_<victim@corp.example>?=") == "real@sender.example"
    assert headers.sender_address("real@sender.example =?utf-8?q?_<victim@corp.example>?=") == "real@sender.example"


def test_sender_address_ignores_angle_address_inside_comment():
    assert headers.sender_address("(Attacker <victim@corp.example>)") == ""
    assert headers.sender_address("x (Attacker <victim@corp.example>)") == ""


def test_sender_address_domain_bearing_invalid_mailbox_is_ambiguous():
    assert headers.sender_address("\"evil x\"@attacker.example, Bank <service@bank.example>") == ""


@pytest.mark.parametrize(("value", "expected"), [
    ("=?utf-8?q?M=C3=BCller?= <Max.Mueller@Example.org>", "max.mueller@example.org"),
    ("=?x-unknown?q?abc?= <a@b.org>", "a@b.org"),
    ("=?utf-8?q?boss@corp.example?= <evil@attacker.example>", "evil@attacker.example"),
    ("=?utf-8?q?boss@corp.example?=", ""),
    ("Doe, John <john@example.org>", "john@example.org"),
    ("\"Doe, John\" <john@example.org>", "john@example.org"),
    ("=?utf-8?q?M=C3=BCller=2C_Max?= <max@example.org>", "max@example.org"),
    ("Doe, John <real@sender.example> =?utf-8?q?_<victim@corp.example>?=", "real@sender.example"),
    ("real@sender.example =?utf-8?q?_<victim@corp.example>?=", "real@sender.example"),
    ("=?utf-8?q?_<victim@corp.example>?= <real@sender.example>", "real@sender.example"),
    ("(Attacker <victim@corp.example>)", ""),
    ("x (Attacker <victim@corp.example>)", ""),
    ("a, b \"q <victim@corp.example>\"", ""),
    ("\"x <victim@corp.example>\"", ""),
    ("a@evil.example, Bank <service@bank.example>", ""),
    ("\"evil x\"@attacker.example, Bank <service@bank.example>", ""),
    ("plain@Example.ORG", "plain@example.org"),
    ("<A@B.org>", "a@b.org"),
    ("", ""),
    ("Group: a@b.org, c@d.org;", ""),
])
def test_sender_paths_agree(value, expected):
    raw = b"From: " + value.encode() + b"\r\nSubject: s\r\n\r\nx\r\n"
    assert headers.sender_address(value) == sync_imap.parse_rfc822(raw, max_body_chars=100)["sender_address"] == expected


def test_sender_address_ignores_angle_address_inside_quotes():
    assert headers.sender_address('a, b "q <victim@corp.example>"') == ""
    assert headers.sender_address('"x <victim@corp.example>"') == ""


def test_parse_rfc822_unquoted_comma_display_name():
    raw = b"From: Doe, John <john@example.org>\r\n\r\n"
    assert sync_imap.parse_rfc822(raw, max_body_chars=100)["sender_address"] == "john@example.org"


def test_sender_address_several_mailboxes_is_empty_on_both_paths():
    value = "a@evil.example, Bank <service@bank.example>"
    assert headers.sender_address(value) == ""
    assert sync_imap.parse_rfc822(f"From: {value}\r\n\r\n".encode(), max_body_chars=100)["sender_address"] == ""


def test_graph_fetch_attachments_refuses_foreign_next_link():
    assert _graph_next_link("https://evil.example/collect") == (None, 1)


def test_graph_fetch_attachments_refuses_other_port():
    assert _graph_next_link("https://graph.microsoft.com:8443/v1.0/me/messages/1/attachments?$skip=1") == (None, 1)
    assert _graph_next_link("https://graph.microsoft.com:0/next") == (None, 1)


def test_graph_fetch_attachments_refuses_plain_http_next_link():
    assert _graph_next_link("http://graph.microsoft.com/next") == (None, 1)


def test_graph_fetch_attachments_refuses_userinfo_and_invalid_url():
    assert _graph_next_link("https://user@graph.microsoft.com/next") == (None, 1)
    assert _graph_next_link("https://[invalid") == (None, 1)


def _graph_next_link(link):
    import asyncio
    import httpx

    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={"value": [], "@odata.nextLink": link})

    async def run():
        async with httpx.AsyncClient(base_url="https://graph.microsoft.com", transport=httpx.MockTransport(handler)) as client:
            return await sync_graph.fetch_attachments(client, "id", {"Authorization": "Bearer test"})

    result = asyncio.run(run())
    return result, len(calls)


def test_graph_fetch_attachments_malformed_json_returns_none():
    import asyncio
    import httpx

    async def run():
        async with httpx.AsyncClient(base_url="https://graph.microsoft.com", transport=httpx.MockTransport(lambda request: httpx.Response(200, text="not json"))) as client:
            return await sync_graph.fetch_attachments(client, "id", {})

    assert asyncio.run(run()) is None


def test_parse_rfc822_reads_reply_to():
    raw = b"From: Ada <ada@example.org>\r\nReply-To: Support <help@example.org>, other@example.org\r\n\r\nBody"
    parsed = sync_imap.parse_rfc822(raw, max_body_chars=100)
    assert json.loads(parsed["reply_to_json"]) == ["help@example.org", "other@example.org"]
    assert json.loads(sync_imap.parse_rfc822(RAW, max_body_chars=100)["reply_to_json"]) == []


def test_gmail_parse_reads_reply_to_header():
    message = {"id": "1", "payload": {"headers": [{"name": "From", "value": "ada@example.org"}, {"name": "Reply-To", "value": "Help <help@example.org>"}]}}
    assert json.loads(sync_gmail.parse_message(message, max_body_chars=100)["reply_to_json"]) == ["help@example.org"]
    assert json.loads(sync_gmail.parse_message(fixture("gmail_message.json"), max_body_chars=100)["reply_to_json"]) == []


def test_graph_parse_reads_reply_to():
    message = {"id": "1", "replyTo": [{"emailAddress": {"address": "help@example.org"}}, {"emailAddress": {}}]}
    assert json.loads(sync_graph.parse_message(message, folder="INBOX", max_body_chars=100)["reply_to_json"]) == ["help@example.org"]
    assert json.loads(sync_graph.parse_message(fixture("graph_message.json"), folder="INBOX", max_body_chars=100)["reply_to_json"]) == []


def test_graph_parse_falls_back_to_the_reply_to_header_without_reply_to_field():
    # An old delta cursor's projection has no replyTo, but it still selects internetMessageHeaders.
    message = {"id": "1", "internetMessageHeaders": [{"name": "Reply-To", "value": "Help <help@example.org>, other@example.org"}]}
    assert json.loads(sync_graph.parse_message(message, folder="INBOX", max_body_chars=100)["reply_to_json"]) == ["help@example.org", "other@example.org"]
    selected = {**message, "replyTo": [{"emailAddress": {"address": "field@example.org"}}]}
    assert json.loads(sync_graph.parse_message(selected, folder="INBOX", max_body_chars=100)["reply_to_json"]) == ["field@example.org"]


def test_connector_parse_has_no_reply_to():
    parsed = sync_connector.parse_message(fixture("connector_thread.json")["messages"][0], thread_id="1", folder="INBOX", max_body_chars=100)
    assert "reply_to_json" not in parsed


# Mail bodies: every provider path turns HTML into the same readable text (DESIGN.md §9.3: mail shows as text).
TEMPLATE_HTML = (FIXTURES / 'template_mail.html').read_text()
TEMPLATE_TEXT = (
    'Waffeltag – Helfer gesucht\n\n'
    'Am Freitag, 21. November, findet der Waffeltag statt.\nWir suchen Helfer & Kuchenspenden.\n\n'
    '• Aufbau ab 8 Uhr\n• Verkauf ab 10 Uhr\n\n'
    'Hallo,\n\nbis bald!\n\n'
    'Melde dich bis Donnerstag: Jetzt anmelden'
)


def _imap_raw(plain: str | None, html: str | None) -> bytes:
    message = EmailMessage()
    message['From'] = 'Fox Education <no-reply@fox.example>'
    message['Subject'] = 'Waffeltag'
    if plain is not None:
        message.set_content(plain)
    if html is not None:
        if plain is None:
            message.set_content(html, subtype='html')
        else:
            message.add_alternative(html, subtype='html')
    return bytes(message)


def _b64(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode()).decode().rstrip('=')


def _parse(provider: str, plain: str | None, html: str | None) -> dict:
    if provider == 'imap':
        return sync_imap.parse_rfc822(_imap_raw(plain, html), max_body_chars=200_000)
    if provider == 'gmail':
        parts = [{'mimeType': mime, 'body': {'data': _b64(text)}} for mime, text in (('text/plain', plain), ('text/html', html)) if text is not None]
        return sync_gmail.parse_message({'id': 'g1', 'payload': {'mimeType': 'multipart/alternative', 'headers': [], 'parts': parts}}, max_body_chars=200_000)
    if provider == 'graph':
        # Graph hands out one body: HTML when the mail has HTML.
        body = {'contentType': 'html', 'content': html} if html is not None else {'contentType': 'text', 'content': plain}
        return sync_graph.parse_message({'id': 'm1', 'body': body}, folder='INBOX', max_body_chars=200_000)
    return sync_connector.parse_message({'id': 'c1', 'plaintextBody': plain or '', 'htmlBody': html or ''}, thread_id='t1', folder='INBOX', max_body_chars=200_000)


PROVIDERS = ['imap', 'gmail', 'graph', 'connector']


@pytest.mark.parametrize('provider', PROVIDERS)
def test_html_only_mail_becomes_readable_text_on_every_provider(provider):
    parsed = _parse(provider, None, TEMPLATE_HTML)
    assert parsed['body_text'] == TEMPLATE_TEXT
    assert parsed['snippet'].startswith('Waffeltag – Helfer gesucht Am Freitag')


PLAIN_LETTER = 'Hallo zusammen,\n\n' + 'am Freitag ist Waffeltag, und wir suchen noch Helfer für den Stand. ' * 4 + '\n\nViele Grüße'


@pytest.mark.parametrize('provider', ['imap', 'gmail', 'connector'])
def test_plain_part_wins_over_html_part(provider):
    assert _parse(provider, PLAIN_LETTER + '\n', TEMPLATE_HTML)['body_text'] == PLAIN_LETTER


@pytest.mark.parametrize('provider', ['imap', 'gmail', 'connector'])
def test_a_short_plain_part_wins_over_html_saying_the_same(provider):
    assert _parse(provider, 'Danke, bis morgen.\n', '<p>Danke, bis <b>morgen</b>.</p>')['body_text'] == 'Danke, bis morgen.'


@pytest.mark.parametrize('provider', ['imap', 'gmail', 'connector'])
def test_a_stub_plain_part_gives_way_to_the_html_text(provider):
    # Newsletters often send only "view this in your browser" as their plain-text part.
    assert _parse(provider, 'Diese E-Mail im Browser ansehen.\n', TEMPLATE_HTML)['body_text'] == TEMPLATE_TEXT


@pytest.mark.parametrize('provider', ['imap', 'gmail', 'connector'])
def test_blank_plain_part_falls_back_to_html(provider):
    assert _parse(provider, ' \n', TEMPLATE_HTML)['body_text'] == TEMPLATE_TEXT


@pytest.mark.parametrize('html, text', [
    ('<title>Hallo<body><p>Inhalt</p>', 'Hallo\n\nInhalt'),  # an unclosed <title> would swallow the mail
    ('<html><title>Hallo<p>Inhalt</p>', 'Hallo\n\nInhalt'),
    ('<head><style>p{color:red}</style><p>Inhalt', 'Inhalt'),  # body content ends an open <head>
    ('<body><p>a</p><head><p>b</p>', 'a\n\nb'),  # a stray <head> inside the body hides nothing
    ('<noscript>Ohne Skript<p>sichtbar</p></noscript>', 'Ohne Skript\n\nsichtbar'),  # mail clients run no scripts
    ('<ul><li><img src="x"></li></ul><p>Danach</p>', 'Danach'),  # an image-only item leaves no bullet behind
    ('<pre>def f():\n    return 1</pre>', 'def f():\n    return 1'),  # <pre> keeps its indentation
    ('<p>vor</p><pre>\n  eingerückt\n    tiefer</pre><p>nach</p>', 'vor\n\n  eingerückt\n    tiefer\n\nnach'),
])
def test_html_to_text_survives_broken_and_unusual_markup(html, text):
    assert sync_types.html_to_text(html) == text


def test_an_unclosed_style_still_hides_what_follows():
    # Negative case: browsers render nothing after an unclosed <style> either; no retry brings CSS back.
    assert sync_types.html_to_text('<p>Text</p><style>p { margin: 0 }') == 'Text'


def test_deeply_nested_skipped_elements_cost_linear_time():
    # Mail is untrusted: 50 000 nested <template> and stray end tags took a minute with an unbounded
    # stack (every end tag searched it), and the sync worker stood still.
    count = 50_000
    html = '<template>' * count + '</style></head>' * count + '</template>' * count + '<p>Hallo</p>'
    started = time.perf_counter()
    assert sync_types.html_to_text(html) == 'Hallo'
    assert sync_types.html_to_text('<template>' * count + 'Versteckt') == ''
    assert time.perf_counter() - started < 3


def test_text_stays_hidden_while_untracked_deep_elements_close():
    # Beyond the tracked depth, end tags first close the untracked openings, never the outer ones.
    depth = sync_types._MAX_SKIP_DEPTH + 1
    html = '<template>' * depth + '</template>' * (depth - 1) + 'Versteckt' + '</template>' + 'Sichtbar'
    assert sync_types.html_to_text(html) == 'Sichtbar'
    assert sync_types.html_to_text('<template>' * depth + '</template>' * depth + '<p>Danach</p>') == 'Danach'


def test_large_html_is_read_to_the_end():
    # An inline image of several MB before the text (data URI) must not cost the text.
    image = '<img src="data:image/png;base64,' + 'A' * 5_000_000 + '">'
    started = time.perf_counter()
    assert sync_types.html_to_text(image + '<p>Frist am Freitag</p>') == 'Frist am Freitag'
    assert time.perf_counter() - started < 3


def test_html_to_text_drops_styles_scripts_title_and_comments():
    text = sync_types.html_to_text(TEMPLATE_HTML)
    for leaked in ('margin', '{', '96', 'Neue Mitteilung', 'nicht anzeigen', 'mso', '<'):
        assert leaked not in text


def test_html_to_text_without_readable_content_is_empty():
    assert sync_types.html_to_text('<html><head><style>p{margin:0}</style></head><body><img src="x.png"></body></html>') == ''


def test_html_to_text_survives_broken_markup():
    # An unclosed <head> must not swallow the mail, and a self-closed <style/> must not hide what follows.
    assert sync_types.html_to_text('<head><style>p{margin:0}</style><body><p>Hallo</p>') == 'Hallo'
    assert sync_types.html_to_text('<p>Vor</p><style/><p>Nach</p>') == 'Vor\n\nNach'


def test_html_to_text_keeps_preformatted_lines():
    assert sync_types.html_to_text('<pre>Zeile 1\nZeile 2</pre>') == 'Zeile 1\nZeile 2'


def test_parse_rfc822_reads_text_with_unknown_charset():
    raw = b'From: a@b.org\r\nContent-Type: text/plain; charset="x-unknown"\r\n\r\nHallo Welt'
    assert sync_imap.parse_rfc822(raw, max_body_chars=100)['body_text'] == 'Hallo Welt'

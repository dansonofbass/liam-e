import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

from db.accessors import mail_message
from db.accessors.mail_message import NewsletterRow
from db.models.mail_account import MailAccount

from api.mail import newsletters


def run(coro):
    return asyncio.run(coro)


def sender(method, link):
    return newsletters.NewsletterSender('a|news@beispiel-shop.test', 'a', 'news@beispiel-shop.test', 'Shop', 2, 1, None, method, link)


def test_unsubscribe_method_prefers_one_click_https():
    assert newsletters.unsubscribe_method('<mailto:news@beispiel-shop.test>, <https://example.test/u>', ' List-Unsubscribe=One-Click ') == ('one_click', 'https://example.test/u')


def test_unsubscribe_method_mailto_without_post_header():
    assert newsletters.unsubscribe_method('<https://example.test/u>, <MAILTO:news@beispiel-shop.test>', '') == ('mailto', 'MAILTO:news@beispiel-shop.test')


def test_unsubscribe_method_http_link_is_manual_only():
    assert newsletters.unsubscribe_method('<http://example.test/u>', 'List-Unsubscribe=One-Click') == ('link', 'http://example.test/u')


def test_one_click_to_private_target_fails_and_does_not_archive(monkeypatch):
    archive = AsyncMock()
    monkeypatch.setattr(newsletters.actions, 'apply_action', archive)
    outcome = run(newsletters.unsubscribe(sender('one_click', 'https://127.0.0.1/u'), SimpleNamespace(id='a')))
    assert (outcome.status, outcome.error_code) == ('failed', 'unsubscribe_blocked')
    archive.assert_not_called()


def test_parse_mailto_sanitizes_subject_and_body():
    target = newsletters.parse_mailto('mailto:leave@list.example.test?Subject=Stop%0D%0ABcc:%20x@y.test&body=line1%0Aline2%09end')
    assert target == newsletters.MailtoTarget('leave@list.example.test', 'Stop Bcc: x@y.test', 'line1 line2 end')


def test_parse_mailto_caps_subject_and_body_at_200():
    long = 'a' * 500
    target = newsletters.parse_mailto(f'mailto:leave@list.example.test?subject={long}&body={long}')
    assert (len(target.subject), len(target.body)) == (200, 200)


def test_parse_mailto_defaults_to_unsubscribe():
    plain = newsletters.parse_mailto('mailto:leave@list.example.test')
    assert (plain.subject, plain.body) == ('unsubscribe', 'unsubscribe')
    blank = newsletters.parse_mailto('mailto:leave@list.example.test?subject=%0D%0A&body=%09')
    assert (blank.subject, blank.body) == ('unsubscribe', 'unsubscribe')


def test_parse_mailto_rejects_bad_recipient_and_scheme():
    assert newsletters.parse_mailto('mailto:a@b.test,c@d.test') is None
    assert newsletters.parse_mailto('mailto:no-at-sign') is None
    assert newsletters.parse_mailto('mailto:%20a@b.test') is None
    assert newsletters.parse_mailto('https://x.test/u') is None


def test_parse_mailto_returns_none_for_malformed_uri():
    assert newsletters.parse_mailto('mailto://[invalid]/leave@list.example.test') is None


def test_mailto_sends_sanitized_values(monkeypatch):
    send = AsyncMock()
    monkeypatch.setattr(newsletters.send, 'send_message', send)
    monkeypatch.setattr(mail_message, 'message_ids_from_sender', AsyncMock(return_value=[]))
    account = SimpleNamespace(id='a')
    link = 'mailto:leave@list.example.test?subject=Stop%0D%0ABcc:%20x@y.test&body=line1%0Aline2%09end'
    outcome = run(newsletters.unsubscribe(sender('mailto', link), account))
    assert outcome.status == 'done'
    send.assert_awaited_once_with(account, to=['leave@list.example.test'], subject='Stop Bcc: x@y.test', body='line1 line2 end')


def test_mailto_invalid_target_sends_nothing(monkeypatch):
    send = AsyncMock()
    monkeypatch.setattr(newsletters.send, 'send_message', send)
    outcome = run(newsletters.unsubscribe(sender('mailto', 'mailto:a@b.test,c@d.test'), SimpleNamespace(id='a')))
    assert (outcome.status, outcome.error_code) == ('failed', 'unsubscribe_invalid')
    send.assert_not_called()


def test_unsubscribe_malformed_mailto_fails_without_send_or_archive(monkeypatch):
    send = AsyncMock()
    monkeypatch.setattr(newsletters.send, 'send_message', send)
    archive = AsyncMock()
    monkeypatch.setattr(newsletters.actions, 'apply_action', archive)
    archive_ids = AsyncMock(return_value=['1'])
    monkeypatch.setattr(mail_message, 'message_ids_from_sender', archive_ids)
    outcome = run(newsletters.unsubscribe(sender('mailto', 'mailto://[invalid]/leave@list.example.test'), SimpleNamespace(id='a')))
    assert (outcome.status, outcome.error_code) == ('failed', 'unsubscribe_invalid')
    send.assert_not_called()
    archive_ids.assert_not_called()
    archive.assert_not_called()


def test_mailto_sends_through_the_account(monkeypatch):
    send = AsyncMock()
    monkeypatch.setattr(newsletters.send, 'send_message', send)
    monkeypatch.setattr(mail_message, 'message_ids_from_sender', AsyncMock(return_value=[]))
    account = SimpleNamespace(id='a')
    outcome = run(newsletters.unsubscribe(sender('mailto', 'mailto:news@beispiel-shop.test?Subject=Stop&body=Please'), account))
    assert outcome.status == 'done'
    send.assert_awaited_once_with(account, to=['news@beispiel-shop.test'], subject='Stop', body='Please')


def test_done_archives_all_inbox_mails_of_sender(monkeypatch):
    monkeypatch.setattr(newsletters.netguard, 'safe_https_post', AsyncMock(return_value=204))
    monkeypatch.setattr(mail_message, 'message_ids_from_sender', AsyncMock(return_value=['1', '2']))
    archive = AsyncMock(side_effect=[SimpleNamespace(id='x'), SimpleNamespace(id='y')])
    monkeypatch.setattr(newsletters.actions, 'apply_action', archive)
    outcome = run(newsletters.unsubscribe(sender('one_click', 'https://example.test/u'), SimpleNamespace(id='a')))
    assert outcome.archived_action_ids == ['x', 'y']
    assert archive.await_count == 2


def test_find_newsletters_includes_never_opened_and_last_read(monkeypatch):
    date = datetime(2025, 1, 1, tzinfo=UTC)
    rows = [NewsletterRow('a', 'news@beispiel-shop.test', 'Shop <news@beispiel-shop.test>', 3, 3, None, '<https://example.test/u>', '', '[]'), NewsletterRow('b', 'other@example.test', '', 2, 1, date, '', '', '["CATEGORY_UPDATES"]')]
    monkeypatch.setattr(mail_message, 'newsletter_senders', AsyncMock(return_value=rows))
    monkeypatch.setattr(newsletters.mail_account, 'list_accounts', AsyncMock(return_value=[SimpleNamespace(id='b', auth_type='mistral_connector')]))
    found = run(newsletters.find_newsletters())
    assert [s.last_read_at for s in found] == [None, date]
    assert [s.method for s in found] == ['link', 'none']


def test_summary_counts_newsletter_senders(client, fake_store, monkeypatch):
    monkeypatch.setattr(newsletters, 'find_newsletters', AsyncMock(return_value=[sender('none', None)]))
    assert client.get('/api/v1/mail/summary').json()['newsletter_senders'] == 1

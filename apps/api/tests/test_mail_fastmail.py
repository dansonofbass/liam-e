"""Fastmail's official presets and allowlist integration; no provider access."""

import socket
from unittest.mock import Mock

import pytest

from api.mail import providers, transport

FASTMAIL = ("imap.fastmail.com", 993, "smtp.fastmail.com", 465, False)

# Independent snapshot of Fastmail's published domain list, checked 2026-11-26.
FASTMAIL_DOMAINS = """
123mail.org 150mail.com 150ml.com 16mail.com 2-mail.com 4email.net 50mail.com
airpost.net aliencamel.com allmail.net cluemail.com elitemail.org emailcorner.net
emailengine.net emailengine.org emailgroups.net emailplus.org emailuser.net eml.cc
f-m.fm fast-email.com fast-mail.org fastem.com fastemailer.com fastest.cc fastimap.com
fastmail.ca fastmail.cn fastmail.com fastmail.com.au fastmail.fm fastmail.im fastmail.in
fastmail.jp fastmail.mx fastmail.net fastmail.org fastmail.to fastmail.tw fastmailbox.net
fastmessaging.com fea.st fmailbox.com fmgirl.com fmguy.com foobox.com foobox.net ftml.net
hailmail.net imap-mail.com imap.cc imapmail.org immerbox.com immermail.com inoutbox.com
internet-e-mail.com internet-mail.org internetemails.net internetmailing.net jetemail.net
justemail.net letterboxes.org lifetimeaddress.com mail-central.com mail-page.com mailas.com
mailbolt.com mailc.net mailcan.com mailforce.net mailhaven.com mailingaddress.org mailite.com
mailmight.com mailnew.com mailsent.net mailservice.ms mailup.net mailworks.org mailzone.com
ml1.net mm.st myfastmail.com mymacmail.com nospammail.net onepost.net ownmail.net penguinmail.com
permanentmail.com petml.com pobox.com postinbox.com postpro.net proinbox.com promessage.com
realemail.net reallyfast.biz reallyfast.info rushpost.com sent.as sent.at sent.com siemprebox.com
siempremail.com speedpost.net speedymail.org ssl-mail.com swift-mail.com the-fastest.net
the-quickest.com theinternetemail.com veribox.net veryfast.biz veryspeedy.net warpmail.net
xsmail.com yepmail.net your-mail.com
fastmail.co.uk fastmail.de fastmail.es fastmail.fr fastmail.nl fastmail.se fastmail.uk fmail.co.uk
bestmail.us fastemail.us fastmail.us h-mail.us
""".split()

LEGACY_PRESETS = [
    ("gmail.com", ("imap.gmail.com", 993, "smtp.gmail.com", 465, False)),
    ("googlemail.com", ("imap.gmail.com", 993, "smtp.gmail.com", 465, False)),
    ("icloud.com", ("imap.mail.me.com", 993, "smtp.mail.me.com", 465, False)),
    ("me.com", ("imap.mail.me.com", 993, "smtp.mail.me.com", 465, False)),
    ("mac.com", ("imap.mail.me.com", 993, "smtp.mail.me.com", 465, False)),
    ("yahoo.com", ("imap.mail.yahoo.com", 993, "smtp.mail.yahoo.com", 465, False)),
    ("ymail.com", ("imap.mail.yahoo.com", 993, "smtp.mail.yahoo.com", 465, False)),
    ("rocketmail.com", ("imap.mail.yahoo.com", 993, "smtp.mail.yahoo.com", 465, False)),
    ("outlook.com", ("outlook.office365.com", 993, "smtp.office365.com", 587, True)),
    ("hotmail.com", ("outlook.office365.com", 993, "smtp.office365.com", 587, True)),
    ("live.com", ("outlook.office365.com", 993, "smtp.office365.com", 587, True)),
]
PRESET_HOSTS = {
    "imap.gmail.com", "smtp.gmail.com", "imap.mail.me.com", "smtp.mail.me.com",
    "imap.mail.yahoo.com", "smtp.mail.yahoo.com", "outlook.office365.com",
    "smtp.office365.com", "imap.fastmail.com", "smtp.fastmail.com",
}


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("a preset test opened a socket or resolved DNS")

    for name in ("socket", "create_connection", "getaddrinfo", "gethostbyname", "gethostbyname_ex"):
        monkeypatch.setattr(socket, name, refuse)


@pytest.mark.parametrize("domain", FASTMAIL_DOMAINS)
@pytest.mark.parametrize("uppercase", [False, True])
def test_official_fastmail_domains(domain, uppercase):
    address_domain = domain.upper() if uppercase else domain
    assert providers.guess_imap_settings(f"me@{address_domain}") == FASTMAIL


@pytest.mark.parametrize("domain", [
    "example.org", "mail.fastmail.com", "mail.fastmail.fm", "fastmail.com.example",
    "fastmail.fm.example", "notfastmail.com", "fastmail.example", "operamail.com",
])
def test_unlisted_domains_are_not_inferred(domain):
    assert providers.guess_imap_settings(f"me@{domain}") is None


@pytest.mark.parametrize("domain,expected", LEGACY_PRESETS)
def test_existing_provider_settings_are_unchanged(domain, expected):
    assert providers.guess_imap_settings(f"me@{domain}") == expected


@pytest.mark.parametrize("configured", ["", " MAIL.EXAMPLE.ORG, "])
def test_allowlist_only_adds_official_fastmail_servers(monkeypatch, configured):
    monkeypatch.setattr(transport.mail_env, "mail_imap_allowed_hosts", configured)
    expected = {host.lower() for preset in providers.IMAP_PRESETS.values() for host in (preset[0], preset[2])}
    expected |= {"mail.example.org"} if configured else set()
    hosts = transport.allowed_hosts()
    assert hosts == expected
    assert PRESET_HOSTS <= hosts
    assert {"pop.fastmail.com", "imap.example.org", "mail.fastmail.com"}.isdisjoint(hosts)


def test_fastmail_preset_uses_verified_implicit_tls(monkeypatch):
    imap = Mock()
    smtp = Mock()
    plaintext_smtp = Mock()
    monkeypatch.setattr(transport.imaplib, "IMAP4_SSL", imap)
    monkeypatch.setattr(transport.smtplib, "SMTP_SSL", smtp)
    monkeypatch.setattr(transport.smtplib, "SMTP", plaintext_smtp)
    settings = providers.guess_imap_settings("me@fastmail.com")

    transport.open_imap(settings[0], settings[1])
    transport.open_smtp(settings[2], settings[3], starttls=settings[4])

    assert imap.call_args.args == ("imap.fastmail.com", 993)
    assert smtp.call_args.args == ("smtp.fastmail.com", 465)
    for context in (imap.call_args.kwargs["ssl_context"], smtp.call_args.kwargs["context"]):
        assert context.check_hostname
        assert context.verify_mode == transport.ssl.CERT_REQUIRED
    plaintext_smtp.assert_not_called()

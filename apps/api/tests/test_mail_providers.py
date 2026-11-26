"""IMAP preset lookup and the preset part of the mail host allowlist; no sockets, no DNS."""

import socket

import pytest

from api.mail import providers, transport

GMAIL = ("imap.gmail.com", 993, "smtp.gmail.com", 465, False)

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

    for name in ("socket", "create_connection", "getaddrinfo", "gethostbyname"):
        monkeypatch.setattr(socket, name, refuse)


@pytest.mark.parametrize("address", ["me@gmail.com", "me@GMAIL.com", "me@Gmail.Com"])
def test_guess_imap_settings_returns_gmail_preset_ignoring_case(address):
    assert providers.guess_imap_settings(address) == GMAIL


def test_googlemail_shares_gmail_servers():
    assert providers.guess_imap_settings("me@googlemail.com") == providers.guess_imap_settings("me@gmail.com")


@pytest.mark.parametrize("domain,expected", LEGACY_PRESETS)
def test_existing_provider_settings_are_unchanged(domain, expected):
    assert providers.guess_imap_settings(f"me@{domain}") == expected


@pytest.mark.parametrize("domain", FASTMAIL_DOMAINS)
def test_official_fastmail_domains(domain):
    assert providers.guess_imap_settings(f"me@{domain}") == FASTMAIL


def test_fastmail_domain_inventory_matches_documented_snapshot():
    actual = {domain for domain, preset in providers.IMAP_PRESETS.items() if preset == FASTMAIL}
    assert actual == set(FASTMAIL_DOMAINS)


def test_fastmail_domain_matching_ignores_case():
    assert providers.guess_imap_settings("me@FastMail.COM") == FASTMAIL


@pytest.mark.parametrize("address", [
    "me@example.org", "me@mail.example.org", "me@mail.gmail.com", "me@gmail.com.example",
    "me@mail.fastmail.com", "me@mail.fastmail.fm", "me@fastmail.com.example",
    "me@fastmail.fm.example", "me@notfastmail.com", "me@fastmail.example", "me@operamail.com",
])
def test_guess_imap_settings_returns_none_without_exact_domain_match(address):
    assert providers.guess_imap_settings(address) is None


def test_allowed_hosts_matches_reviewed_preset_snapshot(monkeypatch):
    monkeypatch.setattr(transport.mail_env, "mail_imap_allowed_hosts", "")
    assert transport.allowed_hosts() == PRESET_HOSTS


def test_allowed_hosts_lowercases_preset_hosts(monkeypatch):
    monkeypatch.setattr(transport.mail_env, "mail_imap_allowed_hosts", "")
    monkeypatch.setitem(providers.IMAP_PRESETS, "mail.test", ("IMAP.Mail.TEST", 993, "SMTP.Mail.TEST", 465, False))
    hosts = transport.allowed_hosts()
    assert {"imap.mail.test", "smtp.mail.test"} <= hosts
    assert "IMAP.Mail.TEST" not in hosts


def test_allowed_hosts_excludes_unknown_host(monkeypatch):
    monkeypatch.setattr(transport.mail_env, "mail_imap_allowed_hosts", "")
    assert "imap.example.org" not in transport.allowed_hosts()

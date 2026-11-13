"""Mail host policy and verified TLS transports.

Check hosts on the event loop before dispatching blocking IMAP/SMTP work.
"""

import imaplib
import smtplib
import ssl

from env.mail import env as mail_env

from api.mail import providers
from api.mail.netguard import resolve_public


class MailHostNotAllowedError(ValueError):
    """The mail server is not in the configured allowlist."""


def allowed_hosts() -> frozenset[str]:
    hosts = {host.lower() for preset in providers.IMAP_PRESETS.values() for host in (preset[0], preset[2])}
    hosts.update(host.strip().lower() for host in mail_env.mail_imap_allowed_hosts.split(",") if host.strip())
    return frozenset(hosts)


async def check_mail_host(host: str) -> None:
    if host.lower() not in allowed_hosts():
        raise MailHostNotAllowedError("Mail host is not allowed")
    await resolve_public(host)


def tls_context() -> ssl.SSLContext:
    return ssl.create_default_context()


def open_imap(host: str, port: int) -> imaplib.IMAP4_SSL:
    return imaplib.IMAP4_SSL(host, port, ssl_context=tls_context(), timeout=30)


def open_smtp(host: str, port: int, *, starttls: bool) -> smtplib.SMTP:
    context = tls_context()
    if not starttls:
        return smtplib.SMTP_SSL(host, port, context=context, timeout=30)
    server = smtplib.SMTP(host, port, timeout=30)
    try:
        server.starttls(context=context)
    except BaseException:
        server.close()
        raise
    return server

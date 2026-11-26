"""Account presentation state tests using only in-memory inputs."""

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from api.mail.state import AccountStatus, account_status, connection


@pytest.mark.parametrize("job_status", ["queued", "running"])
@pytest.mark.parametrize(
    "last_error,expected_error",
    [
        ("", ""),
        ("auth_expired", "auth_expired"),
        ("provider_error", "provider_error"),
        ("Login failed for this account", "provider_error"),
    ],
)
def test_active_sync_job_takes_precedence(job_status, last_error, expected_error):
    last_sync = datetime(2026, 1, 2, tzinfo=timezone.utc)
    sync_state = SimpleNamespace(status="error", last_error=last_error, last_sync_at=last_sync)
    job = SimpleNamespace(kind="sync", status=job_status)

    assert account_status(SimpleNamespace(), sync_state, job) == AccountStatus("syncing", expected_error, last_sync)


@pytest.mark.parametrize("job_status", ["queued", "running"])
def test_active_sync_job_without_sync_state(job_status):
    job = SimpleNamespace(kind="sync", status=job_status)

    assert account_status(SimpleNamespace(), None, job) == AccountStatus("syncing", "", None)


@pytest.mark.parametrize("job_status", ["done", "failed"])
def test_finished_sync_job_does_not_force_syncing(job_status):
    sync_state = SimpleNamespace(status="ok", last_error="", last_sync_at=None)
    job = SimpleNamespace(kind="sync", status=job_status)

    assert account_status(SimpleNamespace(), sync_state, job) == AccountStatus("ok", "", None)


@pytest.mark.parametrize("job_status", ["queued", "running"])
def test_non_sync_job_does_not_force_syncing(job_status):
    sync_state = SimpleNamespace(status="error", last_error="auth_expired", last_sync_at=None)
    job = SimpleNamespace(kind="insights", status=job_status)

    assert account_status(SimpleNamespace(), sync_state, job) == AccountStatus("auth_expired", "auth_expired", None)


def test_missing_sync_state():
    assert account_status(SimpleNamespace(), None, None) == AccountStatus("never", "", None)


@pytest.mark.parametrize(
    "sync_status,last_error,expected_status,expected_error",
    [
        ("ok", "", "ok", ""),
        ("ok", "auth_expired", "auth_expired", "auth_expired"),
        ("error", "auth_expired", "auth_expired", "auth_expired"),
        ("ok", "provider_unavailable", "error", "provider_unavailable"),
        ("error", "provider_unavailable", "error", "provider_unavailable"),
        ("error", "", "error", ""),
        ("error", "Login failed for this account", "error", "provider_error"),
        ("ok", "AUTH_EXPIRED", "error", "provider_error"),
        ("error", "provider-error", "error", "provider_error"),
        ("error", "a" * 65, "error", "provider_error"),
        ("error", "a" * 64, "error", "a" * 64),
    ],
)
def test_stored_sync_status(sync_status, last_error, expected_status, expected_error):
    last_sync = datetime(2026, 1, 2, tzinfo=timezone.utc)
    sync_state = SimpleNamespace(status=sync_status, last_error=last_error, last_sync_at=last_sync)

    assert account_status(SimpleNamespace(), sync_state, None) == AccountStatus(expected_status, expected_error, last_sync)


@pytest.mark.parametrize(
    "auth_type,expected",
    [("mistral_connector", "connector"), ("oauth2", "oauth"), ("imap_password", "imap")],
)
def test_connection(auth_type, expected):
    assert connection(SimpleNamespace(auth_type=auth_type)) == expected

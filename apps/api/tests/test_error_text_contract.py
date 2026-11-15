"""User-facing refusal codes retain their agreed German explanations."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import HTTPException
from utils.mistral import MistralNotConfiguredError

from api.mail import actions, crypto, insights, secrets, transport
from api.routers.api.v1.chat import conversations, history, proposals, route
from api.routers.api.v1.mail import accounts, connectors, messages

pytestmark = pytest.mark.anyio


def assert_detail(error, code, text):
    assert error.value.detail == {"code": code, "message": text}


async def test_missing_history_and_mail_and_account(monkeypatch):
    monkeypatch.setattr(history.conversation_access, "get_conversation", AsyncMock(return_value=None))
    monkeypatch.setattr(messages.message_access, "get_message", AsyncMock(return_value=None))
    monkeypatch.setattr(accounts.account_access, "get_account", AsyncMock(return_value=None))
    cases = [
        (history.history("missing"), "conversation_not_found", "Diese Unterhaltung gibt es nicht mehr. Starte eine neue Unterhaltung."),
        (messages.get_message("missing"), "message_not_found", "Die Mail ist nicht mehr da."),
        (messages.message_original("missing"), "message_not_found", "Die Mail ist nicht mehr da."),
        (accounts.sync_account("missing"), "account_not_found", "Das Konto gibt es nicht mehr."),
    ]
    for call, code, text in cases:
        with pytest.raises(HTTPException) as error:
            await call
        assert_detail(error, code, text)


@pytest.mark.parametrize("status,code,text", [
    (404, "connector_not_found", "Den Connector gibt es in Mistral Studio nicht mehr. Leg ihn dort wieder an oder verbinde das Konto auf anderem Weg."),
    (401, "connector_auth_required", "Der Connector ist in Mistral Studio nicht angemeldet. Melde ihn dort unter Connector → Auth an und versuch es dann noch mal."),
    (500, "connector_failed", "Der Connector antwortet gerade nicht. Versuch es gleich noch mal."),
])
async def test_connector_refusals(status, code, text):
    error = connectors._http_error(SimpleNamespace(status_code=status))
    assert error.detail == {"code": code, "message": text}


@pytest.mark.parametrize("failure,code,text", [
    (secrets.SecretNameNotAllowedError("bad"), "secret_not_allowed", "Der Name muss auf „-app-password“ enden, etwa „yahoo-app-password“, und darf nur Kleinbuchstaben, Ziffern und Bindestriche enthalten. Leg das Secret in Mistral Studio unter so einem Namen an."),
    (secrets.WorkspaceSecretNotFoundError("missing"), "secret_not_found", "Das Secret wurde nicht gefunden oder ist nicht lesbar. Prüfe den Namen und die Freigabe in Mistral Studio."),
    (OSError("bad login"), "login_failed", "Die Anmeldung beim Mailserver hat nicht geklappt. Prüfe die Serveradresse und das App-Passwort."),
])
async def test_imap_refusals(monkeypatch, failure, code, text):
    monkeypatch.setattr(transport, "check_mail_host", AsyncMock())
    monkeypatch.setattr(secrets, "resolve_workspace_secret", AsyncMock(side_effect=failure if code == "secret_not_found" else None, return_value="password"))
    monkeypatch.setattr(accounts, "check_imap_login", AsyncMock(side_effect=failure if code == "login_failed" else None))
    name = "bad" if code == "secret_not_allowed" else "yahoo-app-password"
    with pytest.raises(HTTPException) as error:
        await accounts.connect_imap(accounts.ImapConnectRequest(email_address="a@yahoo.com", password_secret=name))
    assert_detail(error, code, text)


@pytest.mark.parametrize("failure,code,text", [
    (MistralNotConfiguredError("missing"), "mistral_not_configured", "liam-e hat keinen Zugang zu Mistral Studio. Hinterleg für die App einen MISTRAL_API_KEY aus diesem Workspace, starte sie neu und versuch es dann noch mal."),
    (secrets.WorkspaceSecretAccessDeniedError("refused"), "secret_access_denied", "Mistral Studio lässt liam-e die Secrets nicht lesen. Prüfe, ob der MISTRAL_API_KEY der App zu diesem Workspace gehört und noch gültig ist."),
    (httpx.ConnectError("down"), "secret_unavailable", "Mistral Studio antwortet gerade nicht, das Secret ließ sich nicht lesen. Versuch es gleich noch mal."),
])
async def test_imap_app_access_refusals(monkeypatch, failure, code, text):
    monkeypatch.setattr(transport, "check_mail_host", AsyncMock())
    monkeypatch.setattr(secrets, "resolve_workspace_secret", AsyncMock(side_effect=failure))
    with pytest.raises(HTTPException) as error:
        await accounts.connect_imap(accounts.ImapConnectRequest(email_address="a@yahoo.com", password_secret="yahoo-app-password"))
    assert_detail(error, code, text)


async def test_imap_encryption_refusal(monkeypatch):
    monkeypatch.setattr(transport, "check_mail_host", AsyncMock())
    monkeypatch.setattr(secrets, "resolve_workspace_secret", AsyncMock(return_value="password"))
    monkeypatch.setattr(accounts, "check_imap_login", AsyncMock())
    monkeypatch.setattr(crypto.mail_env, "mail_token_encryption_key", None)
    with pytest.raises(HTTPException) as error:
        await accounts.connect_imap(accounts.ImapConnectRequest(email_address="a@yahoo.com", password_secret="yahoo-app-password"))
    assert_detail(error, "encryption_not_configured", "liam-e kann das Konto nicht verschlüsselt speichern, weil der Schlüssel fehlt. Leg in Mistral Studio das Secret „mail_token_encryption_key“ an, falls es fehlt, starte die App neu und verbinde das Konto dann noch einmal.")


async def test_original_refusals(monkeypatch):
    from api.mail import original
    monkeypatch.setattr(messages.message_access, "get_message", AsyncMock(return_value=SimpleNamespace(account_id="a")))
    monkeypatch.setattr(messages.account_access, "get_account", AsyncMock(return_value=None))
    with pytest.raises(HTTPException) as error:
        await messages.message_original("m")
    assert_detail(error, "original_unavailable", "Bei dieser Mail lässt sich das Original nicht abrufen.")
    monkeypatch.setattr(original, "available", lambda account: True)
    monkeypatch.setattr(original, "fetch", AsyncMock(side_effect=TimeoutError()))
    with pytest.raises(HTTPException) as error:
        await messages.message_original("m")
    assert_detail(error, "provider_failed", "Das Original ließ sich beim Anbieter nicht abrufen. Versuch es gleich noch mal.")


async def test_action_and_insight_refusals(monkeypatch):
    monkeypatch.setattr(actions, "apply_action", AsyncMock(side_effect=actions.ActionUnsupportedError()))
    with pytest.raises(HTTPException) as error:
        await messages.message_action("m", messages.MessageActionIn(kind="archive"))
    assert_detail(error, "action_unsupported", "Das geht bei dieser Mail nicht.")
    monkeypatch.setattr(insights, "get_or_compute", AsyncMock(side_effect=insights.InsightError()))
    with pytest.raises(HTTPException) as error:
        await messages.message_insight("m")
    assert_detail(error, "insight_unavailable", "Das Modell antwortet gerade nicht, deshalb fehlt die Zusammenfassung. Öffne die Mail gleich noch mal.")


async def test_unknown_model_and_reconnect(monkeypatch):
    monkeypatch.setattr(conversations.conversation_access, "get_conversation", AsyncMock(return_value=SimpleNamespace()))
    monkeypatch.setattr(conversations, "list_chat_models", AsyncMock(return_value=[]))
    with pytest.raises(HTTPException) as error:
        await conversations.update_conversation("c", conversations.ChatConversationUpdateIn(model="missing"))
    assert_detail(error, "model_unknown", "Dieses Modell gibt es nicht mehr. Wähle ein anderes.")
    monkeypatch.setattr(accounts.account_access, "get_account", AsyncMock(return_value=SimpleNamespace(auth_type="imap_password", provider="imap")))
    with pytest.raises(HTTPException) as error:
        await accounts.oauth_authorize("google", SimpleNamespace(), account_id="a")
    assert_detail(error, "reconnect_unsupported", "Dieses Konto lässt sich über diese Anmeldung nicht neu verbinden. Entferne es und verbinde es danach neu.")


async def test_oauth_not_configured_refusal(monkeypatch):
    monkeypatch.setattr(accounts.providers, "oauth_configured", lambda provider: False)
    with pytest.raises(HTTPException) as error:
        await accounts.oauth_authorize("google", SimpleNamespace())
    assert_detail(error, "oauth_not_configured", "Die Anmeldung ist nicht eingerichtet. Prüfe die Einstellungen in Mistral Studio.")


async def test_chat_internal_refusal(monkeypatch):
    async def events(**kwargs):
        yield SimpleNamespace(event="error", code="internal")
    monkeypatch.setattr(route.agent, "run_turn_events", events)
    with pytest.raises(HTTPException) as error:
        await route.chat_turn(route.ChatTurnRequest(message="Hallo"))
    assert_detail(error, "internal", "Die Antwort konnte nicht erstellt werden. Versuch es gleich noch mal.")


async def test_proposal_refusal():
    from api.mail.proposals import ProposalStateError, ProposalSelectionError
    with pytest.raises(HTTPException) as error:
        proposals._refuse(ProposalStateError())
    assert_detail(error, "proposal_not_pending", "Dieser Vorschlag ist schon erledigt oder abgebrochen. Lade die Unterhaltung neu, um den Stand zu sehen.")
    with pytest.raises(HTTPException) as error:
        proposals._refuse(ProposalSelectionError("selection_empty"))
    assert_detail(error, "selection_empty", "Wähle mindestens einen Eintrag aus.")

"""Settings for the mail feature: OAuth clients, credential encryption, sync, and the chat agent.

The OAuth client secrets and the credential-encryption key are marked ``WorkspaceSecret``, so on
Mistral Apps they are read from the workspace secrets of the same name; locally they come from the
repo-root ``.env`` (gitignored). Names only are declared in the root ``.env.example`` — defaults
live here, never in two places.
"""

from typing import Annotated

from env._base import BaseEnv
from env._mistral_secrets import WorkspaceSecret


class Env(BaseEnv):
    # OAuth2 app credentials, registered at Google Cloud Console / Azure Entra ID.
    mail_oauth_google_client_id: Annotated[str | None, WorkspaceSecret()] = None
    mail_oauth_google_client_secret: Annotated[str | None, WorkspaceSecret()] = None
    mail_oauth_microsoft_client_id: Annotated[str | None, WorkspaceSecret()] = None
    mail_oauth_microsoft_client_secret: Annotated[str | None, WorkspaceSecret()] = None

    # Public base URL of the deployed app, used to build OAuth redirect URIs. Empty derives it
    # from each request; on Mistral Apps set it to the app's public URL.
    mail_oauth_redirect_base_url: str = ""

    # Fernet key that encrypts mail credentials at rest (api/mail/crypto.py). Generate one with:
    #   bash tools/uv.sh run --no-sync python -c "from api.mail.crypto import new_key; print(new_key())"
    mail_token_encryption_key: Annotated[str | None, WorkspaceSecret()] = None

    # Additional allowed IMAP/SMTP hosts, comma-separated.
    mail_imap_allowed_hosts: str = ""

    # Sync behavior: which folders to index, how many messages per run, and the body cap so one
    # huge mail cannot blow up the index.
    mail_sync_enabled: bool = True
    mail_sync_folders: str = "INBOX"
    mail_sync_page_size: int = 100
    mail_sync_max_body_chars: int = 200_000

    # Chat agent (tool loop over the synced mail index).
    mail_chat_model: str = "mistral-medium-latest"
    mail_chat_max_tool_rounds: int = 8


env = Env()

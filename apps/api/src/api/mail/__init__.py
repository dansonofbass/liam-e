"""The mail domain of the API: connect accounts, sync them into the local index, send, and chat.

- ``crypto`` encrypts credentials at rest (Fernet under ``MAIL_TOKEN_ENCRYPTION_KEY``).
- ``providers`` knows the OAuth2 endpoints/scopes (Google, Microsoft) and IMAP/SMTP presets.
- ``service`` loads/saves a connected account's decrypted credential and refreshes OAuth tokens.
- ``sync`` fills ``mail_message`` from IMAP, the Gmail API, or Microsoft Graph.
- ``send`` sends a mail via SMTP, the Gmail API, or Graph — only ever called for confirmed drafts.
- ``agent`` is the chat tool loop over the synced index (reads free, sends only as pending drafts).
"""

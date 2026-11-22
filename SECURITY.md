# Security policy

## Supported versions

Fixes are provided only for the current state of `main`.

## Report a vulnerability

Please report privately through GitHub's private vulnerability reporting: open the **Security**
tab and choose **Report a vulnerability**, or go straight to the
[reporting form](https://github.com/plagor44-ux/liam-e/security/advisories/new). A suspected
vulnerability does not belong in a public issue, pull request or discussion.

The report opens a draft security advisory that only you and the maintainer can see. Questions,
a fix and the disclosure are handled there before anything becomes public. If the button is
missing, open an issue that asks for a private channel and contains no details.

Useful information includes the tested version (commit or date), the affected route or function,
and reproduction steps using synthetic data. Never include credentials, tokens, app passwords,
real mail or appointments, Mistral organization, workspace or app IDs, or absolute local paths.

## What counts

liam-e promises a narrow boundary (AGENTS.md, sections “Security” and “Publication and private
data”). Reports of a broken promise are in scope, for example:

- The agent sends, replies to, forwards or changes a mail without a confirmed proposal card,
  including when triggered by a crafted mail or template.
- A credential, app password, token or secret value appears in a response, log, error message or
  unencrypted in the database.
- An outgoing call reaches a private destination (SSRF, DNS rebinding) or a disallowed mail host
  despite `netguard.py` and `transport.py`.
- A query returns data from an account or source outside the requested scope.
- A mutating operation is accessible through a read-only MCP interface.

## What does not count

- liam-e is a single-user app. The deployment in Mistral Studio, not the app, controls who may
  access it through the gateway. Lack of multi-user separation is a documented limitation.
- Vulnerabilities in Mistral Studio, mail providers or dependencies belong to those projects.
  An advisory affecting liam-e in its own usage counts.
- An incorrect model summary or answer without consequences for sending, data or permissions is
  not a security bug.

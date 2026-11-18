# Contributing

[AGENTS.md](AGENTS.md) is binding for architecture, conventions and security, and
[DESIGN.md](DESIGN.md) for the UI and its text. This file summarizes what applies to issues and
pull requests. Please open an issue before major work.

## Setup and checks

The [local development guide](docs/local-development.md) describes installation, the database,
startup order and seed mode.

```bash
bun run check                # Build, UI type check, client drift check
bunx nx run web:test
bash tools/uv.sh run --no-sync pytest tests apps/api/tests packages/py -q
RUN_PG_CONTRACT=1 bunx nx run db:test-pg-contract   # requires Postgres with pgvector
```

The tests require neither provider access nor Mistral credentials.

## Rules in brief

- Code, comments, docstrings and commit messages are in English; UI text is in German through the
  text catalogue.
- After API changes, regenerate and commit the OpenAPI specification and client. Table changes
  require a generated migration.
- The agent never changes or sends anything without a confirmed proposal card. New mutating
  operations belong in the MCP inventory (`apps/api/tests/test_mcp_exposure.py`).
- Synthetic test data only. No credentials, real mail, Mistral IDs or local paths in files,
  issues, PRs, commit messages or logs.

## Issues

Issues use the forms in [`.github/ISSUE_TEMPLATE/`](.github/ISSUE_TEMPLATE/):
[bug](.github/ISSUE_TEMPLATE/01-bug.yml), [change](.github/ISSUE_TEMPLATE/02-change.yml),
[evaluation](.github/ISSUE_TEMPLATE/03-evaluation.yml) and
[subtask](.github/ISSUE_TEMPLATE/04-subtask.yml). Each asks for acceptance criteria and how to
verify them, so a person or coding agent can implement the issue and a reviewer can check it.
Suspected vulnerabilities do not belong in an issue; see [SECURITY.md](SECURITY.md).

## Pull requests

Pull requests follow [`.github/pull_request_template.md`](.github/pull_request_template.md).

- One task produces one branch and one PR. If it covers multiple issues, each gets its own
  commits and its own closing keyword (`Closes #12. Closes #13.`).
- Describe what was checked and how, with the commands actually run. Tests with fakes do not
  prove live behavior in Studio, at providers or on devices; explicitly state what was not checked.
- CI (`check`, `web-test`, `pytest`, `pg-contract`, `secrets`) must pass.

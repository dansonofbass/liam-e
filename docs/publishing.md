# Before publication

As of 2026-11-22. The repository is private and will be made public later. This page records
the decision on how, what the last check found, and what is left to configure. The ongoing rules
are in [AGENTS.md](../AGENTS.md), section “Publication and private data”.

## Decision of 2026-11-22

The owner chose option (a): this repository becomes public as it is, with its full history.

- **No second repository and no history rewrite.** A rewrite with `git filter-repo` would not
  remove the old commits from GitHub: the read-only `refs/pull/*` refs and force-pushed states
  keep them reachable, and only GitHub support can delete them. All commit hashes would change,
  so references in issues, pull requests and docs would point nowhere.
- **The Mistral IDs stay in `mistral.json`.** `mistral deploy` reads the `deployment` block
  from the pushed state; without it a deployment creates a new app. Organization, workspace and
  app IDs are identifiers, not credentials: the Studio gateway still needs a browser session or
  a workspace key. Older commits contain the same IDs.
- **License: Apache-2.0**, copyright holder `plagor44-ux`. See [LICENSE](../LICENSE) and
  [NOTICE](../NOTICE). The scaffold and two of the agent skills already come from Mistral AI
  under Apache-2.0.
- **`Claude-Session` lines stay** in commits and pull requests. Only the session ID becomes
  public; the session itself stays private.

## Findings of 2026-11-22

All tracked files, the Git history of all branches, the texts and edit histories of all issues
and pull requests on GitHub, the workflows and the GitHub settings were checked.

- **Secrets:** none found. The CI job `secrets` runs gitleaks over the history of all branches.
  Thirteen commits that are reachable on GitHub only because of force-pushes were checked
  separately; they are clean as well.
- **Files on `main`:** `tests/test_public_repo_hygiene.py` passes. The pull request that added
  this page also added the license files, removed the scheduled OpenWiki workflow (it failed on
  every run and held write permissions), replaced a local path and agent tool names in two
  docs with neutral wording, and made the remaining test identifiers visibly synthetic. The
  hygiene test now also flags paths under `~/`.
- **History:** older commits still contain the Mistral IDs (implementation plan of 13.11.), two
  links to private Claude artifacts and the name of another of the owner's projects. All were
  removed from `main` on 2026-11-17. Commits carry the author's first name, GitHub noreply
  addresses and `Claude-Session` links. Decision (a) accepts this.
- **Issues and pull requests:** no uploaded images or attachments. Some pull request
  descriptions and their edit histories name the review profiles of the tools used, the models
  behind them and internal run IDs. This is not private information.
- **Actions:** `.github/workflows/ci.yml` is safe for a public repository: no
  `pull_request_target`, read-only token, no secrets, actions pinned to full commit SHAs. Logs
  of past runs become public with the repository.

## Smaller open decisions

- **Author name:** keep the first name in commit metadata (recommended), or use the GitHub
  login as `user.name` from now on. The history keeps the first name either way.
- **Tool names in pull request texts:** accept (recommended), or edit the texts before the
  switch and delete the old revisions under “Edited”.
- **Old test UUID:** a test UUID that was replaced by a synthetic value is still in the
  history. Confirm once that it is not the owner's Mistral user ID.

## Checklist

**Before the switch, in the repository:**

- [x] `LICENSE` and `NOTICE` (Apache-2.0); README section “License”.
- [x] Scheduled OpenWiki workflow removed; the generated `openwiki/` pages stay.
- [x] Local path and agent tool names removed from the docs; the hygiene test flags `~/` paths.
- [x] Visibly synthetic test IDs and reserved example domains; origin of the audio sample in
  `NOTICE`.
- [ ] CI green on `main`, including the job `secrets`.

**Before the switch, in the GitHub settings:**

- [ ] *Actions → General:*
  - Require approval for fork pull request workflows from all external contributors.
  - Keep “Workflow permissions” at *Read* (already set).
  - Keep “Allow GitHub Actions to create and approve pull requests” off (already off).
  - Allow only selected actions, or require actions to be pinned to a full-length commit SHA.
    The workflow is already pinned.
- [ ] *General → Features:* turn off Wiki and Projects (both are empty).
- [ ] *General → Pull Requests:* turn on “Automatically delete head branches”. Optionally delete
  the old branches on `origin`; they were checked and are clean.
- [ ] *General → Social preview:* upload `docs/assets/social-preview.png`. Set a description and
  topics (both empty).
- [ ] Optional: delete old Actions runs, including the failed OpenWiki runs.

**The switch:**

- [ ] *General → Danger Zone → Change visibility → Public.* This only looks reversible: clones,
  forks and third-party caches cannot be recalled.

**Right after the switch:**

- [ ] *Security → Private vulnerability reporting:* turn on. SECURITY.md and the issue form
  already point to it.
- [ ] *Security → Secret scanning* and *Push protection:* turn on, then review the first alerts.
  Secret scanning also scans the history.
- [ ] *Security → Dependabot alerts* and *Dependabot security updates:* turn on. Optionally add a
  `.github/dependabot.yml` for `github-actions` so the pinned SHAs receive updates.
- [ ] Optional: *Code scanning → CodeQL default setup*.
- [ ] *Rules → Rulesets* for `main`:
  - changes only through pull requests, with 0 required approvals (single owner);
  - required checks as GitHub lists them after a CI run: “bun run check”, “Web tests”,
    “pytest”, “Postgres contract suite” and “Secret scan (gitleaks)” (the job IDs `check`,
    `web-test`, `pytest`, `pg-contract` and `secrets` do not appear there);
  - block force pushes and deletion;
  - whether administrators may bypass the ruleset is the owner's choice.
- [ ] *Insights → Community standards:* check LICENSE, SECURITY.md, CONTRIBUTING.md and the
  templates.

## What will never be public

Workspace secrets in Studio, the local `.env`, the deployment database and traces in Studio.

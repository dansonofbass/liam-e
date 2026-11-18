# Before publication

As of 2026-11-17. The repository is private and should be publishable later. This list names
what still needs to be decided and configured for that. The ongoing rules are in
[AGENTS.md](../AGENTS.md), section “Veröffentlichung und private Daten”.

## Findings from 2026-11-17

All tracked files, the Git history of all branches and the text of all issues and pull requests
on GitHub were checked.

- **Files:** The Mistral IDs now appear only in `mistral.json`. Links to private Claude artifacts
  were replaced by names, and names of the owner's other projects by a general description.
  Test addresses are synthetic; there are no absolute home paths.
  `tests/test_public_repo_hygiene.py` preserves this state (it does not check project names).
- **History:** A local search for common key and token patterns found nothing. The definitive
  evidence comes from the CI job `secrets` (gitleaks over the entire history). Older commits
  still contain the Mistral IDs (in the implementation plan of 13.11.) and the artifact links
  (DESIGN.md, plan, spec), as well as names of the owner's other projects (DESIGN.md). Commits
  carry the author's first name, a GitHub noreply address and `Claude-Session` links.
- **Issues and PRs:** No private information found. PR descriptions name review profiles and
  model families of the tools used for review.

## Owner's open decisions

1. **History.** (a) Publish as-is: the IDs are not secrets but reveal the Studio tenant.
   (b) Remove IDs and links from history with `git filter-repo`: all commit hashes change,
   leaving references in issues and PRs pointing nowhere. (c) A new public repository with a
   fresh initial commit; the private one remains the working and deployment repository.
2. **Mistral IDs in `mistral.json`.** `mistral deploy` builds from the pushed state and reads the
   `deployment` block; without it a deployment creates a new app. If the IDs must not become
   public, this is only possible with separate repositories as in (c).
3. **License.** There is no `LICENSE`. Without a license nobody may use the code. The adopted
   skills under `.agents/skills/` come with their own licenses.
4. Keep **`Claude-Session` lines** in commits and PRs (as in the other public repositories),
   or omit them in future.

## GitHub settings when switching

- Enable private vulnerability reporting; SECURITY.md and the issue form point to it.
- Enable Secret Scanning and Push Protection.
- Branch protection for `main`: changes only through PRs. Select the required checks as GitHub
  offers them after a CI run: “bun run check”, “Web tests”, “pytest”, “Postgres contract suite”
  and “Secret scan (gitleaks)” (the job IDs `check`, `web-test`, `pytest`, `pg-contract`,
  `secrets` do not appear there).
- Enable Dependabot security updates.

## What will never be public

Workspace secrets in Studio, the local `.env`, the deployment database and traces in Studio.

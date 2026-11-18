# Architecture and Process Decisions

Classification: For Review

## ADR-001 — `claude-review.yml` alignment with `anthropics/claude-code-action@v1` (Step 00)
- **Context:** Step 00 requires verifying all inputs and flags in Appendix B (`.github/workflows/claude-review.yml`) against Anthropic's official `anthropics/claude-code-action@v1` documentation before finalizing the workflow.
- **Decision:** Keep the `pull_request` trigger (`opened`, `synchronize`, `ready_for_review`), concurrency group, fork/draft guard, `actions/checkout@v4` (`fetch-depth: 0`), `--max-turns 10`, and `--max-budget-usd 2`, and add:
  1. `id-token: write` and `issues: write` under `permissions:` (required for Claude GitHub App OIDC authentication and posting PR comments).
  2. `--allowedTools "Read,Grep,Glob,Bash(gh pr comment:*),Bash(gh pr diff:*),Bash(gh pr view:*),Bash(git diff:*),Bash(git log:*),Bash(git status:*)"` in `claude_args`, because in `anthropics/claude-code-action@v1` plain-text `prompt` mode defaults to no granted tools unless explicitly allowlisted.
  3. Explicit `REPO: ${{ github.repository }}` and `PR NUMBER: ${{ github.event.pull_request.number }}` context in `prompt` with explicit instruction to post via `gh pr comment`.
- **Alternatives:** Use Appendix B verbatim without `id-token: write` or `--allowedTools`.
- **Reason:** Without `id-token: write`, the Claude GitHub App OIDC flow fails; without `--allowedTools` and PR context, Claude cannot read repository files, inspect diffs, or post the review comment in `prompt` mode.

## ADR-002 — Private repository branch protection on GitHub Free (Step 00)
- **Context:** Step 00 requires enabling branch protection on `main` (require pull request, require owner approval, block direct pushes) and verifying that Antigravity cannot push to `main`.
- **Decision:** Keep the repository private (per Section 0 Rule 12), refrain from making any direct push to `main`, install a local Git `pre-push` hook inside `.git/hooks/pre-push` blocking pushes to `main`, and record the GitHub API finding (`403: Upgrade to GitHub Pro or make this repository public to enable this feature`) in the Step 00 report so the owner can choose either to upgrade to GitHub Pro and enable server-side protection or approve this documented deviation.
- **Alternatives:**
  1. Upgrade the repository owner's account to GitHub Pro (paid plan) and enable branch protection / Rulesets on `main`.
  2. Make the repository public (rejected — violates Section 0 Rule 12).
- **Reason:** Branch protection and Rulesets on private repositories are unavailable on GitHub Free (`protected: false`, `403` on rules endpoint). A local `pre-push` hook prevents accidental pushes from this workstation without violating repository privacy or making unauthorized paid-account changes.

## ADR-003 — Commit `ANTIGRAVITY_BUILD_PLAN.md` in Step 00 (Step 00)
- **Context:** `CLAUDE.md` (Appendix A) and `.github/workflows/claude-review.yml` (Appendix B) instruct the automated reviewer to read the matching step in `ANTIGRAVITY_BUILD_PLAN.md` during PR reviews.
- **Decision:** Include `ANTIGRAVITY_BUILD_PLAN.md` in the initial Step 00 commit on branch `step-00-github-review-pipeline`.
- **Alternatives:** Leave `ANTIGRAVITY_BUILD_PLAN.md` untracked locally until Step 01.
- **Reason:** The GitHub Actions reviewer checks out only repository contents and cannot access untracked local files.

## ADR-004 — Preserve `anthropics/claude-code-action@v1` OIDC workflow validation (Step 00)
- **Context:** During the Step 00 dummy PR smoke test ([PR #1](https://github.com/mohokok/ai-engineering-agent/pull/1), Actions run `44326920938`), `anthropics/claude-code-action@v1` obtained an OIDC token and exited cleanly with: `Workflow validation failed. The workflow file must exist and have identical content to the version on the repository's default branch. If you're seeing this on a PR when you first add a code review workflow file to your repository, this is normal and you should ignore this error.`
- **Decision:** Do **not** override `github_token` with `${{ secrets.GITHUB_TOKEN }}` to bypass OIDC workflow validation; instead, require the owner to merge the initial Step 00 PR (`step-00-github-review-pipeline` -> `main`) first so `.github/workflows/claude-review.yml` exists on `main`, and then execute post-merge verification of the dummy PR and fake-secret PR acceptance tests.
- **Alternatives:** Pass `github_token: ${{ secrets.GITHUB_TOKEN }}` to skip the Claude GitHub App OIDC token exchange.
- **Reason:** The default-branch parity check is an intentional anti-tampering control preventing PR branches from modifying `.github/workflows/claude-review.yml` to misuse `ANTHROPIC_API_KEY` or weaken review rules, and Step 00 explicitly relies on the Claude GitHub App (`https://github.com/apps/claude`).


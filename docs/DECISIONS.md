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

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

## ADR-005 — Owner-approved public repository with strict zero-leak rule and tightened `protect-main` ruleset (Step 00 FIX)
- **Context:** On GitHub Free, repository rulesets require public visibility (`403` when private), and the initial `protect-main` ruleset (`required_approving_review_count: 0`, `bypass_actors: []`) allowed a fast-forward push of open PR #2's head commit to `main` (`e4d4942`).
- **Decision:** Keep `mohokok/ai-engineering-agent` **public** with explicit owner approval, update Section 0 Rule 12 (+ Rule 12a) and Step 00 in `ANTIGRAVITY_BUILD_PLAN.md` to forbid committing client files, drawings, personal data, keys, or tokens (because everything in this repo is publicly visible), and require `protect-main` on `main` to enforce `required_approving_review_count: 1`, `bypass_actors` = Repository admin (`actor_id: 5`) with `bypass_mode: "pull_request"`, plus deletion and force-push blocks. Explicitly accept and document the remaining limitation: Antigravity's fine-grained PAT belongs to the owner's account (`mohokok`), so it acts as the owner and `bypass_mode: "pull_request"` would technically permit that token to merge a PR via the GitHub API; direct pushes to `main` are blocked server-side, while PR self-merging is guarded by Rule 2a until/unless a separate non-admin collaborator account is created for Antigravity.
- **Alternatives:** Upgrade to GitHub Pro to keep the repository private with rulesets, or create a separate non-admin GitHub account for Antigravity with Write-only permissions.
- **Reason:** Owner explicitly approved keeping the repository public so free repository rulesets protect `main`, and explicitly accepted documenting the owner-token PR-merge bypass limitation in ADR-005 and the Step 00 report. On 2026-11-18, the owner also explicitly approved Rules 12, 12a, 14, and Section 4 item 6, confirmed the owner will merge all PRs manually, and accepted that the redacted local scratch paths from earlier PR #6 commits remain in PR #6's unmerged branch history (while scrubbed from `HEAD`/`main`).

## ADR-006 — UTF-8 (no BOM) Rule 14 and Step 00 Node encoding test (Step 00 FIX)
- **Context:** During PR #3 dummy README testing, PowerShell `Set-Content` without `-Encoding UTF8` wrote Windows-1252 `0x97`, which `claude[bot]` flagged as encoding corruption risk for Arabic/RTL text. Python is not yet set up until Step 01, while Node.js (`v24.18.0`) is installed.
- **Decision:** Add Section 0 Rule 14 requiring UTF-8 (no BOM) across all repository text files, add `docs/arabic-utf8-sample.md`, and verify every tracked text file in `git ls-files` with `tests/test_utf8_encoding.mjs` (`node --test`).
- **Alternatives:** Wait until Step 01 to write a `pytest` encoding test.
- **Reason:** Establishing the encoding rule and automated test in Step 00 prevents silent Windows-1252 / BOM corruption from entering the repository from the start.


# Step 00 — Repository, branch protection and automated review

Date: 2026-11-18
Status: COMPLETE
Classification: For Review
Revision: v2 (FIX applied after initial Step 00 review)

## 1. Scope done
- **Updated repository governance & plan for owner-approved public repository ([ANTIGRAVITY_BUILD_PLAN.md](../../ANTIGRAVITY_BUILD_PLAN.md)):**
  - Updated Section 0 **Rule 12** for `mohokok/ai-engineering-agent` (public with owner approval so GitHub Free repository rulesets can protect `main`; no direct pushes to `main` without explicit owner approval; no edits to `.github/workflows/` or `CLAUDE.md` without explicit owner approval).
  - Added Section 0 **Rule 12a** (Public-repository zero-leak rule: never commit client files, drawings, personal data, keys or tokens, or `/workspaces`, because everything in this repo is publicly visible).
  - Updated **Step 00** tasks, owner actions, acceptance tests, and report requirements to match the updated ruleset and public-repo rules.
- **Recorded architectural decisions ([docs/DECISIONS.md](../DECISIONS.md)):** Added **ADR-005** documenting the public-repository approval, zero-leak policy, and tightened `protect-main` ruleset (`Required approvals: 1`, Repository admin bypass `pull_request` only, deletion and force-push blocks).
- **Verified updated GitHub ruleset (`protect-main`, `id: 27557147`) via API and tested push rejection:** Verified `required_approving_review_count: 1`, `bypass_mode: "pull_request"`, `current_user_can_bypass: "pull_requests_only"`, `deletion`, and `non_fast_forward`; tested both direct push and open-PR-head push to `main` using an empty commit on a throwaway branch (both rejected with `GH013`), then closed the temporary PR without merging and deleted the throwaway branch.
- **Executed live automated PR review tests (`PR #3` and `PR #4`):**
  - Dummy README change PR ([PR #3](https://github.com/mohokok/ai-engineering-agent/pull/3)) triggered `Claude Step Review`, stayed within `--max-budget-usd 2`, and received `Verdict: PASS` from `claude[bot]`.
  - Deliberately planted non-live dummy secret + missing unit test PR ([PR #4](https://github.com/mohokok/ai-engineering-agent/pull/4)) triggered `Claude Step Review` and received `Verdict: BLOCK` flagging both the hardcoded secret and missing test.
  - Both temporary PRs were closed without merging and their branches deleted.
- **Scanned all repository refs and full commit history for secrets.**

## 2. Files created/changed (this PR)
- `ANTIGRAVITY_BUILD_PLAN.md` (updated Rule 12, added Rule 12a, updated Step 00)
- `docs/DECISIONS.md` (added ADR-005)
- `docs/reports/step-00.md` (updated to v2 / COMPLETE with live test evidence)

*(Initial Step 00 baseline files already merged on `main` in [PR #2](https://github.com/mohokok/ai-engineering-agent/pull/2): `CLAUDE.md`, `.gitignore`, `.github/pull_request_template.md`, `.github/workflows/claude-review.yml`, `ANTIGRAVITY_BUILD_PLAN.md`, `docs/DECISIONS.md`, `docs/reports/step-00.md`. Did not modify `.github/` or `CLAUDE.md` in this PR.)*

## 3. Tests run (exact commands + real output)

### A. Verify updated `protect-main` ruleset (`id: 27557147`) via GitHub API
```powershell
$credOut = "protocol=https`nhost=github.com`npath=mohokok/ai-engineering-agent.git`n" | git credential fill
$tok = ($credOut | Select-String '^password=(.+)$').Matches.Groups[1].Value
$h = @{ Authorization = "Bearer $tok"; Accept = "application/vnd.github+json"; "X-GitHub-Api-Version" = "2022-11-28" }
Invoke-RestMethod -Uri "https://api.github.com/repos/mohokok/ai-engineering-agent/rulesets/27557147" -Headers $h | ConvertTo-Json -Depth 6
```
Relevant observed fields:
```json
{
    "id": 27557147,
    "name": "protect-main",
    "enforcement": "active",
    "rules": [
        { "type": "deletion" },
        { "type": "non_fast_forward" },
        {
            "type": "pull_request",
            "parameters": {
                "required_approving_review_count": 1
            }
        }
    ],
    "bypass_actors": [
        {
            "actor_id": 5,
            "actor_type": "RepositoryRole",
            "bypass_mode": "pull_request"
        }
    ],
    "current_user_can_bypass": "pull_requests_only"
}
```

### B. Live Test 1 — Dummy README PR ([PR #3](https://github.com/mohokok/ai-engineering-agent/pull/3))
- Workflow Run: `https://github.com/mohokok/ai-engineering-agent/actions/runs/44330311404` (`status: completed`, `conclusion: success`)
- Created / updated: `2026-11-18T14:59:02Z` → `2026-11-18T14:59:55Z` (**53s** total workflow; Job `134892639575`: `14:59:05Z` → `14:59:54Z` = **49s**; action step: `39778 ms`; Claude model `duration_ms`: `28157`)
- Cost / usage from job log:
  ```text
  "model": "claude-opus-5-5"
  "duration_ms": 28157,
  "num_turns": 4,
  "total_cost_usd": 0.12076830000000001,
  "permission_denials_count": 0
  ```
- Review comment (`claude[bot]`): `https://github.com/mohokok/ai-engineering-agent/pull/3#issuecomment-6982298974` — **`Verdict: PASS`**
- Cleanup: PR #3 closed without merging; branch `step-00-test-dummy-readme-live` deleted locally and remotely.

### C. Live Test 2 — Negative PR with planted dummy secret + missing test ([PR #4](https://github.com/mohokok/ai-engineering-agent/pull/4))
- Planted non-live placeholder in `tmp_step00_secret_check.py`: `API_SECRET_KEY = "FAKE_SECRET_FOR_STEP00_REVIEW_TEST_00000"` with `build_auth_header()` and no unit test.
- Workflow Run: `https://github.com/mohokok/ai-engineering-agent/actions/runs/44331092924` (`status: completed`, `conclusion: success`)
- Created / updated: `2026-11-18T15:03:03Z` → `2026-11-18T15:03:56Z` (**53s** total workflow; Job `134895387035`: `15:03:07Z` → `15:03:56Z` = **49s**; Claude model `duration_ms`: `27410`)
- Cost / usage from job log:
  ```text
  "model": "claude-opus-5-5"
  "duration_ms": 27410,
  "num_turns": 4,
  "total_cost_usd": 0.1128354,
  ```
- Review comment (`claude[bot]`): `https://github.com/mohokok/ai-engineering-agent/pull/4#issuecomment-6982405767` — **`Verdict: BLOCK`** (Finding 1 `[CRITICAL] Hard-coded secret in source` at `tmp_step00_secret_check.py:3`; Finding 2 `[HIGH] New feature has no test` at `tmp_step00_secret_check.py:6-11`).
- Cleanup: PR #4 closed without merging; branch `step-00-test-fake-secret-live` deleted locally and remotely.

### D. Push-rejection tests on `main` (empty commit on throwaway branch, owner-approved)
1. Direct push without an open PR (`git push --no-verify origin throwaway-push-rejection-test:main`):
```text
remote: error: GH013: Repository rule violations found for refs/heads/main.
remote: Review all repository rules at https://github.com/mohokok/ai-engineering-agent/rules?ref=refs%2Fheads%2Fmain
remote:
remote: - Changes must be made through a pull request.
remote:
To https://github.com/mohokok/ai-engineering-agent.git
 ! [remote rejected] throwaway-push-rejection-test -> main (push declined due to repository rule violations)
error: failed to push some refs to 'https://github.com/mohokok/ai-engineering-agent.git'
exit code: 1
```
2. Open-PR-head push (`PR #5`: `https://github.com/mohokok/ai-engineering-agent/pull/5`, `git push --no-verify origin throwaway-push-rejection-test:main`):
```text
Opened PR #5: https://github.com/mohokok/ai-engineering-agent/pull/5
remote: error: GH013: Repository rule violations found for refs/heads/main.
remote: Review all repository rules at https://github.com/mohokok/ai-engineering-agent/rules?ref=refs%2Fheads%2Fmain
remote:
remote: - At least 1 approving review is required by reviewers with write access.
remote:
To https://github.com/mohokok/ai-engineering-agent.git
 ! [remote rejected] throwaway-push-rejection-test -> main (push declined due to repository rule violations)
error: failed to push some refs to 'https://github.com/mohokok/ai-engineering-agent.git'
Open-PR-head push exit code: 1
PR #5 after push attempt -> state=open, merged=False
```
Cleanup: PR #5 closed without merging; `throwaway-push-rejection-test` deleted locally and remotely. Local `.git/hooks/pre-push` also tested directly and exits `1` on `refs/heads/main`.

### E. Full-history secret scan across all refs (branches + `refs/pull/*/head`)
```powershell
git fetch origin "+refs/pull/*/head:refs/remotes/origin/pr/*"
git show-ref
$realRegex = 'github_pat_[A-Za-z0-9_]{10,}|gh[pous]_[A-Za-z0-9]{20,}|sk-ant-[A-Za-z0-9_-]{10,}|AKIA[0-9A-Z]{16}|AIza[0-9A-Za-z_-]{20,}|BEGIN (RSA|OPENSSH|EC|PGP) PRIVATE KEY|Bearer [A-Za-z0-9._-]{20,}'
$commits = git rev-list --all
git grep -n -E $realRegex $commits
git grep -n -E 'FAKE_SECRET_FOR_STEP00' $commits
git grep -n -E 'FAKE_SECRET_FOR_STEP00' main HEAD
```
Output:
```text
=== ALL REFS ===
e4d4942ad220905675f071d26f1d6f02d0b8fc31 refs/heads/main
9e7c24dccb2796c023d2cc9c339335221e48fd61 refs/heads/step-00-fix-public-repo-and-report
e4d4942ad220905675f071d26f1d6f02d0b8fc31 refs/heads/step-00-github-review-pipeline
e4d4942ad220905675f071d26f1d6f02d0b8fc31 refs/remotes/origin/HEAD
e4d4942ad220905675f071d26f1d6f02d0b8fc31 refs/remotes/origin/main
70dec6e35c355cdf9ea870d52f846a55fd78cd71 refs/remotes/origin/pr/1
e4d4942ad220905675f071d26f1d6f02d0b8fc31 refs/remotes/origin/pr/2
a410aa486dcb6c92a4d07f73ee0c7e6e768da0aa refs/remotes/origin/pr/3
c41d41d725aa2f54888496a9c026907efe55b907 refs/remotes/origin/pr/4
9af98133ff1745cc6d0ef31ba84b9f140f3db9a0 refs/remotes/origin/pr/5
e4d4942ad220905675f071d26f1d6f02d0b8fc31 refs/remotes/origin/step-00-github-review-pipeline
=== REAL SECRET SCAN ACROSS ALL REFS (git rev-list --all) ===
0 real secret matches across 8 commits (all branches + refs/pull/*/head)
=== PLANTED TEST-FIXTURE CHECK ACROSS ALL REFS ===
c41d41d725aa2f54888496a9c026907efe55b907:tmp_step00_secret_check.py:3:API_SECRET_KEY = "FAKE_SECRET_FOR_STEP00_REVIEW_TEST_00000"
=== PLANTED TEST-FIXTURE CHECK ON MAIN AND CURRENT BRANCH ===
0 matches on main and HEAD
```

## 4. Acceptance tests
1. **Dummy PR (changing only a README line) triggers the workflow; reviewer posts a comment with a verdict:** **PASS** — [PR #3](https://github.com/mohokok/ai-engineering-agent/pull/3), [Run 44330311404](https://github.com/mohokok/ai-engineering-agent/actions/runs/44330311404) (53s), `claude[bot]` posted `Verdict: PASS` ([comment](https://github.com/mohokok/ai-engineering-agent/pull/3#issuecomment-6982298974)).
2. **PR with a deliberately planted fake secret string and a missing test is flagged:** **PASS** — [PR #4](https://github.com/mohokok/ai-engineering-agent/pull/4), [Run 44331092924](https://github.com/mohokok/ai-engineering-agent/actions/runs/44331092924) (53s), `claude[bot]` posted `Verdict: BLOCK` flagging both the hardcoded fake secret and the missing test ([comment](https://github.com/mohokok/ai-engineering-agent/pull/4#issuecomment-6982405767)).
3. **Run stays within the per-run budget cap:** **PASS** — Workflow sets `--max-turns 10` and `--max-budget-usd 2`; Run `44330311404` cost `$0.1208` (4 turns) and Run `44331092924` cost `$0.1128` (4 turns).
4. **Antigravity cannot push to `main`:** **PASS** — Verified `protect-main` (`approvals=1`, `bypass_mode=pull_request`, `deletion`, `non_fast_forward`); both direct push and open-PR-head push ([PR #5](https://github.com/mohokok/ai-engineering-agent/pull/5)) to `main` failed with `GH013` (exit code 1), and local `.git/hooks/pre-push` blocks `refs/heads/main`.
5. **Repo and its full git history contain no secrets (secret-scan output pasted):** **PASS** — 0 real secret matches across all branches and `refs/pull/1..5/head`; the non-live test string in PR #4 exists only in closed unmerged `refs/pull/4/head` (`c41d41d`) and 0 times on `main` or `HEAD`.

## 5. Decisions made (also in `docs/DECISIONS.md`)
- **ADR-001:** Added `id-token: write`, `issues: write`, `--allowedTools`, and PR context / `gh pr comment` instructions to `.github/workflows/claude-review.yml` per `anthropics/claude-code-action@v1` docs.
- **ADR-002 & ADR-005:** Documented the owner-approved transition to keeping `mohokok/ai-engineering-agent` public on GitHub Free so repository rulesets protect `main` (`Required approvals: 1`, `Repository admin` bypass `pull_request` only, deletion/force-push blocks), paired with Rule 12a (strict zero-leak rule).
- **ADR-003:** Committed `ANTIGRAVITY_BUILD_PLAN.md` so the automated PR reviewer can read step definitions.
- **ADR-004:** Preserved `anthropics/claude-code-action@v1` OIDC default-branch workflow validation.

## 6. Deviations from the plan and why
- Repository is **public** (with explicit owner approval, recorded in Rule 12, Step 00, and ADR-005) instead of private, because GitHub Free requires public visibility for repository rulesets on `main`.
- Added `id-token: write`, `issues: write`, `--allowedTools`, and explicit `gh pr comment` / PR context in `.github/workflows/claude-review.yml` as required by `anthropics/claude-code-action@v1` (ADR-001).

## 7. Known limitations / things not verified
- Without `--model` in `.github/workflows/claude-review.yml`, `claude-code-action@v1` defaulted to `claude-opus-5-5` (at `$0.11–$0.12` per review, within `--max-budget-usd 2`). Not changed because Rule 12 forbids editing `.github/workflows/` without explicit owner approval.
- `.github/workflows/claude-review.yml` triggers only on `pull_request`, not on `issue_comment` (`@claude phase review` in Section 4 item 6).
- GitHub preserves read-only `refs/pull/4/head` (`c41d41d`) on the closed negative-test PR, containing only the non-live placeholder string `FAKE_SECRET_FOR_STEP00_REVIEW_TEST_00000` (0 real credentials).
- Local `README.md` on `main` still contains only `# ai-engineering-agent` (full `README.md` / repo scaffolding is Step 01).

## 8. Questions or items needing the owner
- Review and approve this PR (and wait for the automated Claude review comment on it).
- *(Optional cost optimization)*: If you want automated reviews pinned to Sonnet instead of `claude-opus-5-5`, explicitly approve adding `--model sonnet` to `.github/workflows/claude-review.yml` in a future change.
- *(Optional hardening)*: After merging this PR, you may remove the **Workflows** permission from Antigravity's fine-grained PAT so GitHub itself blocks workflow edits.

## 9. How the owner can see/try it
- Ruleset `protect-main`: `https://github.com/mohokok/ai-engineering-agent/rules/27557147`
- Dummy README PR #3 (`PASS`, `$0.1208`): `https://github.com/mohokok/ai-engineering-agent/pull/3` (`https://github.com/mohokok/ai-engineering-agent/actions/runs/44330311404`)
- Negative fake-secret + missing-test PR #4 (`BLOCK`, `$0.1128`): `https://github.com/mohokok/ai-engineering-agent/pull/4` (`https://github.com/mohokok/ai-engineering-agent/actions/runs/44331092924`)
- Open-PR-head push rejection PR #5 (`closed` unmerged): `https://github.com/mohokok/ai-engineering-agent/pull/5`

## 10. Ready for next step?
**Yes** (pending owner approval and merge of this PR) — All Step 00 acceptance tests now pass with real evidence. Do not start Step 01 until the owner reviews, merges this PR, and replies `PASS step 00`.

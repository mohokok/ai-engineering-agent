# Step 00 — Repository, branch protection and automated review

Date: 2026-11-18
Status: PARTIAL
Classification: For Review
Revision: v1

## 1. Scope done
- **Initialised the repository locally and connected remote:** Initialised `git` on branch `main` tracking `origin/main` (`https://github.com/mohokok/ai-engineering-agent.git`), stored the fine-grained PAT in Windows Credential Manager scoped via `credential.https://github.com.useHttpPath=true`, and branched `step-00-github-review-pipeline` from `main` without pushing to `main`.
- **Added repository governance and PR review files:**
  - `CLAUDE.md` (verbatim from Appendix A of `ANTIGRAVITY_BUILD_PLAN.md`).
  - `.github/workflows/claude-review.yml` (based on Appendix B, updated after verifying `anthropics/claude-code-action@v1` requirements).
  - `.github/pull_request_template.md` (verbatim from Appendix C).
  - `.gitignore` (excluding `/workspaces/`, `workspaces/`, `client_data/`, `.env`, `.env.*`, `*.dwg`, `*.rvt`, `*.rfa`, `*.rte`, keys/DBs, and standard Python/Node/OS artifacts).
  - `ANTIGRAVITY_BUILD_PLAN.md` (committed so the GitHub Actions reviewer can read step definitions).
  - `docs/DECISIONS.md` (recording ADR-001 through ADR-004).
- **Verified `anthropics/claude-code-action@v1` documentation and tested workflow trigger:** Recorded action input/permission differences in `docs/DECISIONS.md` (ADR-001) and opened a temporary dummy PR ([PR #1](https://github.com/mohokok/ai-engineering-agent/pull/1)) changing only `README.md`, then closed it without merging and deleted the temporary branch.
- **Checked branch protection on `main`:** Queried GitHub branch and ruleset APIs and installed a local `.git/hooks/pre-push` guard blocking pushes to `refs/heads/main`.

## 2. Files created/changed
- `ANTIGRAVITY_BUILD_PLAN.md`
- `CLAUDE.md`
- `.gitignore`
- `.github/pull_request_template.md`
- `.github/workflows/claude-review.yml`
- `docs/DECISIONS.md`
- `docs/reports/step-00.md`

*(Local untracked Git hook also configured in `.git/hooks/pre-push`.)*

## 3. Tests run (exact commands + real output)

### A. Branch protection & ruleset API check on `main`
```powershell
$credOut = "protocol=https`nhost=github.com`npath=mohokok/ai-engineering-agent.git`n" | git credential fill
$tok = ($credOut | Select-String '^password=(.+)$').Matches.Groups[1].Value
$h = @{ Authorization = "Bearer $tok"; Accept = "application/vnd.github+json"; "X-GitHub-Api-Version" = "2022-11-28" }
$br = Invoke-RestMethod -Uri "https://api.github.com/repos/mohokok/ai-engineering-agent/branches/main" -Headers $h
[pscustomobject]@{ name = $br.name; sha = $br.commit.sha; protected = $br.protected } | ConvertTo-Json
Invoke-RestMethod -Uri "https://api.github.com/repos/mohokok/ai-engineering-agent/rules/branches/main" -Headers $h | ConvertTo-Json -Depth 5
```
Output:
```text
{
    "name":  "main",
    "sha":  "02d2313e86779fef2f9452d9729244ca145cd306",
    "protected":  false
}
Invoke-RestMethod : {"message":"Upgrade to GitHub Pro or make this repository public to enable this feature.","documentation_url":"https://docs.github.com/rest/repos/rules#get-rules-for-a-branch","status":"403"}
```

### B. Dummy PR workflow trigger test (`PR #1`) and Actions job inspection
Opened temporary PR `step-00-test-dummy-readme` -> `step-00-github-review-pipeline` changing only `README.md`, inspected workflow run `44326920938` and job `134880580302` logs, then closed PR #1 without merging and deleted `step-00-test-dummy-readme`:
```text
PR #1: https://github.com/mohokok/ai-engineering-agent/pull/1 (state: closed)
Workflow Run: https://github.com/mohokok/ai-engineering-agent/actions/runs/44326920938
  name: Claude Step Review
  event: pull_request
  status: completed
  conclusion: success
  created_at: 2026-11-18T14:40:55Z
  updated_at: 2026-11-18T14:41:13Z (total duration: 18s; action step: 3139 ms)
  comments_count: 0
  reviews: 0
```
Relevant excerpt from Actions job `134880580302` log:
```text
2026-11-18T14:41:07.6299958Z Auto-detected mode: agent for event: pull_request
2026-11-18T14:41:07.6319009Z Requesting OIDC token...
2026-11-18T14:41:07.7335703Z OIDC token successfully obtained
2026-11-18T14:41:07.7336584Z Exchanging OIDC token for app token...
2026-11-18T14:41:10.3370784Z ##[warning]Skipping action due to workflow validation: Workflow validation failed. The workflow file must exist and have identical content to the version on the repository's default branch. If you're seeing this on a PR when you first add a code review workflow file to your repository, this is normal and you should ignore this error.
2026-11-18T14:41:10.3378117Z Action skipped due to workflow validation error. This is expected when adding Claude Code workflows to new repositories or on PRs with workflow changes. If you're seeing this, your workflow will begin working once you merge your PR.
2026-11-18T14:41:10.3380424Z Exiting due to workflow validation skip
```

### C. Local `pre-push` hook, secret scan, and `.gitignore` verification
```powershell
echo "refs/heads/step-00-github-review-pipeline 0000000 refs/heads/main 0000000" | & "C:\Program Files\Git\bin\sh.exe" .git/hooks/pre-push
"pre-push exit code: $LASTEXITCODE"
$patterns = 'github_pat_|ghp_[A-Za-z0-9]{20,}|gho_[A-Za-z0-9]{20,}|sk-ant-[A-Za-z0-9_-]{10,}|AKIA[0-9A-Z]{16}|AIza[0-9A-Za-z_-]{20,}|BEGIN (RSA|OPENSSH|EC|PGP) PRIVATE KEY'
$hits = git grep -n -E $patterns; if ($hits) { $hits } else { "git grep (HEAD): 0 secret matches" }
$revHits = git log --all -p -S "github_pat_" --oneline; if ($revHits) { $revHits } else { "git log --all (-S github_pat_): 0 matches" }
$skHits = git log --all -p -S "sk-ant-" --oneline; if ($skHits) { $skHits } else { "git log --all (-S sk-ant-): 0 matches" }
git check-ignore -v workspaces/test.txt .env test.dwg test.rvt client_data/doc.pdf
```
Output:
```text
BLOCKED by local pre-push hook: direct pushes to refs/heads/main are prohibited (use a PR).
pre-push exit code: 1
git grep (HEAD): 0 secret matches
git log --all (-S github_pat_): 0 matches
git log --all (-S sk-ant-): 0 matches
.gitignore:3:workspaces/	workspaces/test.txt
.gitignore:11:.env	.env
.gitignore:5:*.dwg	test.dwg
.gitignore:6:*.rvt	test.rvt
.gitignore:4:client_data/	client_data/doc.pdf
```
Local `.git/config` check (`git config --local --list`) also confirmed `remote.origin.url=https://github.com/mohokok/ai-engineering-agent.git` with no embedded PAT (`credential.https://github.com.usehttppath=true`).

## 4. Acceptance tests
1. **Dummy PR (changing only a README line) triggers the workflow; reviewer posts a comment with a verdict:** **PARTIAL / BLOCKED PRE-MERGE** — [PR #1](https://github.com/mohokok/ai-engineering-agent/pull/1) triggered `Claude Step Review` ([Run 44326920938](https://github.com/mohokok/ai-engineering-agent/actions/runs/44326920938), 18s), and OIDC succeeded, but `anthropics/claude-code-action@v1` skipped posting a comment because `.github/workflows/claude-review.yml` is not yet on `main` (pre-merge workflow validation check).
2. **PR with a deliberately planted fake secret string and a missing test is flagged:** **NOT RUN / BLOCKED PRE-MERGE** — Deferred until `.github/workflows/claude-review.yml` is merged onto `main`, because the action skips execution on all PRs while the workflow is absent from the default branch.
3. **Run stays within the per-run budget cap:** **PARTIAL** — Workflow sets `--max-turns 10` and `--max-budget-usd 2`. Run `44326920938` skipped before making any Anthropic API calls (0 API tokens / \$0 estimated); live API budget/token reporting will be verified once `claude-review.yml` is on `main`.
4. **Antigravity cannot push to `main`:** **FAIL (server-side) / MITIGATED LOCALLY** — GitHub reports `protected: false` on `main` and HTTP 403 (`Upgrade to GitHub Pro or make this repository public to enable this feature`) on branch rules. No push to `origin/main` was attempted; a local `.git/hooks/pre-push` hook rejects `refs/heads/main` (exit code 1).
5. **Repo contains no secrets:** **PASS** — `git grep` and `git log --all` returned 0 secret matches; `.git/config` stores no token.

## 5. Decisions made (also in `docs/DECISIONS.md`)
- **ADR-001:** Added `id-token: write`, `issues: write`, `--allowedTools`, and `REPO`/`PR NUMBER`/`gh pr comment` instructions to `.github/workflows/claude-review.yml` per `anthropics/claude-code-action@v1` documentation.
- **ADR-002:** Documented GitHub Free private-repo branch protection limitation (`403`) and installed local `.git/hooks/pre-push` instead of making the repo public or buying a paid plan without owner approval.
- **ADR-003:** Committed `ANTIGRAVITY_BUILD_PLAN.md` so the GitHub Actions reviewer can inspect step specifications.
- **ADR-004:** Kept OIDC workflow validation intact (did not bypass with `github_token: ${{ secrets.GITHUB_TOKEN }}`), requiring this bootstrap PR to land on `main` before live reviewer comment tests can execute.

## 6. Deviations from the plan and why
1. **Workflow additions (`id-token: write`, `issues: write`, `--allowedTools`, PR metadata in `prompt`):** Required by `anthropics/claude-code-action@v1` (plain-text `prompt` mode starts with no tools unless allowlisted, and OIDC requires `id-token: write`).
2. **No server-side branch protection on `main`:** GitHub Free does not support branch protection/Rulesets on private repositories (`403` error). Enforced locally via `.git/hooks/pre-push` until owner either upgrades to GitHub Pro or approves the deviation.
3. **Bootstrap PR must be merged before live Claude review tests can run:** `anthropics/claude-code-action@v1` refuses to run until `.github/workflows/claude-review.yml` matches the default branch (`main`).

## 7. Known limitations / things not verified
- Live Claude review execution (verifying `ANTHROPIC_API_KEY`, Claude GitHub App PR commenting, `--max-budget-usd 2` spend/duration, dummy PR verdict comment, and planted fake-secret + missing-test flagging) has **not** run yet because `claude-review.yml` is not on `main`.
- Server-side rejection of a push to `main` is **not** verified because branch protection is unavailable on GitHub Free private repos.
- `.github/workflows/claude-review.yml` triggers only on `pull_request`; Section 4 item 6 (`@claude phase review` on PR comments) would require an `issue_comment` trigger later if desired.

## 8. Questions or items needing the owner
1. **Branch protection decision:** Do you want to upgrade to **GitHub Pro** and enable branch protection on `main` (with **"Do not allow bypassing the above settings"**), or approve proceeding on **GitHub Free** with the local `pre-push` guard and PR-only discipline?
2. **Bootstrap merge before post-merge Step 00 verification:** Please review the files in this PR (`CLAUDE.md`, `.github/workflows/claude-review.yml`, `.github/pull_request_template.md`, `.gitignore`, `docs/DECISIONS.md`). Notice that on this PR, GitHub Actions will skip Claude review because `claude-review.yml` is not yet on `main`. Once you confirm `ANTHROPIC_API_KEY` + Claude GitHub App (`https://github.com/apps/claude`) are configured and **merge this PR to `main`**, reply to let me run the post-merge dummy PR + fake-secret PR acceptance tests (before replying `PASS step 00` for Step 01).
3. *(Optional security hardening after Step 00)*: Once `.github/workflows/claude-review.yml` is merged to `main`, you may remove the **Workflows** permission from Antigravity's fine-grained PAT so GitHub itself enforces Section 0 Rule 12.

## 9. How the owner can see/try it
- Closed dummy PR #1: `https://github.com/mohokok/ai-engineering-agent/pull/1`
- Workflow run #44326920938: `https://github.com/mohokok/ai-engineering-agent/actions/runs/44326920938`
- Step 00 PR: *(link added in the PR description upon creation)*

## 10. Ready for next step?
**No** — `Status: PARTIAL`. Step 01 must not start until:
1. This bootstrap PR is reviewed and merged to `main` so `.github/workflows/claude-review.yml` is active on the default branch.
2. The dummy README PR, fake-secret + missing-test PR, and budget-cap tests pass on live runs (and branch protection is either enabled via GitHub Pro or formally waived).
3. The owner replies `PASS step 00`.

# Quarantine Approve Workflow Test Checklist

This checklist documents the manual verification procedure for `quarantine-approve.yml` triggered by the `approve-quarantine` label.

| Step # | Test Action | Expected Result | Actual Result | Status |
| :--- | :--- | :--- | :--- | :--- |
| **1** | Apply label `approve-quarantine` to an open test PR with flaky failures | • Workflow `quarantine-approve` triggers.<br>• Verifies actor has repo write permissions.<br>• Filters out any real bugs (`test_case_22`–`27`).<br>• Appends only flaky test IDs to `quarantine.json`.<br>• A bot commit `chore(quarantine): ... [skip ci]` appears directly on the PR head branch. | | [ ] Pending Test |
| **2** | Remove label `approve-quarantine` and re-apply it to the same PR | • Workflow re-executes.<br>• Idempotency check detects existing test IDs in `quarantine.json`.<br>• `added_count == 0`.<br>• No duplicate entries added; no redundant empty commits pushed. | | [ ] Pending Test |
| **3** | Inspect PR merge readiness and status check behavior | • Check GitHub PR UI status checks after the bot commit.<br>• Verify whether the commit pushed by `GITHUB_TOKEN` left required checks in a pending/blocking state or if checks pass/merge is unblocked. | | [ ] Pending Test |
| **4** | Apply label `approve-quarantine` as a contributor without write/admin permissions (or simulate non-maintainer) | • Permission check detects user lacks write/maintain permissions.<br>• Workflow comments on PR: `⚠️ Quarantine Authorization Failed: User @... does not have write permissions...`<br>• Workflow exits cleanly with code 0 without modifying `quarantine.json` or pushing commits. | | [ ] Pending Test |

---

### Test Environment Prerequisites
1. Base branch: `develop`
2. PR Branch: internal same-repo branch with:
   - Planted failure triggering `triage.yml` sticky comment.
   - `.github/workflows/quarantine-approve.yml` present.
3. Label: `approve-quarantine` created in repository settings.

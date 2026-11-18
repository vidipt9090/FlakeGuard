# FlakeGuard Cross-Repository Reusable Workflow Setup Guide

This guide details the exact prerequisites, repository visibility settings, permissions, and secrets required to call the reusable FlakeGuard scan workflow (`vidipt9090/FlakeGuard/.github/workflows/scan.yml`) from target repositories like `vidipt9090/flakeguard-demo`.

---

## 1. FlakeGuard Upstream Repo Visibility & Access
For another repository to call `.github/workflows/scan.yml@main`:

1. **If FlakeGuard is Public**:
   - No special configuration is required; reusable workflows in public repositories are globally accessible to all GitHub workflows.
2. **If FlakeGuard is Private or Internal**:
   - Go to `vidipt9090/FlakeGuard` on GitHub.
   - Click **Settings** -> **Actions** -> **General**.
   - Under **Access**, select:
     - **Accessible from repositories in the 'vidipt9090' organization / user account**.
   - Click **Save**.

---

## 2. Caller Repo Permissions (e.g. in `flakeguard-demo`)
The caller repo workflow must have permissions to post PR triage comments and upload artifacts.

1. In the target repository (e.g. `vidipt9090/flakeguard-demo`):
   - Navigate to **Settings** -> **Actions** -> **General**.
   - Under **Workflow permissions**:
     - Select **Read and write permissions** (required for the bot to post PR triage comments and update statuses).
     - Check the box **Allow GitHub Actions to create and approve pull requests**.
   - Click **Save**.

---

## 3. Caller Secrets & Authentication
- **`GITHUB_TOKEN`**: Automatically provided to GitHub Actions runs. When the caller workflow sets `secrets: inherit`, the token is forwarded to the reusable workflow with caller repo permissions.
- **LLM API Keys (Optional)**:
  - If using live LLM triage (e.g. Gemini or OpenAI), add `GEMINI_API_KEY` or `OPENAI_API_KEY` under:
    - **Settings** -> **Secrets and variables** -> **Actions** -> **Repository secrets**.
  - If omitted, FlakeGuard automatically falls back to empirical heuristic triage without failing.

---

## 4. How to Deploy the Caller in `flakeguard-demo`
1. In `vidipt9090/flakeguard-demo`, create the file:
   `.github/workflows/flakeguard.yml`
2. Paste the contents of `docs/eval3/flakeguard-demo-caller.yml`:
   ```yaml
   name: FlakeGuard CI Scan

   on:
     pull_request:
       branches: [main, master, develop]
     workflow_dispatch:
       inputs:
         n_runs:
           description: "Number of shuffled perturbation runs"
           required: false
           default: 3
           type: number
         flakeguard_ref:
           description: "FlakeGuard branch or ref to invoke (use 'develop' until develop->main is merged)"
           required: true
           default: "develop"
           type: string

   concurrency:
     group: flakeguard-${{ github.workflow }}-${{ github.event.pull_request.number || github.ref }}
     cancel-in-progress: true

   jobs:
     call-flakeguard-scan:
       name: Run FlakeGuard Reusable Scan
       uses: vidipt9090/FlakeGuard/.github/workflows/scan.yml@develop
       with:
         repo_url: ${{ github.repository }}
         n_runs: ${{ inputs.n_runs || 3 }}
         flakeguard_ref: ${{ inputs.flakeguard_ref || 'develop' }}
       secrets: inherit
   ```
3. Commit and push.
4. On any pull request or manual dispatch, FlakeGuard will check out the target repo, run the perturbation matrix, upload the 4-file artifact bundle (`events.jsonl`, `junit.xml`, `findings.json`, `tree.json`), and post the sticky triage comment.

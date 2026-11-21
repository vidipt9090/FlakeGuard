"""Properties of .github/workflows/scan.yml that the console and the honesty rules depend on."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

WORKFLOW = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "scan.yml"
STAGE_IDS = {"checkout", "install", "baseline", "shuffled", "isolated", "bisection", "retrieval", "verdict", "pr-comment"}


def load() -> dict:
    data = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    data["on"] = data.pop(True)  # YAML reads the key `on` as the boolean True
    return data


def step_names(job: dict) -> list[str]:
    return [s["name"] for s in job["steps"] if "name" in s]


def test_is_reusable_and_dispatchable():
    triggers = load()["on"]
    assert {"workflow_call", "workflow_dispatch"} <= set(triggers)
    for event in ("workflow_call", "workflow_dispatch"):
        assert {"n_runs", "seed_start", "mode", "pr_number", "flakeguard_ref"} <= set(triggers[event]["inputs"])


def test_the_engine_commit_must_be_named_by_the_caller():
    triggers = load()["on"]
    for event in ("workflow_call", "workflow_dispatch"):
        assert triggers[event]["inputs"]["flakeguard_ref"]["required"] is True
    assert "job_workflow_sha" not in WORKFLOW.read_text(encoding="utf-8").replace("job_workflow_sha` is", "")


def test_step_names_are_the_stage_ids():
    jobs = load()["jobs"]
    assert {"checkout", "install", "baseline"} <= set(step_names(jobs["scan"]))
    assert {"isolated", "bisection", "retrieval", "verdict"} <= set(step_names(jobs["analyze"]))
    assert "pr-comment" in step_names(jobs["comment"])
    for job in ("scan", "analyze", "comment"):
        for name in step_names(jobs[job]):
            if name in STAGE_IDS:
                assert name == name.lower() and " " not in name


def test_one_matrix_job_per_shuffled_seed():
    job = load()["jobs"]["shuffled"]
    assert job["strategy"]["fail-fast"] is False
    assert "fromJSON(needs.plan.outputs.matrix)" in job["strategy"]["matrix"]
    assert job["name"] == "shuffled (seed ${{ matrix.seed }})"
    uploads = [s for s in job["steps"] if s.get("uses", "").startswith("actions/upload-artifact")]
    assert uploads and uploads[0]["with"]["name"] == "junit-shuffled-${{ matrix.i }}"


def test_one_scan_per_pull_request_and_a_new_push_cancels_the_old_one():
    c = load()["concurrency"]
    assert c["cancel-in-progress"] is True
    assert "github.event.pull_request.number" in c["group"]


def test_permissions_are_limited_to_what_the_comment_needs():
    wf = load()
    assert wf["permissions"] == {"contents": "read"}
    for name, job in wf["jobs"].items():
        if name == "comment":
            assert job["permissions"] == {"contents": "read", "pull-requests": "write"}
        else:
            assert "permissions" not in job, f"{name} must inherit the read-only default"


def test_failures_are_not_masked():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "|| true" not in text and "continue-on-error" not in text
    # pytest exit code 1 (tests failed) is the only exit code accepted, and it is explicit
    assert text.count('if [ "$code" -gt 1 ]') == 2


def test_no_expression_is_interpolated_into_shell_scripts():
    """Values reach scripts through env, not by pasting ${{ }} into the script text."""
    for name, job in load()["jobs"].items():
        for step in job["steps"]:
            run = step.get("run", "")
            assert "${{" not in run, f"{name}/{step.get('name')} interpolates an expression into its script"


def test_comment_job_posts_a_did_not_finish_notice_when_analysis_did_not_succeed():
    comment = load()["jobs"]["comment"]
    assert comment["if"].startswith("${{ !cancelled()")
    script = next(s for s in comment["steps"] if s["name"] == "pr-comment")["run"]
    assert "did_not_finish" in script and 'ANALYZE_RESULT" = "success"' in script
    download = next(s for s in comment["steps"] if s["name"] == "download")
    assert "needs.analyze.result == 'success'" in download["if"]


def test_analyze_only_runs_when_the_scan_and_every_seed_job_finished():
    analyze = load()["jobs"]["analyze"]
    assert re.search(r"needs\.scan\.result == 'success'", analyze["if"])
    assert re.search(r"needs\.shuffled\.result == 'success'", analyze["if"])

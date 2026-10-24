"""The CI/CD page must describe the pipeline the repository actually has.

The page carries its own list of stages so it can group them and explain each
one. That list is a second copy of the truth, and a second copy drifts: the
`deploy` job existed in the workflow for a while before the page knew about
it, so the page showed a pipeline that was missing a stage.

These tests tie the two together.
"""

import pytest

yaml = pytest.importorskip("yaml")
pytest.importorskip("streamlit", reason="pages_cicd imports streamlit")

from flakeguard.app import pages_cicd  # noqa: E402

WORKFLOW = pages_cicd.WORKFLOWS / "cicd.yml"


@pytest.fixture(scope="module")
def workflow():
    assert WORKFLOW.is_file(), f"{WORKFLOW} is missing"
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def test_the_page_lists_exactly_the_workflow_jobs(workflow):
    declared = {job for job, _, _, _ in pages_cicd.STAGES}
    actual = set(workflow["jobs"])
    assert declared == actual, (
        f"page-only: {sorted(declared - actual)}, "
        f"workflow-only: {sorted(actual - declared)}"
    )


def test_every_stage_is_on_a_known_side(workflow):
    for job, _, _, side in pages_cicd.STAGES:
        assert side in pages_cicd.SIDE_LABEL, f"{job} has unknown side {side!r}"


def test_exactly_one_stage_is_the_gate():
    gates = [job for job, _, _, side in pages_cicd.STAGES if side == "gate"]
    assert gates == ["gate"], f"expected one gate stage, got {gates}"


def test_delivery_stages_all_depend_on_the_gate(workflow):
    """The page claims delivery is unreachable without the gate. Check it."""
    jobs = workflow["jobs"]

    def reaches_gate(name, seen=None):
        seen = seen or set()
        if name in seen:
            return False
        seen.add(name)
        needs = jobs[name].get("needs", [])
        needs = [needs] if isinstance(needs, str) else needs
        return "gate" in needs or any(reaches_gate(n, seen) for n in needs)

    for job, _, _, side in pages_cicd.STAGES:
        if side == "cd":
            assert reaches_gate(job), (
                f"{job} is shown as a delivery stage but does not depend on the gate"
            )


def test_no_job_claims_a_protected_environment_unconditionally(workflow):
    """A declared environment is claimed when the job starts, and the Pages
    environment is branch-protected, so an unconditional claim blocks PRs."""
    for name, job in workflow["jobs"].items():
        if job.get("environment"):
            assert job.get("if"), f"{name} claims an environment with no condition"


def test_ci_stages_come_before_the_gate(workflow):
    """Nothing on the testing side may depend on the gate."""
    jobs = workflow["jobs"]
    for job, _, _, side in pages_cicd.STAGES:
        if side == "ci":
            needs = jobs[job].get("needs", [])
            needs = [needs] if isinstance(needs, str) else needs
            assert "gate" not in needs, f"{job} is CI but waits on the gate"

"""Comprehensive unit tests for the FlakeGuard runner, sandbox, and event log."""

from pathlib import Path

from flakeguard.cli import build_parser
from flakeguard.runner.detector import detect_repository
from flakeguard.runner.events import Event, EventLogger
from flakeguard.runner.matrix import parse_junit_xml
from flakeguard.runner.orchestrator import ScanConfig, scan
from flakeguard.runner.sandbox import LocalProcessSandbox

# ---------------------------------------------------------------------------
# Events and EventLogger
# ---------------------------------------------------------------------------


def test_event_schema_contract():
    """Verify Event schema fields and serialization."""
    event = Event(
        run_id="run_123",
        stage="run",
        type="progress",
        test_id="tests/test_a.py::test_1",
        data={"mode": "shuffled", "iteration": 2},
    )
    dumped = event.model_dump()
    assert dumped["run_id"] == "run_123"
    assert dumped["stage"] == "run"
    assert dumped["type"] == "progress"
    assert dumped["test_id"] == "tests/test_a.py::test_1"
    assert dumped["data"]["iteration"] == 2
    assert "ts" in dumped


def test_event_logger_roundtrip(tmp_path):
    """Verify EventLogger writes JSONL lines and read_events yields valid Events."""
    log_file = tmp_path / "test_run.jsonl"
    logger = EventLogger("test_run", output_path=log_file)

    logger.log("ingest", "started", data={"target": "repo"})
    logger.log("run", "progress", test_id="t1", data={"mode": "baseline"})
    logger.log("run", "result", data={"flaky_count": 0})

    events = list(logger.read_events())
    assert len(events) == 3
    assert events[0].stage == "ingest"
    assert events[0].type == "started"
    assert events[1].stage == "run"
    assert events[1].test_id == "t1"
    assert events[2].stage == "run"
    assert events[2].data["flaky_count"] == 0


# ---------------------------------------------------------------------------
# Framework Detection
# ---------------------------------------------------------------------------


def test_detect_repository_synthetic():
    """Verify detection finds pytest in synthetic project."""
    repo = Path(__file__).parent.parent / "synthetic"
    info = detect_repository(repo)
    assert info.can_build is True
    assert info.framework == "pytest"
    assert info.test_files_count >= 3


def test_detect_repository_empty_directory(tmp_path):
    """Verify empty directory yields a clear 'could not build' outcome."""
    info = detect_repository(tmp_path)
    assert info.can_build is False
    assert "could not build" in (info.reason or "")


def test_detect_repository_nonexistent_directory(tmp_path):
    """Verify non-existent directory yields 'could not build'."""
    missing = tmp_path / "does_not_exist"
    info = detect_repository(missing)
    assert info.can_build is False
    assert "could not build" in (info.reason or "")


# ---------------------------------------------------------------------------
# Sandbox Execution
# ---------------------------------------------------------------------------


def test_local_process_sandbox_success():
    """Verify LocalProcessSandbox executes simple command successfully."""
    sandbox = LocalProcessSandbox(default_timeout=10.0)
    res = sandbox.run(["python", "-c", "print('sandbox_ok')"])
    assert res.exit_code == 0
    assert "sandbox_ok" in res.stdout
    assert not res.timed_out


def test_local_process_sandbox_timeout():
    """Verify LocalProcessSandbox catches timeout and marks timed_out=True."""
    sandbox = LocalProcessSandbox(default_timeout=0.2)
    res = sandbox.run(["python", "-c", "import time; time.sleep(1.0)"])
    assert res.timed_out is True
    assert res.exit_code == 124


def test_local_process_sandbox_env_isolation():
    """Verify environment variables are injected into sandbox command."""
    sandbox = LocalProcessSandbox(default_timeout=10.0)
    res = sandbox.run(
        ["python", "-c", "import os; print(os.environ.get('FLAKEGUARD_TEST_VAR'))"],
        env={"FLAKEGUARD_TEST_VAR": "injected_val"},
    )
    assert res.exit_code == 0
    assert "injected_val" in res.stdout


# ---------------------------------------------------------------------------
# JUnit XML Parsing
# ---------------------------------------------------------------------------


def test_parse_junit_xml_extracts_outcomes(tmp_path):
    """Verify parse_junit_xml parses pass, fail, skip, and error outcomes."""
    xml_content = """<?xml version="1.0" encoding="utf-8"?>
    <testsuites>
      <testsuite name="pytest" tests="4" failures="1" errors="1" skipped="1">
        <testcase classname="tests.test_a" name="test_pass" time="0.01"/>
        <testcase classname="tests.test_a" name="test_fail" time="0.05">
          <failure message="AssertionError: failed">assert 1 == 2</failure>
        </testcase>
        <testcase classname="tests.test_a" name="test_skip" time="0.00">
          <skipped message="reason: skipped"/>
        </testcase>
        <testcase classname="tests.test_a" name="test_err" time="0.02">
          <error message="RuntimeError: boom">error text</error>
        </testcase>
      </testsuite>
    </testsuites>
    """
    junit_file = tmp_path / "junit_sample.xml"
    junit_file.write_text(xml_content, encoding="utf-8")

    outcomes = parse_junit_xml(junit_file)
    assert len(outcomes) == 4

    out_map = {o.test_id: o for o in outcomes}
    assert out_map["tests.test_a::test_pass"].outcome == "PASS"
    assert out_map["tests.test_a::test_fail"].outcome == "FAIL"
    assert "AssertionError" in out_map["tests.test_a::test_fail"].message
    assert out_map["tests.test_a::test_skip"].outcome == "SKIP"
    assert out_map["tests.test_a::test_err"].outcome == "ERROR"


# ---------------------------------------------------------------------------
# CLI Argument Parsing
# ---------------------------------------------------------------------------


def test_cli_parser_defaults():
    """Verify CLI argument defaults for scan command."""
    parser = build_parser()
    args = parser.parse_args(["scan", "path/to/repo"])
    assert args.command == "scan"
    assert args.target == "path/to/repo"
    assert args.shuffled_n == 5
    assert args.timeout == 60.0
    assert args.docker is False


def test_cli_parser_custom_options():
    """Verify custom CLI options are parsed correctly."""
    parser = build_parser()
    args = parser.parse_args([
        "scan",
        "https://github.com/example/repo.git",
        "--sha",
        "abc1234",
        "--shuffled-n",
        "10",
        "--timeout",
        "45.0",
        "--docker",
        "--output-events",
        "custom_events.jsonl",
        "--output-artifacts",
        "custom_art",
    ])
    assert args.target == "https://github.com/example/repo.git"
    assert args.sha == "abc1234"
    assert args.shuffled_n == 10
    assert args.timeout == 45.0
    assert args.docker is True
    assert args.output_events == "custom_events.jsonl"
    assert args.output_artifacts == "custom_art"


# ---------------------------------------------------------------------------
# End-to-End Orchestrator Scan
# ---------------------------------------------------------------------------


def test_orchestrator_scan_could_not_build(tmp_path):
    """Verify orchestrator fails with clear 'could not build' outcome on empty dir."""
    config = ScanConfig(
        target=str(tmp_path),
        output_events=str(tmp_path / "events.jsonl"),
    )
    result = scan(config)
    assert result.success is False
    assert result.outcome == "could not build"
    assert "could not build" in (result.reason or "")

    # Event log should contain the failure
    logger = EventLogger(result.run_id, output_path=result.event_log_path)
    events = list(logger.read_events())
    assert any(e.type == "error" and e.data.get("outcome") == "could not build" for e in events)

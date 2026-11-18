"""Recorded runs on disk: ``recorded/<run-id>/{run,findings,tree}.json``.

The console API serves these files. Each file is validated against the contract models when
it is read, so a file that no longer matches the contract fails loudly instead of rendering
something wrong.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from pydantic import TypeAdapter

from flakeguard.console import models as m

REPO_ROOT = Path(__file__).resolve().parents[2]
RECORDED_DIR = REPO_ROOT / "recorded"
FINDING_SEPARATOR = "_"  # finding ids look like run-2026-11-18-001_finding-1

_RUN_ID = re.compile(r"^run-\d{4}-\d{2}-\d{2}-\d{3}$")
_FINDINGS = TypeAdapter(list[m.Finding])


class NotFound(Exception):
    """Raised with a message meant to be shown to the person using the console."""


class RecordedStore:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root if root is not None else RECORDED_DIR

    def run_ids(self) -> list[str]:
        if not self.root.is_dir():
            return []
        return sorted(p.name for p in self.root.iterdir() if p.is_dir() and _RUN_ID.match(p.name))

    def latest_id(self) -> str | None:
        ids = self.run_ids()
        return ids[-1] if ids else None

    def _dir(self, run_id: str) -> Path:
        if not _RUN_ID.match(run_id) or not (self.root / run_id).is_dir():
            raise NotFound(f"There is no run called {run_id}.")
        return self.root / run_id

    def _read(self, run_id: str, name: str) -> str:
        path = self._dir(run_id) / name
        if not path.is_file():
            raise NotFound(f"Run {run_id} has no {name}.")
        return path.read_text(encoding="utf-8")

    def run(self, run_id: str) -> m.RunStatus:
        return m.RunStatus.model_validate_json(self._read(run_id, "run.json"))

    def findings(self, run_id: str) -> list[m.Finding]:
        return _FINDINGS.validate_json(self._read(run_id, "findings.json"))

    def tree(self, run_id: str) -> m.TreeData:
        return m.TreeData.model_validate_json(self._read(run_id, "tree.json"))

    def no_tests(self, run_id: str) -> m.NoTestsPlan:
        """The no-tests plan if one was recorded; otherwise an empty plan (nothing was run)."""
        path = self._dir(run_id) / "no_tests.json"
        if path.is_file():
            return m.NoTestsPlan.model_validate_json(path.read_text(encoding="utf-8"))
        return m.NoTestsPlan(
            repo=self.run(run_id).target,
            steps=[
                m.NoTestsStep(name=n, state="pending")
                for n in ("Find risky spots", "Write tests", "Check them", "Open PR on your fork")
            ],
            spots=[], example=None, checks=[],
        )

    def target_path(self, run_id: str) -> Path | None:
        """Repository the run scanned, if recorded in meta.json and still on disk."""
        meta = self._dir(run_id) / "meta.json"
        if not meta.is_file():
            return None
        rel = json.loads(meta.read_text(encoding="utf-8")).get("target")
        path = (REPO_ROOT / rel).resolve() if rel else None
        return path if path and path.is_dir() else None

    def find_finding(self, finding_id: str) -> tuple[str, m.Finding]:
        run_id, sep, _ = finding_id.partition(FINDING_SEPARATOR)
        if not sep:
            raise NotFound(f"There is no finding called {finding_id}.")
        for f in self.findings(run_id):
            if f.id == finding_id:
                return run_id, f
        raise NotFound(f"There is no finding called {finding_id}.")

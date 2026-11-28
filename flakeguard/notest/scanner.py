"""Static AST scanner detecting risky sites susceptible to test flakiness."""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

RiskCategory = Literal["sleep", "random", "now", "globals", "threads", "network"]


@dataclass(frozen=True)
class RiskySite:
    """A detected code location susceptible to non-determinism or flakiness."""

    file_path: str
    line_number: int
    function_name: str
    risk_category: RiskCategory
    code_snippet: str
    explanation: str


class _RiskySiteVisitor(ast.NodeVisitor):
    """AST visitor identifying risky API calls, global mutations, and concurrency."""

    def __init__(self, file_path: str, source_lines: list[str]) -> None:
        self.file_path = file_path
        self.source_lines = source_lines
        self.current_function: str = "<module>"
        self.sites: list[RiskySite] = []

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        prev = self.current_function
        self.current_function = node.name
        self.generic_visit(node)
        self.current_function = prev

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        prev = self.current_function
        self.current_function = node.name
        self.generic_visit(node)
        self.current_function = prev

    def visit_Global(self, node: ast.Global) -> None:
        snippet = self._get_line(node.lineno)
        self.sites.append(
            RiskySite(
                file_path=self.file_path,
                line_number=node.lineno,
                function_name=self.current_function,
                risk_category="globals",
                code_snippet=snippet,
                explanation=f"Rebinds global variable(s): {', '.join(node.names)}",
            )
        )
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        func_str = self._format_call(node.func)
        snippet = self._get_line(node.lineno)

        if func_str:
            # 1. Sleep
            if func_str in ("time.sleep", "asyncio.sleep", "sleep"):
                self.sites.append(
                    RiskySite(
                        file_path=self.file_path,
                        line_number=node.lineno,
                        function_name=self.current_function,
                        risk_category="sleep",
                        code_snippet=snippet,
                        explanation=f"Calls {func_str}, introducing timing and execution speed sensitivity.",
                    )
                )

            # 2. Random
            elif any(
                func_str.startswith(f"random.{m}")
                for m in ("random", "choice", "randint", "sample", "shuffle", "uniform", "randrange")
            ) or func_str in ("uuid.uuid4", "np.random.random", "numpy.random.random"):
                self.sites.append(
                    RiskySite(
                        file_path=self.file_path,
                        line_number=node.lineno,
                        function_name=self.current_function,
                        risk_category="randomness",
                        code_snippet=snippet,
                        explanation=f"Calls unseeded random source {func_str}.",
                    )
                )

            # 3. Now / Time
            elif func_str in (
                "datetime.now",
                "datetime.utcnow",
                "datetime.datetime.now",
                "datetime.datetime.utcnow",
                "time.time",
                "date.today",
            ):
                self.sites.append(
                    RiskySite(
                        file_path=self.file_path,
                        line_number=node.lineno,
                        function_name=self.current_function,
                        risk_category="now",
                        code_snippet=snippet,
                        explanation=f"Reads system wall-clock time via {func_str}.",
                    )
                )

            # 4. Threads / Concurrency
            elif func_str in (
                "threading.Thread",
                "Thread",
                "concurrent.futures.ThreadPoolExecutor",
                "concurrent.futures.ProcessPoolExecutor",
            ):
                self.sites.append(
                    RiskySite(
                        file_path=self.file_path,
                        line_number=node.lineno,
                        function_name=self.current_function,
                        risk_category="threads",
                        code_snippet=snippet,
                        explanation=f"Spawns asynchronous concurrent worker via {func_str}.",
                    )
                )

            # 5. Network
            elif any(
                func_str == lib or func_str.startswith(f"{lib}.")
                for lib in (
                    "requests.get",
                    "requests.post",
                    "urllib.request.urlopen",
                    "httpx.get",
                    "httpx.post",
                    "socket.socket",
                    "socket.create_connection",
                )
            ):
                self.sites.append(
                    RiskySite(
                        file_path=self.file_path,
                        line_number=node.lineno,
                        function_name=self.current_function,
                        risk_category="network",
                        code_snippet=snippet,
                        explanation=f"Performs external network I/O via {func_str}.",
                    )
                )

        self.generic_visit(node)

    def _format_call(self, node: ast.AST) -> str | None:
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            val = self._format_call(node.value)
            return f"{val}.{node.attr}" if val else node.attr
        return None

    def _get_line(self, lineno: int) -> str:
        if 1 <= lineno <= len(self.source_lines):
            return self.source_lines[lineno - 1].strip()
        return ""


def scan_file_for_risky_sites(file_path: Path) -> list[RiskySite]:
    """Scan a single Python file for risky non-deterministic sites."""
    if not file_path.is_file():
        return []

    try:
        content = file_path.read_text(encoding="utf-8")
        tree = ast.parse(content, filename=str(file_path))
    except Exception:
        return []

    lines = content.splitlines()
    visitor = _RiskySiteVisitor(str(file_path), lines)
    visitor.visit(tree)
    return visitor.sites


def scan_repository_for_risky_sites(
    repo_root: Path,
    exclude_dirs: tuple[str, ...] = ("tests", ".venv", "build", "dist", ".git"),
) -> list[RiskySite]:
    """Scan all Python source files in a repository for risky sites."""
    all_sites: list[RiskySite] = []
    root = repo_root.resolve()

    for py_file in root.glob("**/*.py"):
        # Check exclusion directories
        rel = py_file.relative_to(root)
        if any(part in exclude_dirs for part in rel.parts):
            continue

        sites = scan_file_for_risky_sites(py_file)
        all_sites.extend(sites)

    return all_sites


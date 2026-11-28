"""Static AST read/write map for detecting shared state and cross-test pollution."""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class AccessMap:
    """Read and write accesses detected for a test or function."""

    reads: set[str] = field(default_factory=set)
    writes: set[str] = field(default_factory=set)
    env_reads: set[str] = field(default_factory=set)
    env_writes: set[str] = field(default_factory=set)
    calls: set[str] = field(default_factory=set)


class _AccessVisitor(ast.NodeVisitor):
    """AST visitor extracting variable, attribute, call, and env accesses."""

    def __init__(self) -> None:
        self.reads: set[str] = set()
        self.writes: set[str] = set()
        self.env_reads: set[str] = set()
        self.env_writes: set[str] = set()
        self.calls: set[str] = set()

    def visit_Assign(self, node: ast.Assign) -> None:
        for target in node.targets:
            self._record_target(target, is_write=True)
        self.visit(node.value)

    def visit_AugAssign(self, node: ast.AugAssign) -> None:
        self._record_target(node.target, is_write=True)
        self.visit(node.value)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        self._record_target(node.target, is_write=True)
        if node.value:
            self.visit(node.value)

    def visit_Call(self, node: ast.Call) -> None:
        call_name = self._format_node(node.func)
        if call_name:
            self.calls.add(call_name)
            # Known mutating methods treat the target object as written
            if any(
                call_name.endswith(f".{m}")
                for m in (
                    "append",
                    "clear",
                    "update",
                    "pop",
                    "extend",
                    "register",
                    "set_session",
                    "set_configured",
                )
            ):
                prefix = call_name.rsplit(".", 1)[0]
                self.writes.add(prefix)

        # Check for os.environ accesses
        if isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name):
            if node.func.value.id == "os" and node.func.attr == "getenv":
                if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                    self.env_reads.add(node.args[0].value)

        self.generic_visit(node)

    def visit_Subscript(self, node: ast.Subscript) -> None:
        formatted = self._format_node(node.value)
        if formatted in ("os.environ", "environ"):
            if isinstance(node.slice, ast.Constant) and isinstance(node.slice.value, str):
                if isinstance(node.ctx, ast.Store):
                    self.env_writes.add(node.slice.value)
                else:
                    self.env_reads.add(node.slice.value)
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        formatted = self._format_node(node)
        if formatted:
            if isinstance(node.ctx, ast.Store):
                self.writes.add(formatted)
            elif isinstance(node.ctx, ast.Load):
                self.reads.add(formatted)
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:
        if isinstance(node.ctx, ast.Store):
            self.writes.add(node.id)
        elif isinstance(node.ctx, ast.Load):
            self.reads.add(node.id)
        self.generic_visit(node)

    def _record_target(self, target: ast.AST, is_write: bool = True) -> None:
        if isinstance(target, ast.Subscript):
            self.visit(target)
            return
        formatted = self._format_node(target)
        if formatted:
            if is_write:
                self.writes.add(formatted)
            else:
                self.reads.add(formatted)

    def _format_node(self, node: ast.AST) -> str | None:
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            val = self._format_node(node.value)
            return f"{val}.{node.attr}" if val else node.attr
        return None


def analyze_ast_access(node: ast.AST) -> AccessMap:
    """Analyze an AST node (function or module) to extract reads and writes."""
    visitor = _AccessVisitor()
    visitor.visit(node)
    return AccessMap(
        reads=visitor.reads,
        writes=visitor.writes,
        env_reads=visitor.env_reads,
        env_writes=visitor.env_writes,
        calls=visitor.calls,
    )


def extract_test_access_map(
    file_path: Path,
    test_name: str,
    repo_root: Path | None = None,
) -> AccessMap:
    """Parse a test file and return access map for a specific test function, including code under test if reachable."""
    if not file_path.is_file():
        return AccessMap()

    try:
        tree = ast.parse(file_path.read_text(encoding="utf-8"), filename=str(file_path))
    except Exception:
        return AccessMap()

    target_func: ast.AST | None = None
    for item in ast.walk(tree):
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if item.name == test_name:
                target_func = item
                break

    if target_func is None:
        return AccessMap()

    access_map = analyze_ast_access(target_func)

    # If repo_root is provided, also resolve function calls in repo source files
    if repo_root and repo_root.is_dir():
        for call_name in list(access_map.calls):
            parts = call_name.split(".")
            func_simple_name = parts[-1]
            # Search python files under src/ or module dirs for def func_simple_name
            for py_file in repo_root.glob("**/*.py"):
                if "tests" in py_file.parts or ".venv" in py_file.parts:
                    continue
                try:
                    src_tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
                    for item in ast.walk(src_tree):
                        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name == func_simple_name:
                            callee_map = analyze_ast_access(item)
                            # Callee reads and writes belong to the execution trace of the caller
                            # Normalize names with module name if available
                            mod_name = py_file.stem
                            for r in callee_map.reads:
                                access_map.reads.add(r)
                                access_map.reads.add(f"{mod_name}.{r}")
                            for w in callee_map.writes:
                                access_map.writes.add(w)
                                access_map.writes.add(f"{mod_name}.{w}")
                            access_map.env_reads.update(callee_map.env_reads)
                            access_map.env_writes.update(callee_map.env_writes)
                except Exception:
                    continue

    return access_map


def find_shared_state_overlap(polluter_map: AccessMap, victim_map: AccessMap) -> tuple[set[str], set[str]]:
    """Find shared state variables where polluter writes overlap with victim reads/writes.

    Returns:
        (polluter_writes_victim_reads, env_overlap)
    """
    # Normalize attribute prefixes (e.g. 'shop._default_tax' matches '_default_tax')
    def _normalize(names: set[str]) -> dict[str, str]:
        # Maps simple name -> original full name
        norm: dict[str, str] = {}
        for n in names:
            norm[n] = n
            if "." in n:
                simple = n.split(".")[-1]
                norm[simple] = n
        return norm

    p_writes_norm = _normalize(polluter_map.writes)
    v_reads_norm = _normalize(victim_map.reads)
    v_writes_norm = _normalize(victim_map.writes)

    # Intersect simple keys
    rw_overlap_keys = set(p_writes_norm.keys()).intersection(v_reads_norm.keys())
    ww_overlap_keys = set(p_writes_norm.keys()).intersection(v_writes_norm.keys())

    all_keys = rw_overlap_keys.union(ww_overlap_keys)
    state_overlap = {p_writes_norm[k] for k in all_keys}

    env_overlap = polluter_map.env_writes.intersection(victim_map.env_reads)

    return state_overlap, env_overlap

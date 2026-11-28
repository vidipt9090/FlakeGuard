"""Static analysis for the Repo map: tests, module-level shared state, and who touches it.

AST gives the structure (test functions, module-level mutable names, the exact line of each
read or write). Jedi gives the name resolution (``jedi.Script.goto``): which function a call
reaches, and which definition a name refers to, including through imports. A test is a writer
of a shared name if it assigns to or mutates it, directly or through the functions it calls,
and a reader if it only reads it.

Every access carries a real ``file:line``. Nothing is guessed: a name Jedi cannot resolve
to a module-level definition found by the AST is not reported.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import jedi

SKIP_DIRS = {
    ".git", ".hg", ".venv", "venv", "env", "node_modules", "__pycache__", "site-packages",
    ".tox", ".nox", ".mypy_cache", ".pytest_cache", ".ruff_cache", "build", "dist",
}
MUTABLE_CALLS = {"dict", "list", "set", "defaultdict", "OrderedDict", "Counter", "deque"}
MUTATING_METHODS = {
    "append", "extend", "insert", "add", "update", "clear", "pop", "popitem", "remove",
    "discard", "setdefault", "sort", "reverse",
}
MAX_CALL_DEPTH = 4


@dataclass(frozen=True)
class StateDef:
    """A module-level mutable name, for example ``CACHE = {}``."""

    name: str
    file: str  # repo-relative, forward slashes
    line: int

    @property
    def id(self) -> str:
        return f"{self.file}:{self.name}"


@dataclass(frozen=True)
class TestDef:
    id: str  # pytest node id, for example tests/test_a.py::test_x
    file: str
    name: str
    line: int
    end_line: int


@dataclass(frozen=True)
class Access:
    state: StateDef
    test_id: str
    kind: Literal["read", "write"]
    file: str
    line: int
    via: tuple[str, ...] = ()  # functions called between the test and the access


@dataclass
class RepoAnalysis:
    tests: list[TestDef] = field(default_factory=list)
    states: list[StateDef] = field(default_factory=list)
    accesses: list[Access] = field(default_factory=list)


def iter_python_files(repo: Path) -> list[Path]:
    return sorted(
        p for p in repo.rglob("*.py")
        if not any(part in SKIP_DIRS or part.endswith(".egg-info") for part in p.relative_to(repo).parts)
    )


def _rel(repo: Path, path: Path) -> str:
    return path.resolve().relative_to(repo.resolve()).as_posix()


def _parse(path: Path) -> ast.Module | None:
    try:
        return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (SyntaxError, UnicodeDecodeError, OSError):
        return None


def _is_mutable_value(node: ast.AST | None) -> bool:
    if isinstance(node, (ast.Dict, ast.List, ast.Set, ast.DictComp, ast.ListComp, ast.SetComp)):
        return True
    if isinstance(node, ast.Call):
        f = node.func
        name = f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else None
        return name in MUTABLE_CALLS
    return False


def find_state_defs(repo: Path) -> list[StateDef]:
    states: list[StateDef] = []
    for path in iter_python_files(repo):
        tree = _parse(path)
        if tree is None:
            continue
        rel = _rel(repo, path)
        for node in tree.body:
            if isinstance(node, ast.Assign) and _is_mutable_value(node.value):
                targets = [t for t in node.targets if isinstance(t, ast.Name)]
            elif isinstance(node, ast.AnnAssign) and _is_mutable_value(node.value) and isinstance(node.target, ast.Name):
                targets = [node.target]
            else:
                continue
            for t in targets:
                if not (t.id.startswith("__") and t.id.endswith("__")):
                    states.append(StateDef(name=t.id, file=rel, line=node.lineno))
    return states


def find_tests(repo: Path) -> list[TestDef]:
    tests: list[TestDef] = []
    for path in iter_python_files(repo):
        if not (path.name.startswith("test_") or path.name.endswith("_test.py")):
            continue
        tree = _parse(path)
        if tree is None:
            continue
        rel = _rel(repo, path)

        def add(fn: ast.FunctionDef | ast.AsyncFunctionDef, prefix: str) -> None:
            tests.append(TestDef(
                id=f"{rel}::{prefix}{fn.name}", file=rel, name=fn.name,
                line=fn.lineno, end_line=fn.end_lineno or fn.lineno,
            ))

        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test"):
                add(node, "")
            elif isinstance(node, ast.ClassDef) and node.name.startswith("Test"):
                for item in node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name.startswith("test"):
                        add(item, f"{node.name}::")
    return tests


class _Resolver:
    """Finds accesses to shared state from one test, following calls with Jedi."""

    def __init__(self, repo: Path, states: list[StateDef]) -> None:
        self.repo = repo.resolve()
        self.project = jedi.Project(
            path=str(self.repo), added_sys_path=[str(self.repo / "src"), str(self.repo)]
        )
        self.by_location = {(s.file, s.line): s for s in states}
        self.names = {s.name for s in states}
        self._scripts: dict[str, jedi.Script] = {}
        self._trees: dict[str, ast.Module | None] = {}

    def _script(self, rel: str) -> jedi.Script:
        if rel not in self._scripts:
            self._scripts[rel] = jedi.Script(path=str(self.repo / rel), project=self.project)
        return self._scripts[rel]

    def _tree(self, rel: str) -> ast.Module | None:
        if rel not in self._trees:
            self._trees[rel] = _parse(self.repo / rel)
        return self._trees[rel]

    def _goto(self, rel: str, line: int, col: int) -> list[tuple[str, int, str]]:
        """(repo-relative file, line, jedi type) for each definition the name resolves to."""
        try:
            defs = self._script(rel).goto(line, col, follow_imports=True)
        except Exception:  # Jedi can raise on odd syntax; an unresolved name is simply not reported
            return []
        out = []
        for d in defs:
            if d.module_path is None or d.line is None:
                continue
            try:
                out.append((_rel(self.repo, Path(d.module_path)), d.line, d.type))
            except ValueError:  # outside the repository (stdlib, site-packages)
                continue
        return out

    def _function_at(self, rel: str, line: int) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
        tree = self._tree(rel)
        if tree is None:
            return None
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.lineno == line:
                return node
        return None

    def _init_of_class_at(self, rel: str, line: int) -> ast.FunctionDef | None:
        tree = self._tree(rel)
        if tree is None:
            return None
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.lineno == line:
                for item in node.body:
                    if isinstance(item, ast.FunctionDef) and item.name == "__init__":
                        return item
        return None

    @staticmethod
    def _name_position(node: ast.Name | ast.Attribute) -> tuple[int, int]:
        if isinstance(node, ast.Name):
            return node.lineno, node.col_offset
        return node.end_lineno or node.lineno, (node.end_col_offset or 0) - len(node.attr)

    @staticmethod
    def _kind(node: ast.AST, parents: dict[ast.AST, ast.AST]) -> Literal["read", "write"]:
        parent = parents.get(node)
        if isinstance(parent, ast.Subscript) and parent.value is node and isinstance(parent.ctx, (ast.Store, ast.Del)):
            return "write"
        if isinstance(parent, ast.Attribute) and parent.value is node and parent.attr in MUTATING_METHODS:
            call = parents.get(parent)
            if isinstance(call, ast.Call) and call.func is parent:
                return "write"
        return "read"

    def scan_function(
        self,
        rel: str,
        fn: ast.FunctionDef | ast.AsyncFunctionDef,
        test_id: str,
        via: tuple[str, ...],
        visited: set[tuple[str, int]],
        out: list[Access],
    ) -> None:
        key = (rel, fn.lineno)
        if key in visited or len(via) > MAX_CALL_DEPTH:
            return
        visited.add(key)
        parents = {child: parent for parent in ast.walk(fn) for child in ast.iter_child_nodes(parent)}
        for node in ast.walk(fn):
            if isinstance(node, (ast.Name, ast.Attribute)):
                ident = node.id if isinstance(node, ast.Name) else node.attr
                if ident in self.names:
                    line, col = self._name_position(node)
                    for d_file, d_line, _ in self._goto(rel, line, col):
                        state = self.by_location.get((d_file, d_line))
                        if state is not None and state.name == ident:
                            out.append(Access(
                                state=state, test_id=test_id, kind=self._kind(node, parents),
                                file=rel, line=node.lineno, via=via,
                            ))
            if isinstance(node, ast.Call) and isinstance(node.func, (ast.Name, ast.Attribute)):
                line, col = self._name_position(node.func)
                callee = node.func.id if isinstance(node.func, ast.Name) else node.func.attr
                for d_file, d_line, d_type in self._goto(rel, line, col):
                    target = None
                    if d_type == "function":
                        target = self._function_at(d_file, d_line)
                    elif d_type == "class":
                        target = self._init_of_class_at(d_file, d_line)
                    if target is not None:
                        self.scan_function(d_file, target, test_id, (*via, callee), visited, out)


def analyse_repo(repo: Path) -> RepoAnalysis:
    repo = repo.resolve()
    result = RepoAnalysis(tests=find_tests(repo), states=find_state_defs(repo))
    if not result.states:
        return result
    resolver = _Resolver(repo, result.states)
    for test in result.tests:
        fn = resolver._function_at(test.file, test.line)
        if fn is not None:
            resolver.scan_function(test.file, fn, test.id, (), set(), result.accesses)
    return result


@dataclass(frozen=True)
class SharedLink:
    state: StateDef
    writers: tuple[str, ...]
    readers: tuple[str, ...]


def shared_links(analysis: RepoAnalysis) -> list[SharedLink]:
    """States that at least one test writes and at least two distinct tests touch."""
    links: list[SharedLink] = []
    for state in analysis.states:
        mine = [a for a in analysis.accesses if a.state == state]
        writers = sorted({a.test_id for a in mine if a.kind == "write"})
        readers = sorted({a.test_id for a in mine if a.kind == "read"})
        if writers and len({*writers, *readers}) >= 2:
            links.append(SharedLink(state=state, writers=tuple(writers), readers=tuple(readers)))
    return links

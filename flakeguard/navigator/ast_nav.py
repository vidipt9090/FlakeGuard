"""AST + jedi navigator: from a failing test id to the code it exercises.

Implements the ``Navigator`` protocol in ``flakeguard.contracts``.

The job: given ``tests/test_lru.py::LRUCacheTest::test_lru``, answer
  - which functions and classes does this test actually exercise?
  - which pytest fixtures does it pull in?
  - which module-level mutable state does it touch?
  - which flakiness smells appear in any of that code?

Two resolution paths, because real test suites use both:
  1. named calls   -- ``shop.total(prices)``  -> ``jedi.goto`` on the name
  2. operators     -- ``cache[1] = 1``        -> ``jedi.infer`` on the variable,
     which yields the class whose ``__setitem__`` is really being run.

Path 2 matters: a navigator with only path 1 finds almost nothing in a
container library like cachetools, where the API *is* the operators.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, replace
from pathlib import Path

import jedi

from flakeguard.contracts import Chunk, NavResult

# Names that look like flakiness when they appear in a test or in the code it
# exercises. Matched against dotted source text, so "time.sleep" also catches
# "time.sleep(0.1)" and a bare "sleep(" import is caught by SMELL_BARE.
SMELL_PATTERNS: tuple[str, ...] = (
    "time.sleep",
    "time.time",
    "time.monotonic",
    "datetime.now",
    "datetime.utcnow",
    "random.",
    "requests.",
    "socket.",
    "urllib.",
    "os.environ",
    "tempfile.",
    "threading.",
    "subprocess.",
    "asyncio.sleep",
)

# Bare names that carry the same risk when imported directly
# (``from time import sleep``).
SMELL_BARE: tuple[str, ...] = ("sleep", "shuffle", "randint", "uniform", "getenv")

# Call targets that build a mutable container at module level.
MUTABLE_FACTORIES: frozenset[str] = frozenset(
    {"list", "dict", "set", "bytearray", "defaultdict", "OrderedDict", "deque", "Counter"}
)

# Resolving every name costs a jedi round trip. ast.walk is breadth-first, so
# a low cap silently drops names nested deep inside a call -- which is exactly
# where a callback like ``timer=Timer()`` lives. Measured on cachetools: 150
# keeps the slowest test near a second, which a live demo can afford.
MAX_RESOLUTIONS = 150


@dataclass(frozen=True)
class _Target:
    """A located test function, plus the class that holds it (if any)."""

    path: Path
    rel_path: str
    source: str
    tree: ast.Module
    func: ast.FunctionDef | ast.AsyncFunctionDef
    cls: ast.ClassDef | None


def parse_test_id(test_id: str) -> tuple[str, list[str]]:
    """Split ``tests/test_x.py::TestA::test_b`` into path and the node chain."""
    parts = test_id.split("::")
    if not parts or not parts[0]:
        raise ValueError(f"test_id has no file part: {test_id!r}")
    # pytest-randomly and parametrised ids append "[param]" -- strip it.
    chain = [p.split("[", 1)[0] for p in parts[1:]]
    return parts[0], chain


class AstNavigator:
    """Navigate one repository checkout. One instance per repo + sha."""

    def __init__(self, repo_root: str | Path, repo: str = "repo", sha: str = "local") -> None:
        self.repo_root = Path(repo_root).resolve()
        self.repo = repo
        self.sha = sha
        # A jedi Project makes imports inside the repo resolvable, including
        # the src/ layout that cachetools uses.
        added = [str(self.repo_root / "src")] if (self.repo_root / "src").is_dir() else []
        self.project = jedi.Project(path=str(self.repo_root), added_sys_path=added)
        self._source_cache: dict[Path, str] = {}

    # ---------------------------------------------------------------- public

    def related(self, test_id: str) -> NavResult:
        """The ``Navigator`` contract. Never raises on a missing test."""
        try:
            target = self._locate(test_id)
        except (FileNotFoundError, ValueError, SyntaxError):
            return NavResult(test_id=test_id)

        code_under_test = self._code_under_test(target)
        fixtures = self._fixtures(target)
        shared_state = self._shared_state(target, code_under_test)
        smells = self._smells(target, code_under_test)

        return NavResult(
            test_id=test_id,
            code_under_test=code_under_test,
            fixtures=fixtures,
            shared_state=shared_state,
            smells=smells,
        )

    def test_chunk(self, test_id: str) -> Chunk | None:
        """The test body itself. C's evidence bundle needs this."""
        try:
            target = self._locate(test_id)
        except (FileNotFoundError, ValueError, SyntaxError):
            return None
        return self._chunk(target.path, target.func.lineno, _end(target.func), "test")

    # -------------------------------------------------------------- locating

    def _locate(self, test_id: str) -> _Target:
        rel_path, chain = parse_test_id(test_id)
        path = (self.repo_root / rel_path).resolve()
        if not path.is_file():
            raise FileNotFoundError(path)

        source = self._read(path)
        tree = ast.parse(source, filename=str(path))

        cls: ast.ClassDef | None = None
        scope: list[ast.stmt] = list(tree.body)
        func: ast.FunctionDef | ast.AsyncFunctionDef | None = None

        for name in chain:
            node = _find_named(scope, name)
            if node is None:
                raise ValueError(f"{name!r} not found in {rel_path}")
            if isinstance(node, ast.ClassDef):
                cls = node
                scope = list(node.body)
            else:
                func = node
                break

        if func is None:
            # Either no chain, or a class-only id. Fall back to the first
            # test_* function so the demo still shows something.
            func = _find_first_test(scope)
        if func is None:
            raise ValueError(f"no test function in {test_id}")

        return _Target(path, rel_path, source, tree, func, cls)

    # ------------------------------------------------------- code under test

    def _code_under_test(self, target: _Target) -> list[Chunk]:
        """Resolve names and operator receivers to definitions inside the repo."""
        script = jedi.Script(code=target.source, path=str(target.path), project=self.project)

        # (line, column, weight) positions to ask jedi about, in source order.
        goto_points: list[tuple[int, int]] = []
        infer_points: list[tuple[int, int]] = []

        for node in ast.walk(target.func):
            # Path 1: a call with a resolvable name.
            if isinstance(node, ast.Call):
                point = _name_position(node.func)
                if point is not None:
                    goto_points.append(point)
            # Path 2: operator use -- the receiver's *type* is the real target.
            elif isinstance(node, ast.Subscript):
                point = _name_position(node.value)
                if point is not None:
                    infer_points.append(point)
            # A bare name read as a value: ``Thread(target=func)`` never calls
            # func by name, but func is still the code under test.
            elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
                goto_points.append((node.lineno, node.col_offset))
            elif isinstance(node, ast.Attribute):
                # Resolve the attribute itself (``cachetools.keys.hashkey``
                # handed in as a default argument is never called by name),
                # and separately infer the receiver's type for operator use.
                here = _name_position(node)
                if here is not None:
                    goto_points.append(here)
                point = _name_position(node.value)
                if point is not None:
                    infer_points.append(point)

        # Key on (path, start_line), not the full range: goto and infer can
        # disagree by a line on where a class body ends, and that would show
        # the same definition twice.
        hits: dict[tuple[str, int], Chunk] = {}
        counts: dict[tuple[str, int], int] = {}
        order: dict[tuple[str, int], int] = {}

        def record(names, seq: int) -> None:
            for defn in names:
                chunk = self._chunk_from_definition(defn, target)
                if chunk is None:
                    continue
                key = (chunk.path, chunk.start_line)
                counts[key] = counts.get(key, 0) + 1
                order.setdefault(key, seq)
                # Prefer the wider span, so a class wins over a part of it.
                prev = hits.get(key)
                if prev is None or chunk.end_line > prev.end_line:
                    hits[key] = chunk
                # goto says "class", infer says "instance" of that class.
                # Keep the structural label whichever order they arrive in.
                if chunk.kind == "class" and hits[key].kind != "class":
                    hits[key] = replace(hits[key], kind="class")

        # A call's own name is also walked as a Name node, so drop repeats.
        for seq, (line, col) in enumerate(_unique(goto_points)[:MAX_RESOLUTIONS]):
            try:
                record(script.goto(line, col, follow_imports=True), seq)
            except Exception:  # jedi raises a zoo of errors on odd syntax
                continue

        for seq, (line, col) in enumerate(_unique(infer_points)[:MAX_RESOLUTIONS], start=1000):
            try:
                record(script.infer(line, col), seq)
            except Exception:
                continue

        # Second hop: what the definitions we just found are built on.
        # A test on TTLCache exercises its base _TimedCache, and a test that
        # calls a decorated function runs the decorator too. Both are code
        # under test even though the test never names them.
        for defn in self._expand(list(hits.values())):
            record([defn], 2000)

        # Score: how often the definition was reached, tie-broken by how early
        # it appears. This is what the top-3 metric in B3 ranks on.
        chunks = []
        for key, chunk in hits.items():
            chunks.append(
                Chunk(
                    chunk_id=chunk.chunk_id,
                    path=chunk.path,
                    start_line=chunk.start_line,
                    end_line=chunk.end_line,
                    kind=chunk.kind,
                    text=chunk.text,
                    score=float(counts[key]),
                )
            )
        chunks.sort(key=lambda c: (-c.score, order[(c.path, c.start_line)]))
        return chunks

    def _chunk_from_definition(self, defn, target: _Target) -> Chunk | None:
        """Keep only definitions that live in this repo and have a body."""
        module_path = defn.module_path
        if module_path is None:
            return None
        path = Path(module_path).resolve()
        if not _is_within(path, self.repo_root):
            return None  # stdlib, site-packages, pytest -- not our code
        if defn.type not in {"function", "class", "statement", "instance"}:
            return None
        # Class attributes of the TestCase (NTHREADS, TIMEOUT) are scaffolding.
        if defn.type == "statement" and path == target.path:
            return None

        if path.suffix == ".pyi":
            # jedi prefers type stubs, but a stub is a promise, not the code
            # that runs. Hop to the implementation of the same name.
            real = self._destub(path, defn.name)
            if real is None:
                return None
            path, start_line, end_line = real
        else:
            start = defn.get_definition_start_position()
            end = defn.get_definition_end_position()
            if start is None:
                return None
            start_line = start[0]
            end_line = end[0] if end else start_line

        # Drop the test itself and its enclosing class. Inferring ``self``
        # resolves to the TestCase subclass, which is not code under test.
        if path == target.path:
            if start_line == target.func.lineno:
                return None
            if target.cls is not None and start_line == target.cls.lineno:
                return None

        kind = "class" if defn.type == "class" else "function"
        return self._chunk(path, start_line, end_line, kind)

    def _expand(self, chunks: list[Chunk]) -> list:
        """Base classes and decorators of the definitions already found.

        Inheritance and decoration are both "code that runs when this test
        runs" without ever being named in the test, so a navigator that stops
        at the first hop under-reports on any library built with either.
        """
        extra: list = []
        for chunk in chunks:
            path = (self.repo_root / chunk.path).resolve()
            try:
                source = self._read(path)
                tree = ast.parse(source, filename=str(path))
            except (OSError, SyntaxError):
                continue

            points: list[tuple[int, int]] = []
            for node in ast.walk(tree):
                if not isinstance(
                    node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
                ):
                    continue
                if node.lineno != chunk.start_line:
                    continue
                if isinstance(node, ast.ClassDef):
                    for base in node.bases:
                        point = _name_position(base)
                        if point is not None:
                            points.append(point)
                for deco in node.decorator_list:
                    inner = deco.func if isinstance(deco, ast.Call) else deco
                    point = _name_position(inner)
                    if point is not None:
                        points.append(point)

            if not points:
                continue
            script = jedi.Script(code=source, path=str(path), project=self.project)
            for line, col in points:
                try:
                    extra.extend(script.goto(line, col, follow_imports=True))
                except Exception:
                    continue
        # The caller filters these the same way as a first-hop resolution.
        return extra

    def _destub(self, stub: Path, name: str) -> tuple[Path, int, int] | None:
        """Find ``name`` in the .py that a .pyi stub describes.

        cachetools declares ``cached`` in ``__init__.pyi`` but implements it
        in ``_cached.py``, so we check the sibling module first and then the
        rest of the package.
        """
        candidates = [stub.with_suffix(".py")]
        candidates.extend(sorted(stub.parent.glob("*.py")))
        for candidate in candidates:
            if not candidate.is_file():
                continue
            try:
                tree = ast.parse(self._read(candidate), filename=str(candidate))
            except (OSError, SyntaxError):
                continue
            for node in ast.walk(tree):
                if isinstance(
                    node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
                ) and node.name == name:
                    return candidate, node.lineno, _end(node)
        return None

    # -------------------------------------------------------------- fixtures

    def _fixtures(self, target: _Target) -> list[Chunk]:
        """Test arguments resolved against the conftest.py chain.

        pytest resolves a fixture by name, looking in the test module first,
        then every conftest.py from the test's directory up to the rootdir.
        We walk the same chain, nearest first, and stop at the first match --
        that is pytest's own override rule.
        """
        wanted = [
            a.arg
            for a in target.func.args.args
            if a.arg not in {"self", "cls"}
        ]
        if not wanted:
            return []

        search: list[Path] = [target.path]
        directory = target.path.parent
        while True:
            conftest = directory / "conftest.py"
            if conftest.is_file():
                search.append(conftest)
            if directory == self.repo_root or self.repo_root not in directory.parents:
                break
            directory = directory.parent

        found: list[Chunk] = []
        for name in wanted:
            for candidate in search:
                node = self._find_fixture(candidate, name)
                if node is not None:
                    # Start at the decorator, not at ``def``: scope="module"
                    # is the difference between a fresh object per test and
                    # state shared across the whole file.
                    start = min(
                        [node.lineno] + [d.lineno for d in node.decorator_list]
                    )
                    found.append(self._chunk(candidate, start, _end(node), "fixture"))
                    break
        return found

    def _find_fixture(self, path: Path, name: str) -> ast.stmt | None:
        try:
            tree = ast.parse(self._read(path), filename=str(path))
        except (OSError, SyntaxError):
            return None
        for node in tree.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if node.name != name:
                continue
            for deco in node.decorator_list:
                if "fixture" in ast.unparse(deco):
                    return node
        return None

    # ---------------------------------------------------------- shared state

    def _shared_state(self, target: _Target, code_under_test: list[Chunk]) -> list[Chunk]:
        """Module-level mutable values in every file this test reaches.

        Why this matters: a module-level list or dict is created once per
        process. Test A mutates it, test B reads it, and the pair passes or
        fails depending on the order pytest-randomly chose. That is the
        order_dep / shared_state root-cause family.
        """
        files: dict[Path, None] = {target.path: None}
        for chunk in code_under_test:
            files[(self.repo_root / chunk.path).resolve()] = None

        # Names the test declares global, plus every name it touches at all --
        # used to keep the result relevant instead of dumping every global.
        touched = _touched_names(target.func)

        out: list[Chunk] = []
        for path in files:
            try:
                tree = ast.parse(self._read(path), filename=str(path))
            except (OSError, SyntaxError):
                continue
            # Names some function in this module rebinds with ``global``.
            # These are shared state whatever their type: a module-level
            # ``JOB_DONE = False`` flipped by one test is exactly the bug.
            rebound = _global_declared_names(tree)
            for node in tree.body:
                for name, value in _module_level_assignments(node):
                    provable = name in rebound
                    if not provable and not _is_mutable(value):
                        continue
                    # A global that is provably rebound stays in even if the
                    # test never names it -- it is reached through the API.
                    if not provable and path == target.path and name not in touched:
                        continue
                    out.append(self._chunk(path, node.lineno, _end(node), "global"))
        return out

    # ----------------------------------------------------------------- smells

    def _smells(self, target: _Target, code_under_test: list[Chunk]) -> list[str]:
        """Pattern scan over the test body and the code it exercises."""
        blobs = [ast.get_source_segment(target.source, target.func) or ""]
        blobs.extend(c.text for c in code_under_test)

        found: list[str] = []
        for blob in blobs:
            for pattern in SMELL_PATTERNS:
                if pattern in blob and pattern not in found:
                    found.append(pattern)
            try:
                tree = ast.parse(_dedent(blob))
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                    if node.func.id in SMELL_BARE and node.func.id not in found:
                        found.append(node.func.id)
        return found

    # --------------------------------------------------------------- helpers

    def _read(self, path: Path) -> str:
        if path not in self._source_cache:
            self._source_cache[path] = path.read_text(encoding="utf-8", errors="replace")
        return self._source_cache[path]

    def _chunk(self, path: Path, start_line: int, end_line: int, kind: str) -> Chunk:
        rel = path.resolve().relative_to(self.repo_root).as_posix()
        lines = self._read(path).splitlines()
        text = "\n".join(lines[start_line - 1 : end_line])
        return Chunk(
            chunk_id=f"{self.repo}@{self.sha}:{rel}:{start_line}-{end_line}",
            path=rel,
            start_line=start_line,
            end_line=end_line,
            kind=kind,
            text=text,
        )


# -------------------------------------------------------------- module utils


def _end(node: ast.AST) -> int:
    return getattr(node, "end_lineno", None) or node.lineno  # type: ignore[attr-defined]


def _find_named(body: list[ast.stmt], name: str) -> ast.stmt | None:
    for node in body:
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name == name:
                return node
    return None


def _find_first_test(body: list[ast.stmt]):
    for node in body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name.startswith("test"):
                return node
    return None


def _name_position(node: ast.expr) -> tuple[int, int] | None:
    """A (line, column) jedi can resolve, for a Name or dotted Attribute.

    jedi columns are 0-based like ast's col_offset, but it wants a position
    *inside* the identifier. For ``shop.total`` we point at the last
    character of ``total``, not at ``shop``.
    """
    if isinstance(node, ast.Name):
        return node.lineno, node.col_offset
    if isinstance(node, ast.Attribute):
        return node.end_lineno or node.lineno, max((node.end_col_offset or 1) - 1, 0)
    return None


def _unique(points: list[tuple[int, int]]) -> list[tuple[int, int]]:
    seen: set[tuple[int, int]] = set()
    out: list[tuple[int, int]] = []
    for point in points:
        if point not in seen:
            seen.add(point)
            out.append(point)
    return out


def _is_within(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def _module_level_assignments(node: ast.stmt):
    """Yield (name, value) for top-level assignments."""
    if isinstance(node, ast.Assign):
        for target in node.targets:
            if isinstance(target, ast.Name):
                yield target.id, node.value
    elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
        if node.value is not None:
            yield node.target.id, node.value


def _is_mutable(value: ast.expr) -> bool:
    """Is this value shared mutable state rather than a constant?"""
    if isinstance(value, (ast.List, ast.Dict, ast.Set, ast.ListComp, ast.DictComp, ast.SetComp)):
        return True
    if isinstance(value, ast.Call):
        func = value.func
        name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
        if name in MUTABLE_FACTORIES:
            return True
        # A class instance held at module level is shared state too.
        return bool(name) and name[0].isupper()
    return False


def _global_declared_names(tree: ast.AST) -> set[str]:
    """Module-level names that some function rebinds with ``global``."""
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Global):
            names.update(node.names)
    return names


def _touched_names(func: ast.AST) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(func):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
        elif isinstance(node, ast.Global):
            names.update(node.names)
    return names


def _dedent(text: str) -> str:
    import textwrap

    return textwrap.dedent(text)

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

Every step is reportable. Pass a ``NavTrace`` and the navigator records what
the AST walk collected, every jedi call and what it returned, and the hop
depth each result was found at; ``explain()`` returns that alongside the
result and a knowledge tree built from it. Without a trace the recording
calls hit a shared no-op and nothing changes.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING

import jedi

from flakeguard.contracts import Chunk, NavResult
from flakeguard.navigator.trace import (
    NULL_TRACE,
    VIA_AST,
    VIA_JEDI,
    NavTrace,
    Provenance,
)

if TYPE_CHECKING:  # avoids a cycle: knowledge_tree does not import this module
    from flakeguard.navigator.knowledge_tree import KnowledgeTree

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

# How many first-hop definitions get a second hop (bases, decorators, callee
# defaults, one step into the body), strongest first.
MAX_EXPAND = 12

# Points to resolve per second-hop definition. A long function body would
# otherwise dominate the whole result.
MAX_EXPAND_POINTS = 60

# How many times to repeat the expansion. A second round does reach Cache
# through _TimedCache and lifts recall, but it buries the direct answer:
# measured on the held-out sets it cost 12 points of F1 and dropped
# correct-in-top-3 from 100% to 75%. Recall is worth little if the right
# chunk no longer fits in the evidence bundle, so one hop it is.
EXPAND_ROUNDS = 1

# How many ranked chunks the smell scan looks at. It mirrors what the evidence
# bundle carries: a smell found in code nobody will be shown is not evidence,
# it is noise, and in a library built on clocks it is noise on every test.
SMELL_SCAN_CHUNKS = 5

# Minimum score for a chunk to count as directly exercised. Direct name
# resolution scores 1.0 a hit and a fixture-built type W_FIXTURE, both of
# which the test genuinely drives. An inheritance hop scores W_EXPAND, which
# is below this line: that is library infrastructure, not this test.
DIRECT_SCORE = 0.8

# Evidence weights by distance from the test. A definition the test names is
# worth more than one reached by following three links, and ranking matters:
# C's evidence bundle only carries the first few chunks, so burying the right
# answer under transitively-reachable code is as bad as not finding it.
W_FIXTURE = 0.8      # what a fixture builds
W_CONCRETE = 0.9     # the subclass override behind self.x
W_EXPAND = 0.45      # per hop: 0.45, then 0.20, then 0.09


@dataclass(frozen=True)
class NavExplain:
    """What ``AstNavigator.explain`` hands back.

    ``result`` is the contract answer, unchanged. ``trace`` is the ordered
    record of how it was produced, and ``tree`` is the same answer arranged
    by distance from the test. The dashboard reads all three; the evidence
    bundle still reads only ``result``.
    """

    result: NavResult
    trace: "NavTrace"
    tree: "KnowledgeTree"
    # The test's own source, so a viewer can show which line the AST walk is
    # reading at each step. Every ast_walk event carries a line number, and
    # without the text those numbers point at nothing.
    test_source: Chunk | None = None

    def to_dict(self, include_text: bool = False) -> dict:
        return {
            "test_id": self.result.test_id,
            "tree": self.tree.to_dict(include_text=include_text),
            "trace": self.trace.to_dict(),
            "test_source": (
                {
                    "path": self.test_source.path,
                    "start_line": self.test_source.start_line,
                    "end_line": self.test_source.end_line,
                    "text": self.test_source.text,
                }
                if self.test_source is not None
                else None
            ),
            "result": {
                "code_under_test": [
                    {
                        "path": c.path,
                        "start_line": c.start_line,
                        "end_line": c.end_line,
                        "kind": c.kind,
                        "score": c.score,
                    }
                    for c in self.result.code_under_test
                ],
                "fixtures": [f"{c.path}:{c.start_line}" for c in self.result.fixtures],
                "shared_state": [
                    f"{c.path}:{c.start_line}" for c in self.result.shared_state
                ],
                "smells": list(self.result.smells),
            },
        }


@dataclass(frozen=True)
class _Target:
    """A located test function, plus the class that holds it (if any)."""

    path: Path
    rel_path: str
    source: str
    tree: ast.Module
    func: ast.FunctionDef | ast.AsyncFunctionDef
    cls: ast.ClassDef | None
    # The class named in the test id, which is not the class holding the body
    # when the test is inherited. ``self.x`` must resolve against this one:
    # the mixin declares the hook, the concrete class supplies what runs.
    concrete_cls: ast.ClassDef | None = None
    concrete_path: Path | None = None


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

    def __init__(
        self,
        repo_root: str | Path,
        repo: str = "repo",
        sha: str = "local",
        trace: NavTrace | None = None,
    ) -> None:
        self.repo_root = Path(repo_root).resolve()
        self.repo = repo
        self.sha = sha
        # Where each result came from, keyed the same way as ``hits``:
        # (relative path, start line). Filled during ``_code_under_test``
        # and read by the knowledge tree to draw its edges.
        self.trace: NavTrace = trace if trace is not None else NULL_TRACE
        self.provenance: dict[tuple[str, int], Provenance] = {}
        # A jedi Project makes imports inside the repo resolvable, including
        # the src/ layout that cachetools uses.
        added = []
        if (self.repo_root / "src").is_dir():
            added.append(str(self.repo_root / "src"))
        if (self.repo_root / "synthetic" / "src").is_dir():
            added.append(str(self.repo_root / "synthetic" / "src"))
        self.project = jedi.Project(path=str(self.repo_root), added_sys_path=added)
        self._source_cache: dict[Path, str] = {}

    # ---------------------------------------------------------------- public

    def related(self, test_id: str) -> NavResult:
        """The ``Navigator`` contract. Never raises on a missing test."""
        self.provenance = {}
        self.trace.test_id = self.trace.test_id or test_id
        try:
            target = self._locate(test_id)
        except (FileNotFoundError, ValueError, SyntaxError) as exc:
            self.trace.record(
                "locate", "fail", test_id, ok=False, detail=f"{type(exc).__name__}: {exc}"
            )
            return NavResult(test_id=test_id)

        fixtures = self._fixtures(target)
        code_under_test = self._code_under_test(target, fixtures)
        shared_state = self._shared_state(target, code_under_test)
        smells = self._smells(target, code_under_test)

        return NavResult(
            test_id=test_id,
            code_under_test=code_under_test,
            fixtures=fixtures,
            shared_state=shared_state,
            smells=smells,
        )

    def explain(self, test_id: str) -> "NavExplain":
        """Navigate, and also hand back how it was done.

        This is what the dashboard calls: the result, the ordered trace of
        AST and jedi steps that produced it, and the knowledge tree those
        steps describe. ``related()`` stays the contract surface and is
        unaffected.
        """
        from flakeguard.navigator.knowledge_tree import build_tree

        trace = NavTrace(test_id=test_id, repo=self.repo, sha=self.sha)
        previous, self.trace = self.trace, trace
        try:
            result = self.related(test_id)
        finally:
            self.trace = previous
        tree = build_tree(result, self.provenance, repo=self.repo, sha=self.sha)
        return NavExplain(
            result=result,
            trace=trace,
            tree=tree,
            test_source=self.test_chunk(test_id),
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
        with self.trace.step(
            "locate", "parse", rel_path, path=rel_path, via=VIA_AST
        ) as step:
            tree = ast.parse(source, filename=str(path))
            step.results = len(tree.body)
            step.detail = f"ast.parse -> {len(tree.body)} top-level statements"

        cls: ast.ClassDef | None = None
        scope: list[ast.stmt] = list(tree.body)
        func: ast.FunctionDef | ast.AsyncFunctionDef | None = None
        concrete_cls: ast.ClassDef | None = None
        concrete_path: Path | None = None

        for name in chain:
            node = _find_named(scope, name)
            if node is None:
                # pytest reports an inherited test under the concrete class,
                # but the body lives in the base. cachetools puts 23 tests in
                # CacheTestMixin alone, so this is the common case, not an
                # edge case: without it those ids resolve to nothing.
                inherited = (
                    self._find_inherited(cls, path, source, name)
                    if cls is not None
                    else None
                )
                if inherited is None:
                    raise ValueError(f"{name!r} not found in {rel_path}")
                # Remember where we came from before following the base.
                concrete_cls, concrete_path = cls, path
                path, source, tree, node, cls = inherited
                self.trace.record(
                    "inherit",
                    "resolve",
                    f"{name} (inherited)",
                    via=VIA_JEDI,
                    path=self._rel(path),
                    line=node.lineno,
                    results=1,
                    kept=1,
                    detail=f"body lives in {cls.name}, not in the class the id names",
                )
            if isinstance(node, ast.ClassDef):
                cls = node
                scope = list(node.body)
                self.trace.record(
                    "locate",
                    "enter-class",
                    node.name,
                    via=VIA_AST,
                    path=self._rel(path),
                    line=node.lineno,
                    results=len(node.body),
                )
            else:
                func = node
                self.trace.record(
                    "locate",
                    "found-test",
                    node.name,
                    via=VIA_AST,
                    path=self._rel(path),
                    line=node.lineno,
                    end_line=_end(node),
                    results=1,
                    kept=1,
                )
                break

        if func is None:
            # Either no chain, or a class-only id. Fall back to the first
            # test_* function so the demo still shows something.
            func = _find_first_test(scope)
        if func is None:
            raise ValueError(f"no test function in {test_id}")

        return _Target(
            path, rel_path, source, tree, func, cls, concrete_cls, concrete_path
        )

    def _find_inherited(
        self, cls: ast.ClassDef, path: Path, source: str, name: str, depth: int = 0
    ):
        """Look for a method in the base classes of ``cls``, depth first.

        Returns (path, source, tree, func, cls) for the base that defines it,
        because the rest of navigation has to run against the file the body
        actually lives in, not the file the test id names.
        """
        if depth > 3:  # cachetools nests two deep; three is slack, not a limit
            return None
        script = jedi.Script(code=source, path=str(path), project=self.project)
        for base in cls.bases:
            point = _name_position(base)
            if point is None:
                continue
            try:
                definitions = script.goto(*point, follow_imports=True)
            except Exception:
                continue
            for defn in definitions:
                if defn.module_path is None:
                    continue
                base_path = Path(defn.module_path).resolve()
                if not _is_within(base_path, self.repo_root):
                    continue  # unittest.TestCase and friends
                if base_path.suffix == ".pyi":
                    continue
                start = defn.get_definition_start_position()
                if start is None:
                    continue
                try:
                    base_source = self._read(base_path)
                    base_tree = ast.parse(base_source, filename=str(base_path))
                except (OSError, SyntaxError):
                    continue
                base_cls = next(
                    (
                        n
                        for n in ast.walk(base_tree)
                        if isinstance(n, ast.ClassDef) and n.lineno == start[0]
                    ),
                    None,
                )
                if base_cls is None:
                    continue
                found = _find_named(list(base_cls.body), name)
                if found is not None and not isinstance(found, ast.ClassDef):
                    return base_path, base_source, base_tree, found, base_cls
                deeper = self._find_inherited(
                    base_cls, base_path, base_source, name, depth + 1
                )
                if deeper is not None:
                    return deeper
        return None

    # ------------------------------------------------------- code under test

    def _code_under_test(
        self, target: _Target, fixtures: list[Chunk] | None = None
    ) -> list[Chunk]:
        """Resolve names and operator receivers to definitions inside the repo."""
        script = jedi.Script(code=target.source, path=str(target.path), project=self.project)

        # (line, column, weight) positions to ask jedi about, in source order.
        goto_points: list[tuple[int, int]] = []
        infer_points: list[tuple[int, int]] = []
        # What the AST walk named at each position, for the trace. The walk is
        # the step that turns a test body into a work list, so the dashboard
        # shows it node by node.
        named_at: dict[tuple[int, int], str] = {}

        def seen(node: ast.AST, point: tuple[int, int], why: str) -> None:
            label = _label_of(node)
            named_at.setdefault(point, label)
            self.trace.record(
                "ast_walk",
                type(node).__name__,
                label,
                depth=0,
                via=VIA_AST,
                path=target.rel_path,
                line=point[0],
                detail=why,
            )

        for node in ast.walk(target.func):
            # Path 1: a call with a resolvable name.
            if isinstance(node, ast.Call):
                point = _name_position(node.func)
                if point is not None:
                    goto_points.append(point)
                    seen(node.func, point, "call target -> goto")
            # Path 2: operator use -- the receiver's *type* is the real target.
            elif isinstance(node, ast.Subscript):
                point = _name_position(node.value)
                if point is not None:
                    infer_points.append(point)
                    seen(node.value, point, "subscript receiver -> infer its type")
            # A bare name read as a value: ``Thread(target=func)`` never calls
            # func by name, but func is still the code under test.
            elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
                point = (node.lineno, node.col_offset)
                goto_points.append(point)
                seen(node, point, "name read as a value -> goto")
            elif isinstance(node, ast.Attribute):
                # Resolve the attribute itself (``cachetools.keys.hashkey``
                # handed in as a default argument is never called by name),
                # and separately infer the receiver's type for operator use.
                here = _name_position(node)
                if here is not None:
                    goto_points.append(here)
                    seen(node, here, "attribute -> goto")
                point = _name_position(node.value)
                if point is not None:
                    infer_points.append(point)
                    seen(node.value, point, "attribute receiver -> infer its type")

        # Key on (path, start_line), not the full range: goto and infer can
        # disagree by a line on where a class body ends, and that would show
        # the same definition twice.
        hits: dict[tuple[str, int], Chunk] = {}
        counts: dict[tuple[str, int], float] = {}
        order: dict[tuple[str, int], int] = {}

        def record(
            names,
            seq: int,
            weight: float = 1.0,
            *,
            edge: str = "calls",
            via: str = VIA_JEDI,
            depth: int = 1,
            parent: str = "",
            source: str = "",
            produced: list[str] | None = None,
        ) -> int:
            """Fold jedi definitions into the result, remembering the edge.

            Returns how many survived filtering, which is what the trace
            reports as ``kept``: a jedi call that returned three definitions
            none of which live in this repo found nothing useful, and the
            difference between ``results`` and ``kept`` is where the
            navigator's precision comes from.
            """
            kept = 0
            for defn in names:
                chunk = self._chunk_from_definition(defn, target)
                if chunk is None:
                    continue
                kept += 1
                key = (chunk.path, chunk.start_line)
                if produced is not None:
                    marker = f"{chunk.path}:{chunk.start_line}"
                    if marker not in produced:
                        produced.append(marker)
                counts[key] = counts.get(key, 0) + weight
                order.setdefault(key, seq)
                # First edge to reach a chunk is the one the tree draws: it is
                # the shortest path from the test, because the phases run in
                # increasing distance order.
                known = self.provenance.get(key)
                if known is None:
                    self.provenance[key] = Provenance(
                        edge=edge,
                        via=via,
                        depth=depth,
                        seq=seq,
                        weight=weight,
                        parent=parent,
                        sources=[source] if source else [],
                    )
                elif source and source not in known.sources:
                    known.sources.append(source)
                # Prefer the wider span, so a class wins over a part of it.
                prev = hits.get(key)
                if prev is None or chunk.end_line > prev.end_line:
                    hits[key] = chunk
                # goto says "class", infer says "instance" of that class.
                # Keep the structural label whichever order they arrive in.
                if chunk.kind == "class" and hits[key].kind != "class":
                    hits[key] = replace(hits[key], kind="class")
            return kept

        # A call's own name is also walked as a Name node, so drop repeats.
        for seq, (line, col) in enumerate(_unique(goto_points)[:MAX_RESOLUTIONS]):
            name = named_at.get((line, col), f"{target.rel_path}:{line}:{col}")
            with self.trace.step(
                "jedi_goto",
                "goto",
                name,
                depth=1,
                via=VIA_JEDI,
                path=target.rel_path,
                line=line,
                weight=1.0,
                detail="jedi.goto(follow_imports=True): name -> definition",
            ) as step:
                try:
                    found = script.goto(line, col, follow_imports=True)
                except Exception:  # jedi raises a zoo of errors on odd syntax
                    step.ok = False
                    continue
                step.results = len(found)
                step.kept = record(
                    found,
                    seq,
                    edge="calls",
                    depth=1,
                    source=f"{target.rel_path}:{line}",
                    produced=step.produced,
                )

        for seq, (line, col) in enumerate(_unique(infer_points)[:MAX_RESOLUTIONS], start=1000):
            name = named_at.get((line, col), f"{target.rel_path}:{line}:{col}")
            with self.trace.step(
                "jedi_infer",
                "infer",
                name,
                depth=1,
                via=VIA_JEDI,
                path=target.rel_path,
                line=line,
                weight=1.0,
                detail="jedi.infer: expression -> the type whose operator runs",
            ) as step:
                try:
                    found = script.infer(line, col)
                except Exception:
                    step.ok = False
                    continue
                step.results = len(found)
                step.kept = record(
                    found,
                    seq,
                    edge="infers",
                    depth=1,
                    source=f"{target.rel_path}:{line}",
                    produced=step.produced,
                )

        # Further hops: what the definitions we just found are built on.
        # A test on TTLCache exercises its base _TimedCache, which in turn
        # exercises Cache. One hop stops halfway up a class hierarchy, so
        # walk until nothing new appears, bounded by EXPAND_ROUNDS.
        expanded: set[tuple[str, int]] = set()
        for round_no in range(EXPAND_ROUNDS):
            pending = [
                chunk for key, chunk in hits.items() if key not in expanded
            ]
            if not pending:
                break
            expanded.update((c.path, c.start_line) for c in pending)
            hop = round_no + 2  # depth 1 is a direct hit, so a first hop is 2
            self.trace.record(
                "expand",
                "round",
                f"hop {hop}: {len(pending)} definitions to expand",
                depth=hop,
                via=VIA_AST,
                results=len(pending),
                detail="bases, decorators, callee defaults and one step into the body",
            )
            # The per-definition jedi calls are traced inside _expand. This
            # step reports what the hop as a whole folded in, which is the
            # unit a replay reveals: a hop either reached something new or
            # it did not.
            with self.trace.step(
                "expand",
                "fold",
                f"hop {hop} results",
                depth=hop,
                via=VIA_JEDI,
                detail="definitions reached by this hop that survived filtering",
            ) as step:
                for parent, defn in self._expand(pending, depth=hop):
                    step.results += 1
                    step.kept += record(
                        [defn],
                        2000 + round_no,
                        W_EXPAND ** (round_no + 1),
                        edge="expands",
                        depth=hop,
                        parent=f"{parent.path}:{parent.start_line}",
                        source=f"{parent.path}:{parent.start_line}",
                        produced=step.produced,
                    )

        # Return-type inference was tried here and removed: see
        # nav-results.md. jedi can execute a function and report what it
        # hands back, which should have found _HashedTuple. Measured on all
        # three gold sets it added no recall at all and only false
        # positives, so it is not worth the latency or the noise.

        # What a fixture builds is what the test then calls methods on. The
        # test only ever sees an untyped argument, so without this a
        # fixture-based suite resolves to nothing at all.
        with self.trace.step(
            "fixture",
            "fold",
            "types the fixtures built",
            depth=2,
            via=VIA_JEDI,
            detail="the test only ever sees an untyped argument",
        ) as step:
            for parent, defn in self._from_fixtures(fixtures or []):
                step.results += 1
                step.kept += record(
                    [defn],
                    1500,
                    W_FIXTURE,
                    edge="fixture-builds",
                    depth=2,
                    parent=f"{parent.path}:{parent.start_line}",
                    source=f"{parent.path}:{parent.start_line}",
                    produced=step.produced,
                )

        # self.x inside an inherited test: the base declares the hook, the
        # concrete class named in the test id supplies what actually runs.
        # jedi resolves self to the base, so it would find the abstract stub.
        for chunk, defns in self._concrete_overrides(target):
            key = (chunk.path, chunk.start_line)
            counts[key] = counts.get(key, 0) + 2
            order.setdefault(key, 500)
            hits.setdefault(key, chunk)
            self.provenance.setdefault(
                key,
                Provenance(
                    edge="overrides",
                    via=VIA_AST,
                    depth=1,
                    seq=500,
                    weight=2.0,
                    detail="self.x resolved against the class the test id names",
                ),
            )
            self.trace.record(
                "concrete",
                "override",
                f"{chunk.path}:{chunk.start_line}",
                depth=1,
                via=VIA_AST,
                path=chunk.path,
                line=chunk.start_line,
                end_line=chunk.end_line,
                results=len(defns),
                kept=1,
                produced=[f"{chunk.path}:{chunk.start_line}"],
                detail="the concrete class supplies what actually runs",
            )
            for defn in defns:
                record(
                    [defn],
                    500,
                    W_CONCRETE,
                    edge="overrides",
                    depth=2,
                    parent=f"{chunk.path}:{chunk.start_line}",
                    source=f"{chunk.path}:{chunk.start_line}",
                )

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

        # A stub that cannot run is not code under test.
        node = self._node_at(path, start_line)
        if node is not None and _is_abstract(node):
            return None

        kind = "class" if defn.type == "class" else "function"
        return self._chunk(path, start_line, end_line, kind)

    def _node_at(self, path: Path, line: int):
        """The def/class that starts on this line, if any."""
        try:
            tree = ast.parse(self._read(path), filename=str(path))
        except (OSError, SyntaxError):
            return None
        for node in ast.walk(tree):
            if isinstance(
                node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
            ) and node.lineno == line:
                return node
        return None

    def _from_fixtures(self, fixtures: list[Chunk]) -> list[tuple[Chunk, object]]:
        """Definitions named inside fixture bodies, paired with the fixture.

        ``def signer(signer_factory): return signer_factory()`` hands the test
        a Signer. The test then calls signer.sign(...), but statically that is
        a bare parameter with no type, so the class under test is only
        reachable through the fixture that built it.

        Each definition is returned with the fixture chunk it came from, so
        the knowledge tree can hang it under that fixture instead of under
        the test directly -- which is the truth: the test never names it.
        """
        extra: list[tuple[Chunk, object]] = []
        for chunk in fixtures[:MAX_EXPAND]:
            path = (self.repo_root / chunk.path).resolve()
            try:
                source = self._read(path)
                tree = ast.parse(source, filename=str(path))
            except (OSError, SyntaxError):
                continue
            node = next(
                (
                    n
                    for n in ast.walk(tree)
                    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and chunk.start_line <= n.lineno <= chunk.end_line
                ),
                None,
            )
            if node is None:
                continue
            points: list[tuple[int, int]] = []
            for inner in ast.walk(node):
                if isinstance(inner, (ast.Name, ast.Attribute)):
                    point = _name_position(inner)
                    if point is not None:
                        points.append(point)
            script = jedi.Script(code=source, path=str(path), project=self.project)
            with self.trace.step(
                "fixture",
                "goto-body",
                f"inside fixture {chunk.path}:{chunk.start_line}",
                depth=2,
                via=VIA_JEDI,
                path=chunk.path,
                line=chunk.start_line,
                detail="what the fixture builds is what the test calls methods on",
            ) as step:
                for line, col in _unique(points)[:MAX_EXPAND_POINTS]:
                    try:
                        found = script.goto(line, col, follow_imports=True)
                    except Exception:
                        continue
                    extra.extend((chunk, defn) for defn in found)
                    step.results += len(found)
        return extra

    def _concrete_overrides(self, target: _Target):
        """Resolve ``self.x`` against the class the test id names.

        Yields (chunk for the override, jedi definitions reachable from it).
        The second part matters for a class attribute like
        ``DECORATOR = staticmethod(cachetools.func.lru_cache)``: the override
        is one line, and the code under test is what that line points at.
        """
        cls, path = target.concrete_cls, target.concrete_path
        if cls is None or path is None:
            return

        wanted = {
            node.attr
            for node in ast.walk(target.func)
            if isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == "self"
        }
        if not wanted:
            return

        source = self._read(path)
        script = jedi.Script(code=source, path=str(path), project=self.project)
        for node in cls.body:
            names = [
                n
                for n, _ in (
                    [(node.name, node)]
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                    else list(_module_level_assignments(node))
                )
            ]
            if not any(n in wanted for n in names):
                continue
            if _is_abstract(node):
                continue
            start = min([node.lineno] + [d.lineno for d in getattr(node, "decorator_list", [])])
            chunk = self._chunk(path, start, _end(node), "function")
            definitions: list = []
            for inner in ast.walk(node):
                if isinstance(inner, (ast.Name, ast.Attribute)) and not isinstance(
                    inner, ast.Call
                ):
                    point = _name_position(inner)
                    if point is None:
                        continue
                    try:
                        definitions.extend(script.goto(*point, follow_imports=True))
                    except Exception:
                        continue
            yield chunk, definitions

    def _expand(self, chunks: list[Chunk], depth: int = 2) -> list[tuple[Chunk, object]]:
        """Base classes and decorators of the definitions already found.

        Inheritance and decoration are both "code that runs when this test
        runs" without ever being named in the test, so a navigator that stops
        at the first hop under-reports on any library built with either.

        Returns (parent chunk, definition) pairs: ``depth`` is the hop this
        round sits at, and the parent is what the knowledge tree hangs the
        definition under.
        """
        extra: list[tuple[Chunk, object]] = []
        # Only the strongest first-hop results earn a second hop; descending
        # into everything is where a navigator turns into a whole-repo dump.
        for chunk in sorted(chunks, key=lambda c: -c.score)[:MAX_EXPAND]:
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
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    # Defaults in the CALLEE's signature carry real code:
                    # cachedmethod(cache, key=keys.methodkey, ...) names the
                    # key function the test never mentions.
                    defaults = list(node.args.defaults) + [
                        d for d in node.args.kw_defaults if d is not None
                    ]
                    for default in defaults:
                        point = _name_position(default)
                        if point is not None:
                            points.append(point)
                    # One step into the body. cached() imports _wrapper inside
                    # itself and calls it from a closure, so the function that
                    # does the work is invisible from the test alone.
                    for inner in ast.walk(node):
                        if isinstance(inner, ast.Call):
                            point = _name_position(inner.func)
                            if point is not None:
                                points.append(point)

            if not points:
                continue
            script = jedi.Script(code=source, path=str(path), project=self.project)
            with self.trace.step(
                "expand",
                "goto",
                f"{chunk.path}:{chunk.start_line} ({chunk.kind})",
                depth=depth,
                via=VIA_JEDI,
                path=chunk.path,
                line=chunk.start_line,
                end_line=chunk.end_line,
                weight=W_EXPAND ** (depth - 1),
                detail=f"{len(_unique(points))} base/decorator/default/callee names",
            ) as step:
                for line, col in _unique(points)[:MAX_EXPAND_POINTS]:
                    try:
                        found = script.goto(line, col, follow_imports=True)
                    except Exception:
                        continue
                    extra.extend((chunk, defn) for defn in found)
                    step.results += len(found)
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
        scopes = self._fixture_scopes(target)

        found: list[Chunk] = []
        seen: set[tuple[str, int]] = set()

        def take(path: Path, node, hop: int = 1, why: str = "") -> None:
            # Start at the decorator, not at ``def``: scope="module" is the
            # difference between a fresh object per test and state shared
            # across the whole file, and autouse changes who gets it.
            start = min([node.lineno] + [d.lineno for d in node.decorator_list])
            chunk = self._chunk(path, start, _end(node), "fixture")
            key = (chunk.path, chunk.start_line)
            if key not in seen:
                seen.add(key)
                found.append(chunk)
                self.trace.record(
                    "fixture",
                    "resolve",
                    node.name,
                    depth=hop,
                    via=VIA_AST,
                    path=chunk.path,
                    line=chunk.start_line,
                    end_line=chunk.end_line,
                    results=1,
                    kept=1,
                    produced=[f"{chunk.path}:{chunk.start_line}"],
                    detail=why or "named by the test, nearest conftest scope wins",
                )

        # A fixture can request other fixtures, and pytest resolves those too,
        # so walk the chain rather than stopping at the directly named ones.
        queue = [a.arg for a in target.func.args.args if a.arg not in {"self", "cls"}]
        depth = 0
        while queue and depth < 5:
            nxt: list[str] = []
            for name in queue:
                for path, body in scopes:
                    node = _find_fixture_in(body, name)
                    if node is None:
                        continue
                    take(
                        path,
                        node,
                        hop=depth + 1,
                        why=(
                            "requested by the test"
                            if depth == 0
                            else f"requested by another fixture (chain depth {depth + 1})"
                        ),
                    )
                    nxt.extend(
                        a.arg for a in node.args.args if a.arg not in {"self", "cls"}
                    )
                    break  # nearest scope wins, which is pytest's own rule
            queue = nxt
            depth += 1

        # autouse fixtures apply whether or not the test asks for them.
        for path, body in scopes:
            for node in body:
                if _is_fixture(node) and _is_autouse(node):
                    take(path, node, hop=1, why="autouse: applies without being asked for")
        return found

    def _base_class_scopes(
        self, cls: ast.ClassDef, path: Path, depth: int = 0
    ) -> list[tuple[Path, list[ast.stmt]]]:
        """Bodies of a test class's base classes, nearest first.

        Bases may live in another module, which pytest does not care about:
        test_timed.py imports TestSigner from test_signer.py and inherits its
        fixtures across the file boundary.
        """
        if depth > 3:
            return []
        out: list[tuple[Path, list[ast.stmt]]] = []
        try:
            source = self._read(path)
        except OSError:
            return out
        script = jedi.Script(code=source, path=str(path), project=self.project)
        for base in cls.bases:
            point = _name_position(base)
            if point is None:
                continue
            try:
                definitions = script.goto(*point, follow_imports=True)
            except Exception:
                continue
            for defn in definitions:
                if defn.module_path is None:
                    continue
                base_path = Path(defn.module_path).resolve()
                if not _is_within(base_path, self.repo_root):
                    continue
                if base_path.suffix == ".pyi":
                    continue
                start = defn.get_definition_start_position()
                if start is None:
                    continue
                node = self._node_at(base_path, start[0])
                if not isinstance(node, ast.ClassDef):
                    continue
                out.append((base_path, list(node.body)))
                out.extend(self._base_class_scopes(node, base_path, depth + 1))
        return out

    def _fixture_scopes(self, target: _Target) -> list[tuple[Path, list[ast.stmt]]]:
        """Where pytest looks for a fixture, nearest first.

        The enclosing test class (and its bases, for mixin suites), then the
        test module, then every conftest.py from the test's directory up to
        the repo root.
        """
        scopes: list[tuple[Path, list[ast.stmt]]] = []
        for cls in (target.concrete_cls, target.cls):
            if cls is None:
                continue
            path = target.concrete_path if cls is target.concrete_cls else target.path
            if path is None:
                continue
            scopes.append((path, list(cls.body)))
            # A test class inherits its bases' fixtures, and a subclass may
            # override one. Nearest first, so the subclass wins, which is what
            # pytest does. TestTimestampSigner(FreezeMixin, TestSigner) gets
            # signer from TestSigner and freeze from FreezeMixin.
            scopes.extend(self._base_class_scopes(cls, path))
        scopes.append((target.path, list(target.tree.body)))

        directory = target.path.parent
        while True:
            conftest = directory / "conftest.py"
            if conftest.is_file():
                try:
                    body = ast.parse(
                        self._read(conftest), filename=str(conftest)
                    ).body
                    scopes.append((conftest, list(body)))
                except (OSError, SyntaxError):
                    pass
            if directory == self.repo_root or self.repo_root not in directory.parents:
                break
            directory = directory.parent
        return scopes

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
                    chunk = self._chunk(path, node.lineno, _end(node), "global")
                    out.append(chunk)
                    self.trace.record(
                        "shared_state",
                        "global",
                        name,
                        depth=1 if path == target.path else 2,
                        via=VIA_AST,
                        path=chunk.path,
                        line=chunk.start_line,
                        end_line=chunk.end_line,
                        results=1,
                        kept=1,
                        produced=[f"{chunk.path}:{chunk.start_line}"],
                        detail=(
                            "rebound with `global` somewhere in this module"
                            if provable
                            else "module-level mutable value in a file this test reaches"
                        ),
                    )
        self.trace.record(
            "shared_state",
            "scan",
            f"{len(files)} reachable file(s)",
            depth=1,
            via=VIA_AST,
            results=len(out),
            kept=len(out),
            detail="module-level mutable state is the order_dep / shared_state family",
        )
        return out

    # ----------------------------------------------------------------- smells

    def _smells(self, target: _Target, code_under_test: list[Chunk]) -> list[str]:
        """Pattern scan over the test, its setup, and the code it exercises.

        Two things learned from scoring this on tenacity, where the first
        version managed precision 0.06:

        * Scanning everything reachable is useless in a library whose job
          involves clocks. `BaseRetrying` uses `time.monotonic`, so every
          single tenacity test came back "timing" and the signal carried no
          information. The scan is limited to the test plus the chunks that
          actually reach the evidence bundle.
        * Each smell carries where it was found. "time.sleep" alone tells the
          LLM nothing it can cite; "time.sleep (tenacity/nap.py:24)" is
          evidence. The contract keeps `smells: list[str]`, so this is a
          formatting choice, not a contract change.
        """
        blobs: list[tuple[str, str]] = []

        where = f"{target.rel_path}:{target.func.lineno}"
        blobs.append((where, ast.get_source_segment(target.source, target.func) or ""))

        # setUp and tearDown run for every test in the class, so a sleep or a
        # random seed in there is the test's nondeterminism just as much as
        # one in the body. The missed `random.` in tenacity's after-log tests
        # was exactly this.
        for cls, path in ((target.cls, target.path), (target.concrete_cls,
                                                      target.concrete_path)):
            if cls is None or path is None:
                continue
            for node in cls.body:
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and (
                    node.name in {"setUp", "tearDown", "setup_method", "teardown_method"}
                ):
                    rel = path.resolve().relative_to(self.repo_root).as_posix()
                    text = ast.get_source_segment(self._read(path), node) or ""
                    blobs.append((f"{rel}:{node.lineno}", text))

        # Only code the test reaches DIRECTLY. Infrastructure found by
        # walking up a class hierarchy is reachable from every test in the
        # library, so a smell there does not distinguish one test from
        # another: tenacity's BaseRetrying uses time.monotonic, which made
        # every single one of its tests look like a timing flake.
        direct = [c for c in code_under_test if c.score >= DIRECT_SCORE]
        for chunk in direct[:SMELL_SCAN_CHUNKS]:
            blobs.append((f"{chunk.path}:{chunk.start_line}", chunk.text))

        found: dict[str, str] = {}
        for where, blob in blobs:
            for pattern in SMELL_PATTERNS:
                if pattern in blob:
                    found.setdefault(pattern, where)
            try:
                tree = ast.parse(_dedent(blob))
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                    if node.func.id in SMELL_BARE:
                        found.setdefault(node.func.id, where)

        for name, place in found.items():
            file_part, _, line_part = place.rpartition(":")
            self.trace.record(
                "smell",
                "match",
                name,
                depth=1,
                via=VIA_AST,
                path=file_part or place,
                line=int(line_part) if line_part.isdigit() else 0,
                results=1,
                kept=1,
                produced=[f"smell:{name}"],
                detail=f"pattern found at {place}",
            )
        self.trace.record(
            "smell",
            "scan",
            f"{len(blobs)} blob(s): test + setUp/tearDown + top {len(direct)} direct chunk(s)",
            depth=1,
            via=VIA_AST,
            results=len(found),
            kept=len(found),
            detail="scan is bounded to directly-exercised code on purpose",
        )
        return [f"{name} ({place})" for name, place in found.items()]

    # --------------------------------------------------------------- helpers

    def _rel(self, path: Path) -> str:
        """Repo-relative posix path, or the absolute one if it is outside."""
        try:
            return path.resolve().relative_to(self.repo_root).as_posix()
        except ValueError:
            return path.as_posix()

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


def _label_of(node: ast.AST) -> str:
    """A readable dotted name for an AST node, for the trace.

    ``shop.cart.add`` reads as itself; anything that is not a plain name or
    attribute chain falls back to its node type, because the trace is for a
    human and "Call at line 12" beats an unparsed blob.
    """
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return f"{_label_of(node.value)}.{node.attr}"
    if isinstance(node, ast.Call):
        return f"{_label_of(node.func)}()"
    if isinstance(node, ast.Subscript):
        return f"{_label_of(node.value)}[...]"
    if isinstance(node, ast.Constant):
        return repr(node.value)[:30]
    return type(node).__name__


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


# Directories that are inside the checkout but are not the project's code.
# A virtualenv is the common case: `.venv/` sits in the repo root, so a plain
# "is this path under the repo?" test says yes to every installed package.
VENDOR_DIRS: frozenset[str] = frozenset(
    {
        "site-packages",
        "dist-packages",
        ".venv",
        "venv",
        ".tox",
        ".nox",
        "node_modules",
        "__pypackages__",
        ".eggs",
    }
)


def _is_vendored(path: Path, root: Path) -> bool:
    """True for a path that is under the repo but belongs to a dependency.

    Found the hard way: ``@freeze_time`` made jedi resolve into
    ``.venv/Lib/site-packages/freezegun/api.py``, and because ``.venv`` is
    inside the repo root that counted as code under test. On
    ``test_case_21`` eleven of twenty chunks were freezegun internals. The
    evidence bundle only carries the top few chunks, so third-party source
    does not merely add noise -- it pushes the real answer out.
    """
    try:
        parts = path.resolve().relative_to(root).parts
    except ValueError:
        return False
    return any(part in VENDOR_DIRS for part in parts)


def _is_within(path: Path, root: Path) -> bool:
    """Inside the repository, and part of the repository's own source."""
    if path != root and root not in path.parents:
        return False
    return not _is_vendored(path, root)


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


def _is_fixture(node: ast.stmt) -> bool:
    if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return False
    return any("fixture" in ast.unparse(d) for d in node.decorator_list)


def _is_autouse(node) -> bool:
    """An autouse fixture runs whether or not the test names it."""
    for deco in node.decorator_list:
        if not isinstance(deco, ast.Call):
            continue
        for kw in deco.keywords:
            if kw.arg == "autouse" and isinstance(kw.value, ast.Constant):
                if kw.value.value is True:
                    return True
    return False


def _find_fixture_in(body: list[ast.stmt], name: str):
    for node in body:
        if _is_fixture(node) and node.name == name:  # type: ignore[attr-defined]
            return node
    return None


def _is_abstract(node: ast.AST) -> bool:
    """A declaration with no behaviour: ``...``, ``pass``, or NotImplementedError.

    Protocol stubs and template-method hooks resolve like any other function
    but never run, so reporting them as code under test is just noise.
    """
    if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return False
    body = [n for n in node.body if not _is_docstring(n)]
    if not body:
        return True
    for stmt in body:
        if isinstance(stmt, ast.Pass):
            continue
        if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant):
            if stmt.value.value is Ellipsis:
                continue
        if isinstance(stmt, ast.Raise):
            raised = stmt.exc
            name = ""
            if isinstance(raised, ast.Call):
                raised = raised.func
            if isinstance(raised, ast.Name):
                name = raised.id
            elif isinstance(raised, ast.Attribute):
                name = raised.attr
            if name == "NotImplementedError":
                continue
        return False
    return True


def _is_docstring(node: ast.stmt) -> bool:
    return (
        isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
    )


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

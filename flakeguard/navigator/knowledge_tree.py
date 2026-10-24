"""The knowledge tree: a failing test and everything reachable from it.

``NavResult`` is four flat lists. That is the right shape for an evidence
bundle, and the wrong shape for understanding -- it loses the one thing that
explains the navigator's answer, which is *distance from the test*. A class
the test instantiates on line 3 and a base class found two hops up the
hierarchy arrive in the same list, with only a score to tell them apart.

The knowledge tree puts the structure back. The root is the test. Each child
is something the navigator reached, hung under whatever reached it, labelled
with the edge that got there:

    TEST  synthetic/tests/test_suite_02.py::test_case_13
    |- calls           shop.py:14  add_to_cart            score 2.0
    |  '- expands      shop.py:4   Cart                   score 0.45
    |- infers          shop.py:31  Inventory              score 1.0
    |- fixture-builds  conftest.py:8  session             score 0.8
    |- touches         shop.py:9   _CART (module global)
    '- smells          time.sleep (shop.py:22)

Edges, and what each one means:

``calls``           the test names it -- ``jedi.goto`` resolved the name
``infers``          the test uses an operator on it -- ``jedi.infer`` gave
                    the type whose ``__getitem__`` actually runs
``fixture-builds``  a fixture constructed it; the test only sees an
                    untyped argument
``overrides``       ``self.x`` in an inherited test, resolved against the
                    concrete class named in the test id
``expands``         reached from its parent's bases, decorators, callee
                    defaults, or one step into its body
``touches``         module-level mutable state in a reachable file
``smells``          a flakiness pattern matched in directly-exercised code

The tree is what the dashboard draws and what CI exports per test case. It
is derived, never authoritative: ``NavResult`` stays the contract.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from flakeguard.contracts import Chunk, NavResult
from flakeguard.navigator.trace import Provenance

# Depth 1 edges come straight off the test; the rest hang off a parent.
DIRECT_EDGES: frozenset[str] = frozenset({"calls", "infers", "overrides"})

# Display order for children at the same depth, so the tree reads
# nearest-first regardless of dict ordering.
EDGE_ORDER: dict[str, int] = {
    "calls": 0,
    "infers": 1,
    "overrides": 2,
    "fixture": 3,
    "fixture-builds": 4,
    "expands": 5,
    "touches": 6,
    "smells": 7,
}


@dataclass
class TreeNode:
    """One node of the knowledge tree."""

    node_id: str
    kind: str          # test | function | class | fixture | global | smell
    label: str
    edge: str = ""     # how its parent reached it; "" for the root
    via: str = ""      # ast | jedi -- which resolver found it
    path: str = ""
    start_line: int = 0
    end_line: int = 0
    depth: int = 0
    score: float = 0.0
    detail: str = ""
    text: str = ""
    children: list[TreeNode] = field(default_factory=list)

    # ------------------------------------------------------------- traversal

    def walk(self):
        """This node, then every descendant, depth first."""
        yield self
        for child in self.children:
            yield from child.walk()

    def size(self) -> int:
        return sum(1 for _ in self.walk())

    def max_depth(self) -> int:
        return max(node.depth for node in self.walk())

    def sort(self) -> None:
        """Order children nearest-edge first, then by score, then by line."""
        self.children.sort(
            key=lambda c: (EDGE_ORDER.get(c.edge, 99), -c.score, c.path, c.start_line)
        )
        for child in self.children:
            child.sort()

    # ----------------------------------------------------------- rendering

    def to_dict(self, include_text: bool = False) -> dict:
        out = {
            "node_id": self.node_id,
            "kind": self.kind,
            "label": self.label,
            "edge": self.edge,
            "via": self.via,
            "path": self.path,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "depth": self.depth,
            "score": round(self.score, 4),
            "detail": self.detail,
            "children": [c.to_dict(include_text) for c in self.children],
        }
        if include_text:
            out["text"] = self.text
        return out

    def render(self, prefix: str = "", is_last: bool = True, is_root: bool = True) -> str:
        """Box-drawing text form. Used by the CLI demo and the dashboard."""
        if is_root:
            head = f"TEST  {self.label}"
            lines = [head]
        else:
            connector = "`- " if is_last else "|- "
            where = f"{self.path}:{self.start_line}" if self.path else ""
            score = f"  score {self.score:.2f}" if self.score else ""
            edge = f"[{self.edge}]" if self.edge else ""
            lines = [f"{prefix}{connector}{edge:<17} {self.label}  {where}{score}".rstrip()]
            prefix = prefix + ("   " if is_last else "|  ")
        for index, child in enumerate(self.children):
            lines.append(
                child.render(
                    prefix, is_last=index == len(self.children) - 1, is_root=False
                )
            )
        return "\n".join(lines)


@dataclass
class KnowledgeTree:
    """A rooted tree plus the counters a report needs."""

    root: TreeNode
    test_id: str
    repo: str = ""
    sha: str = ""

    # --------------------------------------------------------------- metrics

    def stats(self) -> dict:
        """Shape of the tree, which is what gets charted and gated on."""
        nodes = list(self.root.walk())
        by_depth: dict[int, int] = {}
        by_edge: dict[str, int] = {}
        by_kind: dict[str, int] = {}
        for node in nodes:
            by_depth[node.depth] = by_depth.get(node.depth, 0) + 1
            by_kind[node.kind] = by_kind.get(node.kind, 0) + 1
            if node.edge:
                by_edge[node.edge] = by_edge.get(node.edge, 0) + 1
        files = {node.path for node in nodes if node.path}
        return {
            "test_id": self.test_id,
            "nodes": len(nodes),
            "edges": len(nodes) - 1,
            "max_depth": self.root.max_depth(),
            "files_touched": len(files),
            "branching_factor": (
                round((len(nodes) - 1) / sum(1 for n in nodes if n.children), 3)
                if any(n.children for n in nodes)
                else 0.0
            ),
            "nodes_by_depth": dict(sorted(by_depth.items())),
            "nodes_by_edge": dict(sorted(by_edge.items(), key=lambda kv: -kv[1])),
            "nodes_by_kind": dict(sorted(by_kind.items(), key=lambda kv: -kv[1])),
        }

    def to_dict(self, include_text: bool = False) -> dict:
        return {
            "test_id": self.test_id,
            "repo": self.repo,
            "sha": self.sha,
            "stats": self.stats(),
            "root": self.root.to_dict(include_text),
        }

    def render(self) -> str:
        return self.root.render()

    # ------------------------------------------------- flat views for charts

    def rows(self) -> list[dict]:
        """One row per node with its parent, for a treemap or a table.

        Plotly's treemap and sunburst both want parallel ``ids``/``parents``
        arrays, which is exactly this with the nesting flattened out.
        """
        rows: list[dict] = []

        def visit(node: TreeNode, parent_id: str) -> None:
            rows.append(
                {
                    "id": node.node_id,
                    "parent": parent_id,
                    "label": node.label,
                    "kind": node.kind,
                    "edge": node.edge or "root",
                    "via": node.via or "-",
                    "depth": node.depth,
                    "score": round(node.score, 4),
                    "path": node.path,
                    "start_line": node.start_line,
                    "end_line": node.end_line,
                    "lines": max(0, node.end_line - node.start_line + 1) if node.path else 0,
                    "detail": node.detail,
                }
            )
            for child in node.children:
                visit(child, node.node_id)

        visit(self.root, "")
        return rows


def build_tree(
    result: NavResult,
    provenance: dict[tuple[str, int], Provenance] | None = None,
    repo: str = "",
    sha: str = "",
) -> KnowledgeTree:
    """Assemble the tree from a ``NavResult`` and the navigator's provenance.

    Without provenance (a ``NavResult`` loaded from disk, say) every chunk
    hangs directly off the test at depth 1. That is a flatter tree but still
    a correct one -- the edges are simply unknown rather than wrong.
    """
    provenance = provenance or {}

    root = TreeNode(
        node_id=result.test_id or "test",
        kind="test",
        label=result.test_id or "test",
        depth=0,
        detail="the failing test the navigator was asked about",
    )

    # Fixtures first: a fixture can be the parent of code under test, so its
    # node has to exist before anything is hung under it.
    nodes: dict[str, TreeNode] = {}
    for chunk in result.fixtures:
        node = _node_from_chunk(
            chunk,
            edge="fixture",
            via="ast",
            depth=1,
            detail="pytest resolves this before the test body runs",
        )
        nodes[_key(chunk)] = node
        root.children.append(node)

    # Code under test, parented by provenance where we have it. Sorting by
    # depth means a parent is placed before any child that names it.
    pending: list[tuple[Chunk, Provenance]] = []
    for chunk in result.code_under_test:
        prov = provenance.get((chunk.path, chunk.start_line)) or Provenance(
            edge="reaches", via="jedi", depth=1
        )
        pending.append((chunk, prov))
    pending.sort(key=lambda pair: (pair[1].depth, -pair[0].score))

    for chunk, prov in pending:
        node = _node_from_chunk(
            chunk,
            edge=prov.edge,
            via=prov.via,
            depth=prov.depth,
            detail=prov.detail or _edge_detail(prov.edge),
        )
        key = _key(chunk)
        nodes[key] = node
        parent = nodes.get(prov.parent) if prov.parent else None
        if parent is None:
            # Either a direct hit, or a parent that was filtered out of the
            # result. Hanging it off the test keeps the node rather than
            # dropping evidence, and its depth still says how far it was.
            root.children.append(node)
        else:
            parent.children.append(node)
            node.depth = parent.depth + 1

    # Shared state and smells are properties of the test's reachable set, not
    # definitions, so they sit at depth 1 under whichever file they are in.
    for chunk in result.shared_state:
        root.children.append(
            _node_from_chunk(
                chunk,
                edge="touches",
                via="ast",
                depth=1,
                detail="module-level mutable state: created once per process",
            )
        )

    for smell in result.smells:
        name, _, place = smell.partition(" (")
        where = place.rstrip(")")
        path, _, line = where.rpartition(":")
        root.children.append(
            TreeNode(
                node_id=f"smell:{smell}",
                kind="smell",
                label=name.strip(),
                edge="smells",
                via="ast",
                path=path,
                start_line=int(line) if line.isdigit() else 0,
                depth=1,
                detail=f"flakiness pattern matched at {where}" if where else "",
            )
        )

    root.sort()
    return KnowledgeTree(root=root, test_id=result.test_id, repo=repo, sha=sha)


def _key(chunk: Chunk) -> str:
    return f"{chunk.path}:{chunk.start_line}"


def _node_from_chunk(
    chunk: Chunk, edge: str, via: str, depth: int, detail: str = ""
) -> TreeNode:
    return TreeNode(
        node_id=chunk.chunk_id or _key(chunk),
        kind=chunk.kind,
        label=_label_for(chunk),
        edge=edge,
        via=via,
        path=chunk.path,
        start_line=chunk.start_line,
        end_line=chunk.end_line,
        depth=depth,
        score=chunk.score,
        detail=detail,
        text=chunk.text,
    )


def _label_for(chunk: Chunk) -> str:
    """The declared name on the chunk's first meaningful line.

    Chunks are spans of source, not syntax nodes, so the name has to be read
    back out of the text. Three shapes appear in practice: a ``def``/``class``
    header, a decorator with the header a line or two below, and a bare
    assignment -- ``jedi.goto`` on a global resolves to the statement that
    binds it, and "JOB_DONE" is the only useful label for that.
    """
    stripped_text = chunk.text.strip()
    if not stripped_text:
        return f"{chunk.path.rsplit('/', 1)[-1]}:{chunk.start_line}"

    for line in stripped_text.splitlines():
        line = line.strip()
        for keyword in ("async def ", "def ", "class "):
            if line.startswith(keyword):
                return line[len(keyword):].split("(")[0].split(":")[0].strip()
        if line.startswith("@") or not line:
            continue  # decorator: the header is further down
        # An assignment, annotated or not: take the left-hand side.
        head = line.split("=", 1)[0].strip() if "=" in line else ""
        if head and head.replace("_", "").replace(".", "").replace(",", "").isalnum():
            return head.split(":")[0].strip()
        break

    return f"{chunk.path.rsplit('/', 1)[-1]}:{chunk.start_line}"


def _edge_detail(edge: str) -> str:
    return {
        "calls": "the test names this -- jedi.goto resolved the name",
        "infers": "operator use -- jedi.infer gave the type whose method runs",
        "fixture-builds": "built by a fixture; the test only sees an untyped argument",
        "overrides": "self.x resolved against the concrete class in the test id",
        "expands": "reached from its parent's bases, decorators, defaults or body",
        "reaches": "reached by the navigator; edge not recorded",
    }.get(edge, "")

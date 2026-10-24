"""Tests for the navigation trace and the knowledge tree built from it.

Same sample project as tests/test_navigator.py: tests/data/navsample is
small enough that the expected tree can be checked by eye. No network and no
cachetools checkout, so this runs in CI.

What these tests protect:
  - tracing is genuinely free when off, and complete when on
  - the tree's edges say which resolver found each node, and its depths say
    how far from the test each one is -- that is the whole claim the
    dashboard makes, so a wrong edge is a wrong explanation
  - ``explain()`` cannot change what ``related()`` answers
"""

from pathlib import Path

import pytest

from flakeguard.contracts import Chunk, NavResult
from flakeguard.navigator.ast_nav import AstNavigator, NavExplain
from flakeguard.navigator.knowledge_tree import KnowledgeTree, TreeNode, build_tree
from flakeguard.navigator.trace import NULL_TRACE, NavTrace, Provenance

SAMPLE = Path(__file__).parent / "data" / "navsample"


@pytest.fixture(scope="module")
def nav():
    return AstNavigator(SAMPLE, repo="navsample", sha="test")


# --------------------------------------------------------------- the recorder


def test_null_trace_records_nothing():
    """The default path must stay free, including through a step body."""
    before = len(NULL_TRACE.events)
    with NULL_TRACE.step("jedi_goto", "goto", "anything") as step:
        step.results = 7
        step.kept = 3
        step.detail = "ignored"
    NULL_TRACE.record("ast_walk", "walk", "also ignored", depth=4)
    assert len(NULL_TRACE.events) == before == 0
    assert NULL_TRACE.enabled is False


def test_null_step_reads_back_as_empty():
    """``s.results += n`` has to work when tracing is off, not raise."""
    with NULL_TRACE.step("jedi_goto", "goto", "x") as step:
        step.results += 5
        assert step.results == 0
        assert step.kept == 0


def test_trace_records_in_order_with_depth():
    trace = NavTrace("tests/t.py::test_x")
    trace.record("ast_walk", "Call", "shop.total", depth=0)
    with trace.step("jedi_goto", "goto", "shop.total", depth=1) as step:
        step.results = 2
        step.kept = 1
    trace.record("expand", "goto", "Cache", depth=2)

    assert [e.seq for e in trace.events] == [1, 2, 3]
    assert [e.phase for e in trace.events] == ["ast_walk", "jedi_goto", "expand"]
    summary = trace.summary()
    assert summary["ast_names"] == 1
    assert summary["jedi_goto_calls"] == 1
    assert summary["jedi_hits"] == 1
    assert summary["jedi_hit_rate"] == 1.0
    assert summary["max_depth"] == 2
    assert trace.by_depth() == {0: 1, 1: 1, 2: 1}


def test_trace_counts_a_miss_as_a_miss():
    """A jedi call that returned nothing is not a hit. Precision depends on it."""
    trace = NavTrace()
    with trace.step("jedi_goto", "goto", "len", depth=1) as step:
        step.results = 0
    with trace.step("jedi_infer", "infer", "cache", depth=1) as step:
        step.results = 1
        step.kept = 1
    summary = trace.summary()
    assert summary["jedi_calls"] == 2
    assert summary["jedi_hits"] == 1
    assert summary["jedi_hit_rate"] == 0.5


def test_step_does_not_swallow_exceptions():
    trace = NavTrace()
    with pytest.raises(ValueError):
        with trace.step("jedi_goto", "goto", "boom"):
            raise ValueError("boom")
    # The step is still recorded, flagged as failed -- a crashed resolution
    # is evidence, not something to hide.
    assert len(trace.events) == 1
    assert trace.events[0].ok is False


# ------------------------------------------------------------ live navigation


def test_explain_matches_related(nav):
    """``explain`` must be ``related`` plus commentary, never a different answer."""
    test_id = "tests/test_shop.py::test_total"
    plain = nav.related(test_id)
    explained = nav.explain(test_id)

    assert isinstance(explained, NavExplain)
    assert explained.result.test_id == plain.test_id
    assert [c.chunk_id for c in explained.result.code_under_test] == [
        c.chunk_id for c in plain.code_under_test
    ]
    assert [c.chunk_id for c in explained.result.fixtures] == [
        c.chunk_id for c in plain.fixtures
    ]
    assert sorted(explained.result.smells) == sorted(plain.smells)


def test_explain_records_both_resolver_paths(nav):
    explained = nav.explain("tests/test_shop.py::test_total")
    summary = explained.trace.summary()

    assert summary["events"] > 0
    assert summary["ast_names"] > 0, "the AST walk must report what it collected"
    assert summary["jedi_goto_calls"] > 0, "shop.total is a named call -> goto"
    phases = summary["events_by_phase"]
    assert "locate" in phases
    assert "shared_state" in phases


def test_trace_is_not_shared_between_explains(nav):
    """Each explain gets its own trace; the navigator keeps no leftovers."""
    first = nav.explain("tests/test_shop.py::test_total")
    second = nav.explain("tests/test_shop.py::test_job_finishes")
    assert first.trace is not second.trace
    assert first.trace.test_id == "tests/test_shop.py::test_total"
    assert second.trace.test_id == "tests/test_shop.py::test_job_finishes"
    # ...and explaining does not leave tracing switched on afterwards.
    assert nav.trace.enabled is False


def test_missing_test_explains_cleanly(nav):
    explained = nav.explain("tests/test_shop.py::test_does_not_exist")
    assert explained.result.code_under_test == []
    assert explained.tree.root.kind == "test"
    assert explained.tree.stats()["nodes"] == 1
    # The failure to locate is itself recorded, so the dashboard can say why.
    assert any(e.phase == "locate" and not e.ok for e in explained.trace.events)


# ---------------------------------------------------------------- tree shape


def test_tree_root_is_the_test(nav):
    explained = nav.explain("tests/test_shop.py::test_total")
    root = explained.tree.root
    assert root.kind == "test"
    assert root.label == "tests/test_shop.py::test_total"
    assert root.depth == 0
    assert root.edge == ""


def test_named_call_is_a_calls_edge_found_by_jedi(nav):
    explained = nav.explain("tests/test_shop.py::test_total")
    labels = {
        node.label: node
        for node in explained.tree.root.walk()
        if node.kind in {"function", "class"}
    }
    assert "total" in labels, f"expected shop.total in the tree, got {sorted(labels)}"
    node = labels["total"]
    assert node.edge == "calls"
    assert node.via == "jedi"
    assert node.depth == 1
    assert node.path.endswith("shop.py")


def test_fixtures_are_their_own_edge(nav):
    explained = nav.explain("tests/test_shop.py::test_total")
    fixtures = [n for n in explained.tree.root.walk() if n.kind == "fixture"]
    assert [n.label for n in fixtures] == ["prices"]
    assert fixtures[0].edge == "fixture"
    assert fixtures[0].depth == 1


def test_shared_state_appears_as_touches(nav):
    explained = nav.explain("tests/test_shop.py::TestRegistry::test_register")
    touched = [n for n in explained.tree.root.walk() if n.edge == "touches"]
    assert touched, "the sample's module-level _registry must show up"
    assert "_registry" in {n.label for n in touched}
    assert all(n.kind == "global" for n in touched)


def test_smells_appear_as_leaves_with_a_location(nav):
    explained = nav.explain("tests/test_shop.py::test_job_finishes")
    smells = [n for n in explained.tree.root.walk() if n.kind == "smell"]
    assert smells, "slow_job sleeps; the tree must carry that"
    assert any(n.label.startswith("time.sleep") for n in smells)
    assert all(n.edge == "smells" for n in smells)


def test_stats_describe_the_shape(nav):
    explained = nav.explain("tests/test_shop.py::test_total")
    stats = explained.tree.stats()
    assert stats["nodes"] == explained.tree.root.size()
    assert stats["edges"] == stats["nodes"] - 1
    assert stats["max_depth"] >= 1
    assert stats["files_touched"] >= 1
    assert sum(stats["nodes_by_depth"].values()) == stats["nodes"]
    assert sum(stats["nodes_by_kind"].values()) == stats["nodes"]


def test_rows_are_a_valid_parent_table(nav):
    """Plotly's treemap needs every parent to exist and only the root empty."""
    explained = nav.explain("tests/test_shop.py::test_total")
    rows = explained.tree.rows()
    ids = {row["id"] for row in rows}
    roots = [row for row in rows if row["parent"] == ""]
    assert len(roots) == 1
    for row in rows:
        assert row["parent"] == "" or row["parent"] in ids


def test_render_is_readable(nav):
    explained = nav.explain("tests/test_shop.py::test_total")
    text = explained.tree.render()
    assert text.startswith("TEST  tests/test_shop.py::test_total")
    assert "[calls]" in text
    assert len(text.splitlines()) == explained.tree.stats()["nodes"]


# -------------------------------------------------- building without a trace


def test_tree_from_a_bare_navresult_is_flat_but_correct():
    """Loading a result from disk loses provenance, not correctness."""
    chunk = Chunk(
        chunk_id="r@s:src/shop.py:10-12",
        path="src/shop.py",
        start_line=10,
        end_line=12,
        kind="function",
        text="def total(prices):\n    return sum(prices)",
        score=1.0,
    )
    result = NavResult(
        test_id="tests/test_shop.py::test_total",
        code_under_test=[chunk],
        smells=["time.sleep (src/shop.py:11)"],
    )
    tree = build_tree(result)
    assert isinstance(tree, KnowledgeTree)
    node = next(n for n in tree.root.walk() if n.kind == "function")
    assert node.label == "total"
    assert node.edge == "reaches", "unknown edge must be named, not guessed"
    assert node.depth == 1
    smell = next(n for n in tree.root.walk() if n.kind == "smell")
    assert smell.label == "time.sleep"
    assert smell.path == "src/shop.py"
    assert smell.start_line == 11


def test_provenance_parents_a_node_under_another():
    """An ``expands`` edge must hang under the definition it came from."""
    parent = Chunk(
        chunk_id="r@s:src/c.py:5-9",
        path="src/c.py",
        start_line=5,
        end_line=9,
        kind="class",
        text="class TTLCache(_TimedCache):\n    pass",
        score=2.0,
    )
    child = Chunk(
        chunk_id="r@s:src/c.py:1-3",
        path="src/c.py",
        start_line=1,
        end_line=3,
        kind="class",
        text="class _TimedCache:\n    pass",
        score=0.45,
    )
    provenance = {
        ("src/c.py", 5): Provenance(edge="calls", via="jedi", depth=1),
        ("src/c.py", 1): Provenance(
            edge="expands", via="jedi", depth=2, parent="src/c.py:5"
        ),
    }
    tree = build_tree(
        NavResult(test_id="t::x", code_under_test=[child, parent]), provenance
    )
    top = [n for n in tree.root.children if n.kind == "class"]
    assert [n.label for n in top] == ["TTLCache"]
    assert [n.label for n in top[0].children] == ["_TimedCache"]
    assert top[0].children[0].depth == 2
    assert tree.stats()["max_depth"] == 2


def test_label_reads_the_name_off_a_decorated_definition():
    chunk = Chunk(
        chunk_id="r@s:tests/conftest.py:3-6",
        path="tests/conftest.py",
        start_line=3,
        end_line=6,
        kind="fixture",
        text='@pytest.fixture(scope="module")\ndef shared_cart():\n    return []',
        score=0.8,
    )
    tree = build_tree(NavResult(test_id="t::x", fixtures=[chunk]))
    assert tree.root.children[0].label == "shared_cart"


def test_label_reads_the_name_off_an_assignment():
    """jedi.goto on a global resolves to the statement that binds it."""
    chunk = Chunk(
        chunk_id="r@s:src/shop.py:13-13",
        path="src/shop.py",
        start_line=13,
        end_line=13,
        kind="global",
        text="JOB_DONE = False",
        score=1.0,
    )
    tree = build_tree(NavResult(test_id="t::x", shared_state=[chunk]))
    assert tree.root.children[0].label == "JOB_DONE"


def test_children_sort_nearest_edge_first():
    node = TreeNode(node_id="root", kind="test", label="t::x")
    node.children = [
        TreeNode(node_id="c", kind="smell", label="sleep", edge="smells"),
        TreeNode(node_id="b", kind="class", label="Deep", edge="expands", score=0.45),
        TreeNode(node_id="a", kind="function", label="Near", edge="calls", score=2.0),
    ]
    node.sort()
    assert [c.label for c in node.children] == ["Near", "Deep", "sleep"]


# ------------------------------------------------- replay: step -> tree node


def test_kept_is_a_number_not_none(nav):
    """`record()` once fell off the end without returning, so every event
    reported kept=None and the 'definitions returned vs kept' column -- the
    one that shows where precision comes from -- was empty."""
    explained = nav.explain("tests/test_shop.py::test_total")
    for event in explained.trace.events:
        assert isinstance(event.kept, int), f"step {event.seq} kept={event.kept!r}"
    assert sum(e.kept for e in explained.trace.events) > 0


def test_steps_report_which_nodes_they_produced(nav):
    """A replay grows the tree in step with the trace, so each step has to
    say which nodes it added. Without this the mapping can only be guessed."""
    explained = nav.explain("tests/test_shop.py::test_total")
    produced = [e for e in explained.trace.events if e.produced]
    assert produced, "no step reported producing anything"

    # Every key a step claims must correspond to a node that is in the tree.
    node_keys = set()
    for node in explained.tree.root.walk():
        if node.kind == "smell":
            node_keys.add(f"smell:{node.label}")
        elif node.path:
            node_keys.add(f"{node.path}:{node.start_line}")

    claimed = {key for event in produced for key in event.produced}
    unknown = claimed - node_keys
    assert not unknown, f"steps claimed nodes that are not in the tree: {unknown}"


def test_every_resolved_node_is_claimed_by_some_step(nav):
    """The other direction: a node nobody claims would never appear in a
    replay, so it would be invisible however long you let it run."""
    explained = nav.explain("tests/test_shop.py::test_total")
    claimed = {
        key for event in explained.trace.events for key in event.produced
    }
    for node in explained.tree.root.walk():
        if node.depth == 0:
            continue  # the root is the test, nothing "produces" it
        key = (
            f"smell:{node.label}"
            if node.kind == "smell"
            else f"{node.path}:{node.start_line}"
        )
        assert key in claimed, f"{node.label} ({key}) is never produced by a step"


def test_produced_keys_are_ordered_by_when_they_were_found(nav):
    """The first step to claim a node is the one a replay should reveal it
    on, so claims must arrive in trace order."""
    explained = nav.explain("tests/test_shop.py::test_total")
    first_seen: dict[str, int] = {}
    for event in explained.trace.events:
        for key in event.produced:
            first_seen.setdefault(key, event.seq)
    assert first_seen
    assert list(first_seen.values()) == sorted(first_seen.values())

"""The AST + Jedi analysis finds the shared state in the demo_inventory fixture."""

from __future__ import annotations

from pathlib import Path

from flakeguard.console.analysis import analyse_repo, shared_links

FIXTURE = Path(__file__).parent / "data" / "demo_inventory"


def test_finds_the_module_level_dict_and_its_writer_and_reader():
    analysis = analyse_repo(FIXTURE)
    assert [(s.name, s.file, s.line) for s in analysis.states] == [("CACHE", "src/inventory/cache.py", 3)]
    (link,) = shared_links(analysis)
    assert link.writers == ("tests/test_warmup.py::test_cache_warm",)
    assert link.readers == ("tests/test_report.py::test_report_total",)


def test_every_access_points_at_a_real_line_that_names_the_state():
    analysis = analyse_repo(FIXTURE)
    assert analysis.accesses
    for a in analysis.accesses:
        text = (FIXTURE / a.file).read_text(encoding="utf-8").splitlines()[a.line - 1]
        assert a.state.name in text, f"{a.file}:{a.line} does not mention {a.state.name}"
    by_kind = {a.kind: (a.file, a.line, a.via) for a in analysis.accesses}
    assert by_kind["write"] == ("src/inventory/cache.py", 7, ("warm",))
    assert by_kind["read"] == ("src/inventory/report.py", 11, ("total",))


def test_a_test_that_touches_no_shared_state_has_no_access():
    analysis = analyse_repo(FIXTURE)
    touched = {a.test_id for a in analysis.accesses}
    assert "tests/test_report.py::test_report_empty" not in touched
    assert "tests/test_stock.py::test_reserve_ok" not in touched

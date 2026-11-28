"""Tests for the knowledge-tree export: the case loader and the gate's input.

The export script is a pipeline stage, so a quiet mistake in it does not
crash -- it produces a results file that the quality gate then reads as
truth. These tests cover the two ways that has actually gone wrong.
"""

import json
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import export_knowledge_trees as export  # noqa: E402


def write(tmp_path: Path, name: str, payload) -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


# ------------------------------------------------------------ both formats


def test_reads_labels_json_format(tmp_path):
    """labels/labels.json is a flat list keyed 'id'."""
    path = write(
        tmp_path,
        "labels.json",
        [
            {"id": "t/test_a.py::test_one", "label": "flaky", "root_cause": "timing"},
            {"id": "t/test_a.py::test_two", "label": "stable", "root_cause": "none"},
        ],
    )
    cases = export.load_cases(path)
    assert [c["id"] for c in cases] == ["t/test_a.py::test_one", "t/test_a.py::test_two"]
    assert cases[0]["label"] == "flaky"
    assert cases[0]["root_cause"] == "timing"


def test_reads_nav_gold_format(tmp_path):
    """A nav gold set nests its cases under 'tests', keyed 'test_id'.

    Reading the top level of this file instead of its 'tests' key is the bug
    that produced nine junk tree files named after metadata keys.
    """
    path = write(
        tmp_path,
        "nav-gold.json",
        {
            "repo": "cachetools",
            "sha": "3c082c6",
            "labelled_by": "B",
            "method": "by hand",
            "tests": [
                {"test_id": "tests/test_lru.py::LRUCacheTest::test_lru"},
                {"test_id": "tests/test_ttl.py::TTLCacheTest::test_ttl"},
            ],
        },
    )
    cases = export.load_cases(path)
    assert [c["id"] for c in cases] == [
        "tests/test_lru.py::LRUCacheTest::test_lru",
        "tests/test_ttl.py::TTLCacheTest::test_ttl",
    ]
    # The metadata keys must not have become cases.
    assert not any(c["id"] in {"repo", "sha", "method"} for c in cases)


# ------------------------------------------------------------- the guards


def test_rejects_an_id_that_is_not_a_node_id(tmp_path):
    """The guard that stops metadata keys being treated as test cases."""
    path = write(tmp_path, "bad.json", [{"id": "repo"}, {"id": "sha"}])
    with pytest.raises(ValueError, match="not a pytest node id"):
        export.load_cases(path)


def test_rejects_a_case_with_no_id(tmp_path):
    path = write(tmp_path, "bad.json", [{"label": "flaky"}])
    with pytest.raises(ValueError, match="neither 'id' nor 'test_id'"):
        export.load_cases(path)


def test_rejects_a_non_list_of_cases(tmp_path):
    path = write(tmp_path, "bad.json", {"tests": {"not": "a list"}})
    with pytest.raises(ValueError, match="expected a list of cases"):
        export.load_cases(path)


# ----------------------------------------------------------- the filenames


@pytest.mark.parametrize(
    "case_id",
    [
        "tests/test_ttl.py::TTLCacheTest::test_ttl",
        "synthetic/tests/test_suite_02.py::test_case_13",
        "tests/test_x.py::test_param[1-2]",
        r"tests\windows\test_y.py::test_z",
    ],
)
def test_safe_name_survives_windows(case_id):
    """Node ids contain ':' and '/', neither of which is a legal filename."""
    name = export.safe_name(case_id)
    assert not set(name) & set(':/\\<>"|?*'), f"{name!r} is not a legal filename"
    assert name


def test_safe_name_is_unique_per_case():
    ids = [
        "tests/test_a.py::test_one",
        "tests/test_b.py::test_one",
        "tests/test_a.py::Class::test_one",
    ]
    assert len({export.safe_name(i) for i in ids}) == len(ids)


# -------------------------------------------------- the exported CSV shape


def test_csv_fields_cover_what_the_gate_reads():
    """The gate reads nav_trace_summary.json, the dashboard reads this CSV.

    Dropping a column here breaks a chart silently, so the contract between
    the export and its consumers is asserted rather than assumed.
    """
    required = {
        "case_id",
        "tree_nodes",
        "tree_max_depth",
        "ast_names",
        "jedi_goto_calls",
        "jedi_infer_calls",
        "jedi_calls",
        "jedi_hits",
        "jedi_hit_rate",
        "nodes_depth_1",
        "nodes_depth_2plus",
        "elapsed_ms",
    }
    missing = required - set(export.CSV_FIELDS)
    assert not missing, f"the export no longer writes {sorted(missing)}"


def test_row_for_reports_the_tree_and_the_trace():
    """One real navigation, folded into a CSV row."""
    from flakeguard.navigator.ast_nav import AstNavigator

    sample = Path(__file__).parent / "data" / "navsample"
    nav = AstNavigator(sample, repo="navsample", sha="test")
    explained = nav.explain("tests/test_shop.py::test_total")

    row = export.row_for(
        {"id": "tests/test_shop.py::test_total", "label": "flaky", "root_cause": "timing"},
        explained,
        elapsed_ms=12.5,
    )
    assert set(row) == set(export.CSV_FIELDS)
    assert row["case_id"] == "tests/test_shop.py::test_total"
    assert row["label"] == "flaky"
    assert row["tree_nodes"] >= 2
    assert row["tree_edges"] == row["tree_nodes"] - 1
    assert row["ast_names"] > 0
    assert row["jedi_calls"] == row["jedi_goto_calls"] + row["jedi_infer_calls"]
    assert 0.0 <= row["jedi_hit_rate"] <= 1.0
    assert row["elapsed_ms"] == 12.5

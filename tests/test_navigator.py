"""Unit tests for the AST + jedi navigator.

Everything runs against tests/data/navsample, a sample project small enough
that the expected answer can be checked by eye. No network, no cachetools
checkout, so this passes in CI.
"""

from pathlib import Path

import pytest

from flakeguard.contracts import NavResult
from flakeguard.navigator.ast_nav import AstNavigator, parse_test_id

SAMPLE = Path(__file__).parent / "data" / "navsample"


@pytest.fixture(scope="module")
def nav():
    return AstNavigator(SAMPLE, repo="navsample", sha="test")


def paths(chunks):
    return {c.path for c in chunks}


def texts(chunks):
    return "\n".join(c.text for c in chunks)


# ----------------------------------------------------------- id parsing


@pytest.mark.parametrize(
    "test_id,expected",
    [
        ("tests/test_shop.py::test_total", ("tests/test_shop.py", ["test_total"])),
        (
            "tests/test_shop.py::TestRegistry::test_register",
            ("tests/test_shop.py", ["TestRegistry", "test_register"]),
        ),
        # pytest appends the parameter set; the navigator must ignore it.
        ("tests/test_shop.py::test_total[1-2]", ("tests/test_shop.py", ["test_total"])),
    ],
)
def test_parse_test_id(test_id, expected):
    assert parse_test_id(test_id) == expected


def test_parse_test_id_rejects_empty():
    with pytest.raises(ValueError):
        parse_test_id("::test_total")


# ------------------------------------------------------- code under test


def test_finds_code_under_test(nav):
    result = nav.related("tests/test_shop.py::test_total")
    assert isinstance(result, NavResult)
    assert "src/shop.py" in paths(result.code_under_test)
    body = texts(result.code_under_test)
    assert "def total(" in body
    assert "def set_discount(" in body


def test_chunk_id_follows_the_contract(nav):
    chunk = nav.related("tests/test_shop.py::test_total").code_under_test[0]
    assert chunk.chunk_id.startswith("navsample@test:")
    assert chunk.chunk_id.endswith(f"{chunk.start_line}-{chunk.end_line}")
    assert chunk.path in chunk.chunk_id


def test_handles_a_test_inside_a_class(nav):
    result = nav.related("tests/test_shop.py::TestRegistry::test_register")
    assert "def register(" in texts(result.code_under_test)


def test_finds_a_test_inherited_from_a_mixin(nav):
    """pytest reports an inherited test under the concrete class.

    The body lives in the base, so looking only in the named class finds
    nothing. Caught by the held-out gold set: three of its eight tests
    scored zero on every metric because of this, and cachetools puts 23
    tests in CacheTestMixin alone.
    """
    result = nav.related("tests/test_shop.py::TestViaMixin::test_total_via_mixin")
    assert "def total(" in texts(result.code_under_test)


# -------------------------------------------------------------- fixtures


def test_resolves_fixtures_from_conftest(nav):
    result = nav.related("tests/test_shop.py::test_total")
    assert "def prices(" in texts(result.fixtures)
    assert all(c.kind == "fixture" for c in result.fixtures)
    assert all(c.path == "tests/conftest.py" for c in result.fixtures)


def test_fixture_chunk_includes_the_decorator(nav):
    """scope="module" is shared state, so it must be inside the chunk."""
    result = nav.related("tests/test_shop.py::test_cart_grows")
    cart = [c for c in result.fixtures if "def shared_cart(" in c.text][0]
    assert 'scope="module"' in cart.text


def test_resolves_several_fixtures(nav):
    result = nav.related("tests/test_shop.py::test_cart_grows")
    found = texts(result.fixtures)
    assert "def shared_cart(" in found
    assert "def prices(" in found


def test_no_fixtures_when_test_takes_no_arguments(nav):
    assert nav.related("tests/test_shop.py::test_job_finishes").fixtures == []


# ---------------------------------------------------------- shared state


def test_finds_module_level_mutable_state(nav):
    result = nav.related("tests/test_shop.py::test_total")
    found = texts(result.shared_state)
    # A float rebound with ``global`` counts: this is the JOB_DONE case.
    assert "_discount = 0.0" in found
    assert "_cache = " in found or "_registry = " in found


def test_ignores_module_level_constants(nav):
    result = nav.related("tests/test_shop.py::test_total")
    assert "RATE_LIMIT" not in texts(result.shared_state)


# ------------------------------------------------------------------ smells


def smell_names(smells):
    """Smells are reported as "name (path:line)"."""
    return {s.split(" (", 1)[0] for s in smells}


def test_detects_randomness_smell(nav):
    result = nav.related("tests/test_shop.py::test_discount_is_small")
    assert "random." in smell_names(result.smells)


def test_detects_sleep_smell(nav):
    result = nav.related("tests/test_shop.py::test_job_finishes")
    assert "time.sleep" in smell_names(result.smells)


def test_smell_carries_where_it_was_found(nav):
    """A bare name is not evidence; the LLM has to be able to cite it."""
    result = nav.related("tests/test_shop.py::test_job_finishes")
    sleep = [s for s in result.smells if s.startswith("time.sleep")][0]
    assert "src/shop.py:" in sleep


def test_detects_a_smell_in_setup(nav):
    """setUp runs before every test in the class, so its randomness is theirs.

    Found by scoring tenacity: its after-log tests pick a log level with
    random.choice in setUp, and the body alone looks deterministic.
    """
    result = nav.related("tests/test_shop.py::TestWithSetUp::test_uses_setup_value")
    assert "random." in smell_names(result.smells)


def test_clean_test_has_no_smells(nav):
    assert nav.related("tests/test_shop.py::test_total").smells == []


# ------------------------------------------------------- failure handling


@pytest.mark.parametrize(
    "test_id",
    [
        "tests/does_not_exist.py::test_x",
        "tests/test_shop.py::test_not_here",
        "tests/test_shop.py::NoSuchClass::test_x",
    ],
)
def test_missing_targets_return_empty_not_crash(nav, test_id):
    """The contract says related() answers for any id. CI must never crash."""
    result = nav.related(test_id)
    assert result.test_id == test_id
    assert result.code_under_test == []


def test_test_chunk_returns_the_test_body(nav):
    chunk = nav.test_chunk("tests/test_shop.py::test_total")
    assert chunk is not None
    assert chunk.kind == "test"
    assert "def test_total(" in chunk.text


def test_test_chunk_is_none_for_a_missing_test(nav):
    assert nav.test_chunk("tests/test_shop.py::test_nope") is None


# --------------------------------------------- dependencies are not our code


def test_a_virtualenv_inside_the_repo_is_not_code_under_test(tmp_path):
    """A .venv sits inside the checkout, so "is this path under the repo?"
    says yes to every installed package.

    Found by looking at a real tree: ``@freeze_time`` made jedi resolve into
    ``.venv/Lib/site-packages/freezegun/api.py``, and eleven of twenty chunks
    for one case were freezegun internals. The evidence bundle carries only
    the top few chunks, so third-party source does not just add noise — it
    pushes the real answer out of the bundle entirely.
    """
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "shop.py").write_text(
        "TOTALS = []\n\n\ndef total(prices):\n    return sum(prices)\n",
        encoding="utf-8",
    )
    # A dependency, installed where a virtualenv would put it.
    vendor = tmp_path / ".venv" / "Lib" / "site-packages" / "vendorlib"
    vendor.mkdir(parents=True)
    (vendor / "__init__.py").write_text(
        "CACHE = {}\n\n\ndef helper(x):\n    return x\n", encoding="utf-8"
    )
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_shop.py").write_text(
        "import shop\nimport vendorlib\n\n\n"
        "def test_total():\n"
        "    assert vendorlib.helper(shop.total([1.0])) == 1.0\n",
        encoding="utf-8",
    )

    navigator = AstNavigator(tmp_path, repo="sample", sha="test")
    result = navigator.related("tests/test_shop.py::test_total")

    reached = [c.path for c in result.code_under_test + result.shared_state]
    assert reached, "the navigator found nothing at all"
    assert not any("site-packages" in p for p in reached), (
        f"a dependency reached the result: {reached}"
    )
    assert not any(p.startswith(".venv") for p in reached), reached
    # ...and the project's own code is still found.
    assert any(p.endswith("shop.py") for p in reached), reached


@pytest.mark.parametrize(
    "vendor_dir", ["node_modules", ".tox", "venv", ".eggs", "dist-packages"]
)
def test_other_vendor_directories_are_excluded_too(tmp_path, vendor_dir):
    from flakeguard.navigator.ast_nav import _is_within

    root = tmp_path.resolve()
    assert not _is_within(root / vendor_dir / "pkg" / "mod.py", root)
    assert _is_within(root / "src" / "mod.py", root)

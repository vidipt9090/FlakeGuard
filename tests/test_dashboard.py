"""Smoke tests: every dashboard page must render without raising.

A Streamlit page fails at *render* time, in a browser, which means a broken
page looks fine to `pytest` and fine to `ruff` and only shows up when someone
opens it -- usually during the demo. Streamlit's own test harness runs the
script the way the server does, so these catch that class of break in CI.

They are smoke tests on purpose. They assert that each page renders and that
the headline numbers reach the page, not that any particular chart looks
right; a layout assertion would break on every deliberate design change and
teach everyone to ignore it.

Both themes are exercised, because the palettes are separate code paths and
a missing token only raises in the theme that uses it.
"""

from pathlib import Path

import pytest

pytest.importorskip("streamlit", reason="dashboard tests need streamlit")

from streamlit.testing.v1 import AppTest  # noqa: E402

APP = Path(__file__).resolve().parents[1] / "flakeguard" / "app" / "dashboard.py"

# Substrings, not the full labels: the emoji and wording are presentation and
# are allowed to change without breaking the test.
PAGES = [
    "Overview",
    "Dataset",
    "Knowledge Tree",
    "AST",
    "Results",
    "Case Explorer",
    "Failures",
    "CI/CD Pipeline",
    "Roadmap",
]

TIMEOUT = 240


def _app() -> AppTest:
    app = AppTest.from_file(str(APP), default_timeout=TIMEOUT)
    app.run()
    assert not app.exception, [str(e.value) for e in app.exception]
    return app


def _goto(app: AppTest, needle: str) -> AppTest:
    """Switch to the page whose label contains ``needle``."""
    options = list(app.radio[0].options)
    match = next((label for label in options if needle in label), None)
    assert match is not None, f"no page matching {needle!r} in {options}"
    app.radio[0].set_value(match).run()
    return app


def test_the_app_boots():
    app = _app()
    assert len(app.radio[0].options) == len(PAGES)


@pytest.mark.parametrize("page", PAGES)
def test_every_page_renders(page):
    app = _goto(_app(), page)
    assert not app.exception, [str(e.value) for e in app.exception]


@pytest.mark.parametrize("page", ["Knowledge Tree", "AST", "CI/CD Pipeline", "Results"])
def test_the_new_pages_render_in_light_theme(page):
    """The light palette is a separate dict; a missing token only raises there."""
    app = _app()
    app.radio[1].set_value("☀️ Light").run()
    assert not app.exception, [str(e.value) for e in app.exception]
    app = _goto(app, page)
    assert not app.exception, [str(e.value) for e in app.exception]


def test_knowledge_tree_page_shows_a_tree():
    """The rendered tree must actually reach the page, not just not crash."""
    app = _goto(_app(), "Knowledge Tree")
    blocks = [block.value for block in app.code]
    assert any("TEST  " in text for text in blocks), (
        "the text form of the knowledge tree is missing from the page"
    )
    assert any("[calls]" in text or "[touches]" in text for text in blocks), (
        "the tree rendered with no edges on it"
    )


def test_trace_page_offers_a_step_player():
    """The point of the page is stepping through navigation, so the slider
    has to exist and span more than one step."""
    app = _goto(_app(), "AST")
    assert app.slider, "the trace page has no step slider"
    step = app.slider[0]
    assert step.max > 1, f"only {step.max} step(s) to replay"


def test_cicd_page_reports_the_gate_verdict():
    app = _goto(_app(), "CI/CD Pipeline")
    body = " ".join(block.value for block in app.markdown)
    assert "PROMOTE" in body or "BLOCKED" in body, (
        "the CI/CD page did not report a gate verdict"
    )


def test_results_page_surfaces_the_false_quarantine_caveat():
    """Guards a finding, not a layout.

    The best prompt reaches recall 1.0 by calling every real bug flaky. A
    results page that shows F1 without that is misleading, so the caveat is
    treated as part of the result and tested like one.
    """
    app = _goto(_app(), "Results")
    body = " ".join(block.value for block in app.markdown)
    assert "false-quarantine" in body.lower() or "false quarantine" in body.lower(), (
        "the false-quarantine caveat is not on the results page"
    )

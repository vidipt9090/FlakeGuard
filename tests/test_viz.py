"""Tests for the chart layer's colour and encoding rules.

These guard decisions, not appearance. The navigator pages have nine phases
and eight edge types, and the tempting thing to do with those is give each one
a colour. Nobody can tell nine hues apart, and a validated palette cannot
separate that many on a scatter at all, so the rule is:

  * identity is carried by **position** (a row per phase, a column per depth)
  * the only categorical colour is the two-way AST / jedi split
  * everything else coloured is a magnitude and uses one sequential ramp

A test is the right place for that because the failure mode is a well-meant
commit adding a per-phase palette, which looks like an improvement and is not.
"""

from pathlib import Path

import pytest

from flakeguard.app import viz

pytest.importorskip("plotly", reason="chart tests need plotly")
pytest.importorskip("streamlit", reason="pages_nav imports streamlit")

from flakeguard.app import pages_nav  # noqa: E402

# A stand-in theme: every token the same colour, so any hue a figure carries
# must have come from the palette rather than the theme.
THEME = dict.fromkeys(
    [
        "plot_bg", "plot_grid", "plot_text", "plot_axis", "plot_legend_bg",
        "plot_legend_bd", "accent", "text", "text_soft", "text_muted",
        "text_faint", "card_bg", "card_border", "evidence_bg",
        "evidence_tag_bg", "sec_border",
    ],
    "#000000",
)

SAMPLE = Path(__file__).parent / "data" / "navsample"


@pytest.fixture(scope="module")
def explained():
    from flakeguard.navigator.ast_nav import AstNavigator

    nav = AstNavigator(SAMPLE, repo="navsample", sha="test")
    return nav.explain("tests/test_shop.py::test_total")


# --------------------------------------------------------------- the palette


@pytest.mark.parametrize("dark", [True, False])
def test_exactly_two_categorical_hues_exist(dark):
    """Two, because that is what survives the all-pairs CVD checks."""
    palette = viz.resolvers(dark)
    assert set(palette) == {"ast", "jedi"}
    assert len(set(palette.values())) == 2


def _relative_luminance(hex_color: str) -> float:
    channels = []
    for i in (1, 3, 5):
        c = int(hex_color[i: i + 2], 16) / 255
        channels.append(c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4)
    r, g, b = channels
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast(a: str, b: str) -> float:
    la, lb = _relative_luminance(a), _relative_luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


@pytest.mark.parametrize("dark", [True, False])
@pytest.mark.parametrize("marks", [True, False])
def test_the_sequential_ramp_is_one_hue_and_monotonic(dark, marks):
    """Sequential means light to dark in a single hue, never a rainbow."""
    ramp = viz.gold_scale(dark, marks)
    assert len(ramp) >= 4
    lums = [_relative_luminance(step) for step in ramp]
    # Light theme runs light -> dark, dark theme dark -> light. Either way it
    # must be monotonic, or "more" stops reading as further from the surface.
    assert lums == sorted(lums) or lums == sorted(lums, reverse=True), lums


@pytest.mark.parametrize(
    "dark,surface", [(False, "#ffffff"), (True, "#0d0b1a")]
)
def test_every_mark_step_clears_three_to_one(dark, surface):
    """A dot or a bar has to be visible against the surface it sits on.

    The full-range ramp is for area fills; its pale end measures 1.27:1 on
    white, which for a 9px dot means the mark is not there. Marks get their
    own steps and this is the floor they exist to hold.
    """
    for step in viz.gold_scale(dark, marks=True):
        ratio = _contrast(step, surface)
        assert ratio >= 3.0, f"{step} is {ratio:.2f}:1 on {surface}"


@pytest.mark.parametrize("dark", [True, False])
@pytest.mark.parametrize("marks", [True, False])
def test_depth_color_stays_on_the_ramp(dark, marks):
    ramp = set(viz.gold_scale(dark, marks))
    for max_depth in (0, 1, 2, 5):
        for depth in range(max_depth + 1):
            assert viz.depth_color(depth, max_depth, dark, marks) in ramp


def test_status_colors_are_not_reused_as_series():
    """Reserved colours stay reserved."""
    series = set(viz.RESOLVER_LIGHT.values()) | set(viz.RESOLVER_DARK.values())
    series |= set(viz.GOLD_LIGHT) | set(viz.GOLD_DARK)
    series |= set(viz.GOLD_MARKS_LIGHT) | set(viz.GOLD_MARKS_DARK)
    assert not (series & set(viz.STATUS.values()))


def test_every_edge_and_phase_is_documented():
    """A new edge or phase must arrive with its explanation, or the table and
    the tooltip silently show a blank."""
    from flakeguard.navigator.knowledge_tree import EDGE_ORDER
    from flakeguard.navigator.trace import PHASES

    for edge in EDGE_ORDER:
        assert viz.EDGE_HELP.get(edge), f"edge {edge!r} has no explanation"
        assert viz.EDGE_SYMBOL.get(edge), f"edge {edge!r} has no marker shape"
    for phase in PHASES:
        assert viz.PHASE_HELP.get(phase), f"phase {phase!r} has no explanation"


def test_edge_shapes_are_distinct():
    """Shape is the secondary encoding, so it must actually discriminate."""
    shapes = list(viz.EDGE_SYMBOL.values())
    assert len(shapes) == len(set(shapes))


# -------------------------------------------------------------- the geometry


def test_layout_places_every_node_with_depth_on_x(explained):
    rows = explained.tree.rows()
    nodes, edges = viz.layout_nodes(rows)
    assert len(nodes) == len(rows)
    assert len(edges) == len(rows) - 1, "a tree has exactly n-1 edges"
    for node in nodes:
        assert node["x"] == node["depth"], "x must be hop depth, not an index"
        assert "y" in node


def test_layout_centres_a_parent_on_its_children():
    rows = [
        {"id": "r", "parent": "", "depth": 0, "label": "root", "kind": "test",
         "edge": "root", "via": "-", "score": 0, "path": "", "start_line": 0,
         "end_line": 0, "lines": 0, "detail": ""},
        {"id": "a", "parent": "r", "depth": 1, "label": "a", "kind": "function",
         "edge": "calls", "via": "jedi", "score": 1, "path": "x.py",
         "start_line": 1, "end_line": 2, "lines": 2, "detail": ""},
        {"id": "b", "parent": "r", "depth": 1, "label": "b", "kind": "function",
         "edge": "calls", "via": "jedi", "score": 1, "path": "x.py",
         "start_line": 5, "end_line": 6, "lines": 2, "detail": ""},
    ]
    nodes, _ = viz.layout_nodes(rows)
    by_id = {n["id"]: n for n in nodes}
    assert by_id["r"]["y"] == pytest.approx(
        (by_id["a"]["y"] + by_id["b"]["y"]) / 2
    )


def test_layout_survives_a_single_node_tree():
    rows = [
        {"id": "r", "parent": "", "depth": 0, "label": "root", "kind": "test",
         "edge": "root", "via": "-", "score": 0, "path": "", "start_line": 0,
         "end_line": 0, "lines": 0, "detail": ""}
    ]
    nodes, edges = viz.layout_nodes(rows)
    assert len(nodes) == 1 and edges == []


# --------------------------------------------------------------- the figures


@pytest.mark.parametrize("dark", [True, False])
def test_node_link_uses_only_the_two_resolver_hues(explained, dark):
    figure = pages_nav._node_link_figure(explained.tree.rows(), THEME, dark)
    allowed = set(viz.resolvers(dark).values())
    used = {
        trace.marker.color
        for trace in figure.data
        if trace.name and isinstance(trace.marker.color, str)
    }
    assert used <= allowed, f"a hue outside the validated pair: {used - allowed}"
    assert "hops" in figure.layout.xaxis.title.text, "the x axis must say it is depth"


@pytest.mark.parametrize("dark", [True, False])
def test_node_link_names_its_series(explained, dark):
    """Two series means a legend is required; identity is never colour alone."""
    figure = pages_nav._node_link_figure(explained.tree.rows(), THEME, dark)
    named = [t.name for t in figure.data if t.name]
    assert named, "the resolver split must be a named series"
    assert all("AST" in n or "jedi" in n for n in named)
    # ...and the nodes carry text labels, which is the direct-label rule.
    assert any("text" in (t.mode or "") for t in figure.data if t.name)


@pytest.mark.parametrize("dark", [True, False])
def test_icicle_colours_come_from_the_sequential_ramp(explained, dark):
    figure = pages_nav._icicle_figure(explained.tree.rows(), THEME, dark)
    assert figure.data[0].type == "icicle"
    assert set(figure.data[0].marker.colors) <= set(viz.gold_scale(dark))


def test_raster_puts_phases_on_rows_not_on_hues(explained):
    """The core encoding decision, asserted."""
    events = [e.to_dict() for e in explained.trace.events]
    figure = pages_nav._raster_figure(events, len(events), THEME, True)

    rows = list(figure.layout.yaxis.ticktext)
    assert len(rows) >= 3, "phases must occupy separate rows"
    assert all(phase in viz.PHASE_HELP for phase in rows)

    done = next(t for t in figure.data if t.name == "run so far")
    assert set(done.marker.color) <= set(viz.gold_scale(True, marks=True)), (
        "the raster coloured something other than depth"
    )


def test_raster_marks_the_current_step(explained):
    events = [e.to_dict() for e in explained.trace.events]
    figure = pages_nav._raster_figure(events, 2, THEME, True)
    assert figure.layout.shapes, "the step cursor is missing"


def test_hit_figure_separates_resolved_from_unresolved(explained):
    events = [e.to_dict() for e in explained.trace.events]
    figure = pages_nav._hit_figure(events, THEME, True)
    names = [t.name for t in figure.data]
    assert "resolved to a definition" in names
    assert figure.layout.barmode == "stack"


def test_no_figure_uses_two_y_axes(explained):
    """A dual-axis chart is the one form that is always wrong."""
    events = [e.to_dict() for e in explained.trace.events]
    rows = explained.tree.rows()
    figures = [
        pages_nav._node_link_figure(rows, THEME, True),
        pages_nav._icicle_figure(rows, THEME, True),
        pages_nav._depth_bar_figure(rows, THEME, True),
        pages_nav._raster_figure(events, len(events), THEME, True),
        pages_nav._trace_depth_figure(events, THEME, True),
        pages_nav._hit_figure(events, THEME, True),
    ]
    for figure in figures:
        assert "yaxis2" not in figure.layout, "dual axis found"
        assert not any(getattr(t, "yaxis", None) == "y2" for t in figure.data)


@pytest.mark.parametrize("dark,surface", [(False, "#ffffff"), (True, "#0d0b1a")])
def test_tree_edges_are_visible_but_subordinate(dark, surface):
    """Edges are what make it a tree; in the grid colour they vanished."""
    ratio = _contrast(viz.tree_edge(dark), surface)
    assert ratio >= 1.4, f"edge is {ratio:.2f}:1 on {surface} — invisible"
    # ...and still quieter than the marks sitting on top of them.
    faintest_mark = min(
        _contrast(step, surface) for step in viz.gold_scale(dark, marks=True)
    )
    assert ratio < faintest_mark, "edges must not compete with the nodes"


def test_node_link_uses_the_edge_colour_not_the_grid(explained):
    figure = pages_nav._node_link_figure(explained.tree.rows(), THEME, True)
    lines = [t for t in figure.data if t.mode == "lines"]
    assert lines, "the tree drew no edges"
    assert lines[0].line.color == viz.tree_edge(True)

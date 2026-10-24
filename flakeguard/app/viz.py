"""Chart tokens, data loading and figure builders for the navigator pages.

Kept out of ``dashboard.py`` so the page code reads as layout rather than as
plotly boilerplate, and so the colour decisions live in exactly one place.

Colour policy, decided once here:

*Identity never rides on more than two hues.* The pages have up to nine
navigation phases and eight edge types, which is far past the number of
categorical hues anyone can tell apart -- and past what a validated palette
can separate on a scatter. So phase and edge identity are carried by
**position** (a row per phase, a column per depth) and the only categorical
colour in the whole set is the two-way split that actually matters:

    AST found it  (blue)      vs    jedi found it  (orange)

That pair clears every check in both themes, all pairs, including colour-vision
deficiency separation. Everything else that is coloured is a *magnitude* --
hop depth, or a count -- and gets the brand gold as a single-hue sequential
ramp, light to dark, which has no such limit.

Every chart on these pages also ships a table view, which is what the light
theme's lower-contrast steps are allowed on.
"""

from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
RESULTS = REPO_ROOT / "results"

# --------------------------------------------------------------------- colour

# The one categorical split: which resolver produced a node. Steps are the
# validated blue/orange pair, stepped per theme for its own surface.
RESOLVER_LIGHT = {"ast": "#2a78d6", "jedi": "#eb6834"}
RESOLVER_DARK = {"ast": "#3987e5", "jedi": "#d95926"}

# Brand gold as a sequential ramp for magnitude (depth, counts). Light to dark
# on the cream surface; dark to light on the near-black one, so in both cases
# "more" reads as "further from the background".
#
# This full-range ramp is for *area* fills -- icicle tiles, big contiguous
# shapes -- where the pale end is still legible because the shape is large and
# carries a label inside it.
GOLD_LIGHT = ["#F5E3B8", "#E3C473", "#C9A23C", "#9A6F1A", "#5C3D0A"]
GOLD_DARK = ["#4A3108", "#8A6418", "#B88A2C", "#D4A843", "#F0D98F"]

# The same hue re-stepped for *marks* -- dots and bars sitting on the surface.
# A 9px dot in #F5E3B8 on white measures 1.27:1 and is simply not there. Every
# step below clears 3:1 against its own surface while staying monotonic, so
# the ramp still reads as a ramp:
#
#   light on #ffffff : 3.29 / 4.76 / 7.39 / 11.88 / 16.2
#   dark  on #0d0b1a : 3.63 / 4.64 / 7.02 / 9.93 / 14.33
#
# Compressing the lightness range costs some of the sequential signal, which
# is affordable here because depth is also carried by position (the x axis of
# the tree, the row of the raster) and exactly by the hover and the table.
GOLD_MARKS_LIGHT = ["#B2871F", "#946C16", "#70500E", "#4A3308", "#2E2004"]
GOLD_MARKS_DARK = ["#8A6418", "#A07422", "#C29435", "#DCB45A", "#F2DC9A"]

# The tree's edges are data, not chrome: they are what makes it a tree rather
# than a scatter of labels. Drawn in the grid colour they measured ~1.1:1 and
# could not be followed from a parent to its child. These sit between the grid
# and the marks -- clearly visible, still subordinate to the nodes.
TREE_EDGE_LIGHT = "#B6AE9C"
TREE_EDGE_DARK = "#544B6B"

# Reserved status colours. Never reused as a series.
STATUS = {
    "good": "#16a34a",
    "warning": "#d97706",
    "serious": "#dc2626",
    "neutral": "#64748b",
}

# Marker shapes double up for the edge kinds, so edge identity survives a
# greyscale print and never depends on a hue.
EDGE_SYMBOL = {
    "root": "star",
    "calls": "circle",
    "infers": "diamond",
    "fixture": "square",
    "fixture-builds": "square-open",
    "overrides": "triangle-up",
    "expands": "triangle-right",
    "touches": "hexagon",
    "smells": "x",
    "reaches": "circle-open",
}

EDGE_HELP = {
    "calls": "the test names it — jedi.goto resolved the name",
    "infers": "operator use — jedi.infer gave the type whose method runs",
    "fixture": "a pytest fixture the test requests (or an autouse one)",
    "fixture-builds": "built by a fixture; the test only sees an untyped argument",
    "overrides": "self.x resolved against the concrete class in the test id",
    "expands": "reached from its parent's bases, decorators, defaults or body",
    "touches": "module-level mutable state in a file this test reaches",
    "smells": "a flakiness pattern matched in directly-exercised code",
    "reaches": "reached by the navigator; the edge was not recorded",
}

PHASE_HELP = {
    "locate": "test id → file, class, function (pure ast)",
    "inherit": "the body is in a base class, not the class the id names",
    "ast_walk": "walk the test body and collect every candidate name",
    "jedi_goto": "name → definition",
    "jedi_infer": "expression → the type whose operator actually runs",
    "fixture": "test arguments → the conftest.py chain",
    "concrete": "self.x → the override in the class the test id names",
    "expand": "a definition's bases, decorators, defaults and callees",
    "shared_state": "module-level mutable values in reachable files",
    "smell": "flakiness pattern scan over directly-exercised code",
}


def resolvers(dark: bool) -> dict[str, str]:
    return RESOLVER_DARK if dark else RESOLVER_LIGHT


def tree_edge(dark: bool) -> str:
    return TREE_EDGE_DARK if dark else TREE_EDGE_LIGHT


def gold_scale(dark: bool, marks: bool = False) -> list[str]:
    """The sequential ramp. ``marks=True`` returns the contrast-safe steps."""
    if marks:
        return GOLD_MARKS_DARK if dark else GOLD_MARKS_LIGHT
    return GOLD_DARK if dark else GOLD_LIGHT


def depth_color(depth: int, max_depth: int, dark: bool, marks: bool = False) -> str:
    """One step off the gold ramp, by how far from the test a node sits.

    Pass ``marks=True`` for anything drawn *on* the surface (dots, bars) and
    leave it off for area fills.
    """
    ramp = gold_scale(dark, marks)
    if max_depth <= 0:
        return ramp[-1]
    index = round(depth / max_depth * (len(ramp) - 1))
    return ramp[max(0, min(len(ramp) - 1, index))]


def plotly_layout(theme: dict, height: int = 420, **kw) -> dict:
    """Shared layout: recessive grid and axes, text in text tokens."""
    layout = {
        "plot_bgcolor": theme["plot_bg"],
        "paper_bgcolor": theme["plot_bg"],
        "font": {"color": theme["plot_text"], "family": "Inter", "size": 12},
        "height": height,
        "margin": {"l": 60, "r": 20, "t": 30, "b": 50},
        "hoverlabel": {
            "bgcolor": theme["plot_legend_bg"],
            "bordercolor": theme["plot_legend_bd"],
            "font": {"color": theme["plot_text"], "family": "Inter"},
        },
        "legend": {
            "bgcolor": theme["plot_legend_bg"],
            "bordercolor": theme["plot_legend_bd"],
            "borderwidth": 1,
            "orientation": "h",
            "yanchor": "bottom",
            "y": 1.02,
            "xanchor": "left",
            "x": 0,
        },
    }
    layout.update(kw)
    return layout


def axis(theme: dict, title: str = "", **kw) -> dict:
    out = {
        "title": title,
        "gridcolor": theme["plot_grid"],
        "zeroline": False,
        "color": theme["plot_axis"],
        "linecolor": theme["plot_grid"],
    }
    out.update(kw)
    return out


# ------------------------------------------------------------------- loading


def tree_dirs() -> dict[str, Path]:
    """Exported tree sets, by the repository they were navigated in.

    ``scripts/export_knowledge_trees.py`` writes ``results/knowledge_trees``
    for the synthetic benchmark and ``results/<repo>/knowledge_trees`` for
    anything else, so the page can offer both.
    """
    found: dict[str, Path] = {}
    primary = RESULTS / "knowledge_trees"
    if primary.is_dir() and any(primary.glob("*.json")):
        found["synthetic (planted benchmark)"] = primary
    for child in sorted(RESULTS.iterdir()) if RESULTS.is_dir() else []:
        if not child.is_dir() or child.name == "knowledge_trees":
            continue
        nested = child / "knowledge_trees"
        if nested.is_dir() and any(nested.glob("*.json")):
            found[child.name] = nested
    return found


def load_tree_index(directory: Path) -> dict[str, Path]:
    """Case id -> file, read from each file's own ``test_id``."""
    index: dict[str, Path] = {}
    for path in sorted(directory.glob("*.json")):
        try:
            with path.open(encoding="utf-8") as handle:
                payload = json.load(handle)
        except (OSError, json.JSONDecodeError):
            continue
        test_id = payload.get("test_id") or path.stem
        index[test_id] = path
    return index


def load_tree(path: Path) -> dict | None:
    try:
        with path.open(encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError):
        return None


def load_summary(directory: Path) -> dict | None:
    """The ``nav_trace_summary.json`` beside a tree directory."""
    path = directory.parent / "nav_trace_summary.json"
    try:
        with path.open(encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError):
        return None


def trace_csv(directory: Path) -> Path:
    return directory.parent / "nav_trace.csv"


# ------------------------------------------------------------ tree geometry


def layout_nodes(rows: list[dict]) -> tuple[list[dict], list[tuple[dict, dict]]]:
    """Give every node an (x, y) for a node-link drawing.

    ``x`` is the node's depth, so distance from the test reads left to right
    -- that axis *is* the "searching in depth" story. ``y`` is assigned by
    walking the tree in display order and giving each leaf the next slot,
    with a parent centred on its children, which is the standard tidy-tree
    placement and keeps edges from crossing.
    """
    by_id = {row["id"]: dict(row) for row in rows}
    children: dict[str, list[str]] = {node_id: [] for node_id in by_id}
    roots: list[str] = []
    for row in rows:
        parent = row["parent"]
        if parent and parent in children:
            children[parent].append(row["id"])
        else:
            roots.append(row["id"])

    cursor = [0.0]

    def place(node_id: str) -> float:
        kids = children[node_id]
        if not kids:
            y = cursor[0]
            cursor[0] += 1.0
            by_id[node_id]["y"] = y
            return y
        positions = [place(kid) for kid in kids]
        y = (min(positions) + max(positions)) / 2
        by_id[node_id]["y"] = y
        return y

    for root in roots:
        place(root)

    for node in by_id.values():
        node["x"] = node["depth"]

    edges = [
        (by_id[row["parent"]], by_id[row["id"]])
        for row in rows
        if row["parent"] and row["parent"] in by_id
    ]
    return list(by_id.values()), edges

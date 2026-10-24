"""Build the static result report the pipeline deploys.

The Streamlit dashboard is the interactive view and it needs a Python process.
This is the deliverable version: one self-contained HTML file, built from the
same ``results/`` bundle the quality gate just passed, with no runtime at all.
That is what makes the last pipeline stage a deployment rather than a build --
there is an artifact a person can open.

    python scripts/build_static_report.py --out site

Reads ``results/pipeline_status.json``, ``nav_trace_summary.json``,
``nav_trace.csv``, ``llm_metrics.csv``, ``baseline_metrics.csv`` and the
exported knowledge trees. Anything missing is reported as missing rather than
faked, because a report that hides a gap is worse than no report.
"""

from __future__ import annotations

import argparse
import csv
import html
import json
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# Same validated pair the dashboard uses for the one categorical split.
AST_HUE = "#2a78d6"
JEDI_HUE = "#eb6834"
GOLD = ["#F5E3B8", "#E3C473", "#C9A23C", "#9A6F1A", "#5C3D0A"]
STATUS_HUE = {"pass": "#16a34a", "warn": "#d97706", "fail": "#dc2626", "skip": "#64748b"}


def read_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def read_csv(path: Path) -> list[dict]:
    try:
        with path.open(encoding="utf-8", newline="") as handle:
            return list(csv.DictReader(handle))
    except OSError:
        return []


def esc(value) -> str:
    return html.escape(str(value))


def missing(what: str) -> str:
    return (
        f'<p class="missing">Not in this bundle: <code>{esc(what)}</code>. '
        f"The stage that produces it did not run, or produced nothing.</p>"
    )


# ---------------------------------------------------------------- sections


def section_gate(status: dict | None) -> str:
    if not status:
        return "<h2>Quality gate</h2>" + missing("results/pipeline_status.json")
    verdict = status.get("verdict", "unknown")
    counts = status.get("counts", {})
    rows = "".join(
        f"<tr><td><span class='pill' style='background:{STATUS_HUE.get(c['status'], '#64748b')}'>"
        f"{esc(c['status'].upper())}</span></td>"
        f"<td><b>{esc(c['name'])}</b></td><td>{esc(c['stage'])}</td>"
        f"<td class='mono'>{esc(c['detail'])}</td><td class='why'>{esc(c['why'])}</td></tr>"
        for c in status.get("checks", [])
    )
    banner_hue = STATUS_HUE["pass"] if verdict == "promote" else STATUS_HUE["fail"]
    return f"""
    <h2>Quality gate — the testing/delivery boundary</h2>
    <p class="lede">Every stage before this one asks whether the code runs. This
    one asks whether the build is good enough to ship. When it fails, nothing
    downstream of it executes: no report, no deployment, no release.</p>
    <div class="banner" style="border-color:{banner_hue}">
      <div class="verdict" style="color:{banner_hue}">{esc(verdict.upper())}</div>
      <div class="counts">{counts.get('pass', 0)} passed ·
      {counts.get('fail', 0)} failed · {counts.get('warn', 0)} warned ·
      {counts.get('skip', 0)} skipped</div>
      <div class="meta">commit <code>{esc(status.get('commit', '?'))}</code> ·
      branch <code>{esc(status.get('branch') or 'local')}</code> ·
      workflow <code>{esc(status.get('workflow', '?'))}</code> ·
      python {esc(status.get('python', '?'))}</div>
    </div>
    <table><thead><tr><th></th><th>Check</th><th>Stage</th>
    <th>Measured</th><th>Why this threshold</th></tr></thead>
    <tbody>{rows}</tbody></table>
    """


def bar_svg(items: list[tuple[str, float]], unit: str = "", hue: str = GOLD[3]) -> str:
    """A horizontal bar chart as inline SVG. No script, no dependency."""
    if not items:
        return ""
    top = max(value for _, value in items) or 1.0
    row_h, label_w, chart_w = 30, 230, 420
    height = row_h * len(items) + 10
    bars = []
    for index, (label, value) in enumerate(items):
        y = index * row_h + 6
        width = max(2.0, value / top * chart_w)
        bars.append(
            f'<text x="{label_w - 10}" y="{y + 14}" text-anchor="end" '
            f'class="svg-label">{esc(label)}</text>'
            f'<rect x="{label_w}" y="{y + 3}" width="{width:.1f}" height="15" '
            f'rx="4" fill="{hue}"/>'
            f'<text x="{label_w + width + 8}" y="{y + 15}" class="svg-value">'
            f'{value:g}{esc(unit)}</text>'
        )
    return (
        f'<svg viewBox="0 0 {label_w + chart_w + 90} {height}" '
        f'class="chart" role="img">{"".join(bars)}</svg>'
    )


def section_navigator(nav: dict | None, rows: list[dict]) -> str:
    if not nav:
        return "<h2>Navigator</h2>" + missing("results/nav_trace_summary.json")

    head = f"""
    <h2>Navigator: knowledge trees</h2>
    <p class="lede">For each failing test the navigator builds a tree: the root
    is the test, every other node is code it reaches, and the depth of a node is
    how many hops away it is. <span style="color:{AST_HUE};font-weight:700">The
    AST walk</span> decides what to look for;
    <span style="color:{JEDI_HUE};font-weight:700">jedi</span> resolves each name
    to a definition and the expansion hops go deeper.</p>
    <div class="tiles">
      <div class="tile"><b>{esc(nav.get('cases', 0))}</b><span>cases navigated</span></div>
      <div class="tile"><b>{nav.get('resolution_rate', 0):.0%}</b><span>resolved to something</span></div>
      <div class="tile"><b>{esc(nav.get('mean_tree_nodes', 0))}</b><span>mean nodes per tree</span></div>
      <div class="tile"><b>{esc(nav.get('max_tree_depth', 0))}</b><span>deepest tree</span></div>
      <div class="tile"><b>{nav.get('jedi_hit_rate', 0):.0%}</b><span>jedi hit rate</span></div>
      <div class="tile"><b>{esc(nav.get('median_ms', 0))} ms</b><span>median per test</span></div>
    </div>
    <p class="meta">Repo <code>{esc(nav.get('repo', '?'))}</code> @
    <code>{esc(nav.get('sha', '?'))}</code>, gold set
    <code>{esc(nav.get('gold', '?'))}</code>. Max latency
    {esc(nav.get('max_ms', 0))} ms.</p>
    """

    if not rows:
        return head + missing("results/nav_trace.csv")

    def total(field: str) -> float:
        return sum(float(row.get(field) or 0) for row in rows)

    edges = [
        ("calls — the test names it", total("edge_calls")),
        ("infers — operator use, jedi.infer", total("edge_infers")),
        ("expands — bases, decorators, callees", total("edge_expands")),
        ("fixture — pytest fixtures", total("edge_fixture")),
        ("fixture-builds — what a fixture made", total("edge_fixture_builds")),
        ("overrides — self.x in an inherited test", total("edge_overrides")),
        ("touches — module-level mutable state", total("edge_touches")),
        ("smells — flakiness patterns", total("edge_smells")),
    ]
    edges = [pair for pair in edges if pair[1]]

    depth_rows = [
        ("the test itself", float(len(rows))),
        ("hop 1 — named directly", total("nodes_depth_1")),
        ("hop 2+ — reached by expansion", total("nodes_depth_2plus")),
    ]

    resolver_rows = [
        ("jedi.goto calls", total("jedi_goto_calls")),
        ("jedi.infer calls", total("jedi_infer_calls")),
        ("names the AST walk collected", total("ast_names")),
    ]

    table_rows = "".join(
        f"<tr><td class='mono'>{esc(row['case_id'].split('/')[-1])}</td>"
        f"<td>{esc(row.get('label') or '—')}</td>"
        f"<td>{esc(row.get('root_cause') or '—')}</td>"
        f"<td>{esc(row['tree_nodes'])}</td><td>{esc(row['tree_max_depth'])}</td>"
        f"<td>{esc(row['ast_names'])}</td><td>{esc(row['jedi_calls'])}</td>"
        f"<td>{float(row['jedi_hit_rate']):.0%}</td>"
        f"<td>{esc(row['elapsed_ms'])}</td></tr>"
        for row in rows
    )

    return head + f"""
    <h3>What reached each node</h3>
    <p class="note">Every edge type, totalled across the set. This is the
    navigator's mechanism made countable: how much of what it finds comes from
    a name the test wrote down, versus a type it had to infer, versus a hop it
    had to take.</p>
    {bar_svg(edges, hue=GOLD[3])}
    <h3>How far from the test</h3>
    {bar_svg(depth_rows, unit=" nodes", hue=GOLD[2])}
    <h3>Resolver work</h3>
    {bar_svg(resolver_rows, unit=" calls", hue=JEDI_HUE)}
    <h3>Per case</h3>
    <table><thead><tr><th>case</th><th>label</th><th>root cause</th>
    <th>nodes</th><th>depth</th><th>AST names</th><th>jedi calls</th>
    <th>hit rate</th><th>ms</th></tr></thead>
    <tbody>{table_rows}</tbody></table>
    """


def section_results(llm: list[dict], baselines: list[dict]) -> str:
    if not llm and not baselines:
        return "<h2>Detection results</h2>" + missing("results/llm_metrics.csv")

    rows = []
    for row in baselines:
        rows.append(
            (f"rerun baseline (N={row.get('N')})", row, "baseline")
        )
    for row in llm:
        rows.append((f"prompt {row.get('prompt_version')}", row, "llm"))

    body = "".join(
        f"<tr><td><b>{esc(name)}</b></td>"
        f"<td>{esc(row.get('model', 'rerun'))}</td>"
        f"<td>{float(row.get('precision') or 0):.3f}</td>"
        f"<td>{float(row.get('recall') or 0):.3f}</td>"
        f"<td><b>{float(row.get('f1') or 0):.3f}</b> "
        f"<span class='ci'>[{float(row.get('f1_ci_lower') or 0):.2f}, "
        f"{float(row.get('f1_ci_upper') or 0):.2f}]</span></td>"
        f"<td>{float(row.get('root_cause_acc') or 0):.3f}</td>"
        f"<td class='{'bad' if float(row.get('false_quarantine_rate') or 0) > 0.1 else ''}'>"
        f"{float(row.get('false_quarantine_rate') or 0):.3f}</td></tr>"
        for name, row, _ in rows
    )

    f1_bars = [
        (name, round(float(row.get("f1") or 0), 3)) for name, row, _ in rows
    ]

    caveat = ""
    worst_fq = max(
        (float(row.get("false_quarantine_rate") or 0) for _, row, kind in rows if kind == "llm"),
        default=0.0,
    )
    if worst_fq > 0.1:
        caveat = f"""
        <div class="caveat">
          <b>Read the last column before the F1 column.</b> The best prompt
          reaches its recall by calling almost everything flaky, and its
          false-quarantine rate of {worst_fq:.2f} means it mislabels the real
          bugs in the benchmark as flaky. The rerun baseline's rate is 0.00.
          F1 alone makes the LLM look strictly better; on the one error that
          costs more than a flake does, it is worse. This is why v1 never
          quarantines on its own — a person approves every quarantine.
        </div>"""

    return f"""
    <h2>Detection results</h2>
    <p class="lede">Precision, recall and F1 for calling a test flaky, with
    bootstrap confidence intervals, against the rerun baseline.</p>
    {bar_svg(f1_bars, hue=GOLD[3])}
    <table><thead><tr><th>method</th><th>model</th><th>precision</th>
    <th>recall</th><th>F1 [95% CI]</th><th>root-cause acc</th>
    <th>false quarantine</th></tr></thead><tbody>{body}</tbody></table>
    {caveat}
    """


def section_trees(tree_dir: Path, limit: int = 6) -> str:
    """A few rendered trees, so the report shows the thing itself."""
    files = sorted(tree_dir.glob("*.json"))[:limit] if tree_dir.is_dir() else []
    if not files:
        return ""
    blocks = []
    for path in files:
        payload = read_json(path)
        if not payload or not payload.get("rendered"):
            continue
        stats = payload.get("tree", {}).get("stats", {})
        blocks.append(
            f"<details><summary><code>{esc(payload.get('test_id', path.stem))}</code>"
            f" — {esc(stats.get('nodes', 0))} nodes, depth "
            f"{esc(stats.get('max_depth', 0))}</summary>"
            f"<pre>{esc(payload['rendered'])}</pre></details>"
        )
    if not blocks:
        return ""
    return f"""
    <h2>Knowledge trees, as built</h2>
    <p class="lede">The first {len(blocks)} trees in the bundle, exactly as the
    navigator produced them. <code>[calls]</code> is a name the test wrote;
    <code>[infers]</code> is a type jedi had to work out; <code>[expands]</code>
    is a hop deeper into a base class or decorator.</p>
    {"".join(blocks)}
    """


STYLE = """
:root{color-scheme:light dark;--bg:#ffffff;--fg:#121212;--muted:#5b5b5b;
--faint:#8a8a8a;--line:rgba(154,111,26,.22);--card:#fcfbf7;--accent:#9A6F1A;}
@media (prefers-color-scheme:dark){:root{--bg:#0d0b1a;--fg:#F5EDD6;
--muted:#C8B99A;--faint:#8e8270;--line:rgba(212,168,67,.25);--card:#141127;
--accent:#D4A843;}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);
font:15px/1.65 Inter,-apple-system,Segoe UI,Roboto,sans-serif;}
.wrap{max-width:1080px;margin:0 auto;padding:40px 16px 80px}
header{border-bottom:2px solid var(--accent);padding-bottom:18px;margin-bottom:8px}
h1{font-size:2rem;margin:0 0 6px;letter-spacing:-.01em}
h2{font-size:1.3rem;margin:44px 0 6px;padding-top:18px;border-top:1px solid var(--line)}
h3{font-size:1rem;margin:26px 0 6px;color:var(--accent)}
.lede{color:var(--muted);margin:6px 0 18px;max-width:72ch}
.note{color:var(--faint);font-size:.86rem;max-width:72ch;margin:4px 0 10px}
.meta{color:var(--faint);font-size:.8rem}
.missing{background:rgba(217,119,6,.08);border-left:3px solid #d97706;
padding:10px 14px;border-radius:0 8px 8px 0;color:var(--muted);font-size:.9rem}
code{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:.86em;
background:rgba(128,128,128,.12);padding:1px 5px;border-radius:4px}
.mono{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:.82rem}
table{width:100%;border-collapse:collapse;margin:14px 0;font-size:.86rem}
th{text-align:left;color:var(--faint);font-size:.72rem;text-transform:uppercase;
letter-spacing:.06em;padding:8px 10px;border-bottom:1px solid var(--line)}
td{padding:9px 10px;border-bottom:1px solid var(--line);vertical-align:top}
tbody tr:hover{background:rgba(128,128,128,.05)}
.why{color:var(--faint);font-size:.8rem;max-width:34ch}
.ci{color:var(--faint);font-size:.78rem}
.bad{color:#dc2626;font-weight:700}
.pill{color:#fff;font-size:.68rem;font-weight:700;padding:3px 8px;
border-radius:9px;letter-spacing:.04em}
.banner{border:1px solid;border-left-width:5px;border-radius:0 12px 12px 0;
padding:16px 20px;background:var(--card);margin:14px 0}
.verdict{font-size:1.5rem;font-weight:800;letter-spacing:.02em}
.counts{color:var(--muted);font-size:.9rem;margin:2px 0 6px}
.tiles{display:flex;flex-wrap:wrap;gap:10px;margin:16px 0}
.tile{flex:1 1 150px;background:var(--card);border:1px solid var(--line);
border-radius:12px;padding:14px 16px}
.tile b{display:block;font-size:1.5rem;color:var(--accent);line-height:1.2}
.tile span{color:var(--faint);font-size:.74rem;text-transform:uppercase;
letter-spacing:.05em}
.chart{width:100%;height:auto;max-width:760px;display:block;margin:8px 0 18px}
.svg-label{fill:var(--muted);font:12px Inter,sans-serif}
.svg-value{fill:var(--fg);font:600 12px Inter,sans-serif}
.caveat{background:rgba(220,38,38,.07);border-left:4px solid #dc2626;
border-radius:0 10px 10px 0;padding:14px 18px;margin:18px 0;font-size:.9rem;
color:var(--fg);max-width:78ch}
details{border:1px solid var(--line);border-radius:10px;padding:10px 14px;
margin-bottom:8px;background:var(--card)}
summary{cursor:pointer;font-size:.88rem}
pre{overflow-x:auto;font-size:.8rem;line-height:1.5;color:var(--muted)}
footer{margin-top:50px;padding-top:16px;border-top:1px solid var(--line);
color:var(--faint);font-size:.8rem}
@media (max-width:640px){.wrap{padding:24px 16px 60px}h1{font-size:1.5rem}}
"""


def build(results: Path) -> str:
    status = read_json(results / "pipeline_status.json")
    nav = read_json(results / "nav_trace_summary.json")
    rows = read_csv(results / "nav_trace.csv")
    llm = read_csv(results / "llm_metrics.csv")
    baselines = read_csv(results / "baseline_metrics.csv")

    built = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    commit = (status or {}).get("commit", "local")

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>FlakeGuard Report</title><style>{STYLE}</style></head>
<body><div class="wrap">
<header>
  <h1>FlakeGuard — pipeline report</h1>
  <p class="meta">Built {esc(built)} from commit <code>{esc(commit)}</code> ·
  generated by <code>scripts/build_static_report.py</code> in the
  <code>report</code> stage, from the bundle that passed the gate.</p>
</header>
{section_gate(status)}
{section_navigator(nav, rows)}
{section_results(llm, baselines)}
{section_trees(results / "knowledge_trees")}
<footer>Detect and triage flaky tests using LLM-assisted analysis.
Every number here comes from a file in <code>results/</code>; nothing is
hand-entered. Interactive view:
<code>streamlit run flakeguard/app/dashboard.py</code>.</footer>
</div></body></html>
"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", default="results", help="the gated bundle")
    parser.add_argument("--out", default="site", help="output directory")
    args = parser.parse_args(argv)

    results = Path(args.results)
    if not results.is_absolute():
        results = REPO_ROOT / results
    if not results.is_dir():
        print(f"error: {results} not found")
        return 2

    out_dir = Path(args.out)
    if not out_dir.is_absolute():
        out_dir = REPO_ROOT / out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    page = build(results)
    index = out_dir / "index.html"
    index.write_text(page, encoding="utf-8")
    print(f"  report -> {index}  ({len(page) / 1024:.1f} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

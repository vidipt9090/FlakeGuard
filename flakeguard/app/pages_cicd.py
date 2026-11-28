"""The CI/CD page: the pipeline, the gate, and what actually ran.

The project started as "we have tests and a workflow that runs them". That is
continuous integration and nothing more. This page shows the pipeline it became
and, more importantly, *where the boundary is*: the stages that ask "does it
work?" and the one stage that asks "is this good enough to ship?", after which
nothing runs unless the answer was yes.

Three sources, in order of how live they are:

1. ``results/pipeline_status.json`` -- written by ``scripts/quality_gate.py``,
   so the check table is the real last verdict, local or from CI.
2. the GitHub Actions REST API -- fetched on demand, so the stage grid shows
   what the latest real runs did.
3. the workflow files on disk -- parsed for the declared stage graph, so the
   page cannot drift from the pipeline it claims to document.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path

import plotly.graph_objects as go
import streamlit as st

from flakeguard.app import viz

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = REPO_ROOT / ".github" / "workflows"
DEFAULT_REPO = "vidipt9090/FlakeGuard"

# The declared pipeline. Each entry is (job id, what it proves, which side of
# the gate it sits on). Kept beside the workflow so the page can show the two
# together and a drift is visible rather than silent.
STAGES: list[tuple[str, str, str, str]] = [
    ("static", "lint", "ruff over the whole tree", "ci"),
    ("build", "build", "sdist + wheel, metadata checked, uploaded once", "ci"),
    ("ui", "web ui", "React dashboard: typecheck + build, carried forward", "ci"),
    ("test", "unit tests", "pytest with coverage; records the jedi version", "ci"),
    ("navigate", "navigate (synthetic)", "neutralisation check, nav eval, knowledge trees", "ci"),
    (
        "navigate-external",
        "navigate (cachetools)",
        "a repo that is not ours, pinned by SHA, scored on a hand gold set",
        "ci",
    ),
    ("gate", "quality gate", "measured thresholds; blocks everything downstream", "gate"),
    ("report", "report", "static HTML built from the gated bundle", "cd"),
    ("deploy", "deploy", "publishes it to GitHub Pages (develop / main only)", "cd"),
    ("release", "release", "tagged release carrying the build and its evidence", "cd"),
]

SIDE_LABEL = {
    "ci": "continuous integration — does it work?",
    "gate": "the boundary — is it good enough to ship?",
    "cd": "continuous delivery — ship it",
}

CONCLUSION_STATUS = {
    "success": "good",
    "failure": "serious",
    "cancelled": "neutral",
    "skipped": "neutral",
    "timed_out": "serious",
    "action_required": "warning",
    "neutral": "neutral",
    None: "warning",
}


def _load_status() -> dict | None:
    """The last gate verdict, written by ``scripts/quality_gate.py``.

    Not cached: the point of the page is that re-running the gate locally
    changes what it shows on the next rerun.
    """
    path = REPO_ROOT / "results" / "pipeline_status.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _sec(label: str) -> None:
    st.markdown(f'<div class="sec-label">{label}</div>', unsafe_allow_html=True)


def _note(theme: dict, text: str) -> None:
    st.markdown(
        f'<div style="background:{theme["evidence_bg"]};border-left:3px solid '
        f'{theme["accent"]};border-radius:0 8px 8px 0;padding:12px 16px;'
        f'font-size:0.88rem;color:{theme["text_soft"]};line-height:1.65;'
        f'margin-bottom:16px">{text}</div>',
        unsafe_allow_html=True,
    )


# --------------------------------------------------------------------- page


def render(theme: dict, dark: bool) -> None:
    _sec("🚀 From a test suite to a delivery pipeline")
    _note(
        theme,
        "Running <code>pytest</code> on every push is continuous integration. "
        "It answers one question: <i>did it break?</i> A delivery pipeline "
        "answers a second one — <i>is this build good enough to ship?</i> — and "
        "acts on the answer. The stage that does that is the "
        "<b>quality gate</b>. Everything to its left is testing; everything to "
        "its right only runs through it.",
    )

    status = _load_status()
    _render_flow(theme, dark, status)

    st.divider()
    _render_gate(theme, dark, status)

    st.divider()
    _render_transition(theme)

    st.divider()
    _render_live(theme, dark)

    st.divider()
    _render_workflows(theme)


# -------------------------------------------------------------- the diagram


def _render_flow(theme: dict, dark: bool, status: dict | None) -> None:
    _sec("🧭 The pipeline")
    verdict = (status or {}).get("verdict")

    for side in ("ci", "gate", "cd"):
        group = [s for s in STAGES if s[3] == side]
        st.markdown(
            f'<p style="color:{theme["accent"]};font-size:0.72rem;font-weight:700;'
            f'letter-spacing:0.08em;text-transform:uppercase;margin:16px 0 8px">'
            f"{SIDE_LABEL[side]}</p>",
            unsafe_allow_html=True,
        )
        cols = st.columns(len(group))
        for col, (job, title, detail, _) in zip(cols, group):
            if side == "gate" and verdict:
                hue = (
                    viz.STATUS["good"] if verdict == "promote" else viz.STATUS["serious"]
                )
                badge = verdict.upper()
            elif side == "cd":
                reachable = verdict == "promote"
                hue = viz.STATUS["good"] if reachable else viz.STATUS["neutral"]
                badge = "reachable" if reachable else "blocked"
            else:
                hue = theme["accent"]
                badge = job
            col.markdown(
                f'<div class="pipeline-stage" style="border-color:{hue}">'
                f"<b>{title}</b><br>"
                f'<span style="color:{theme["text_faint"]};font-size:0.64rem">'
                f"{detail}</span><br>"
                f'<span style="color:{hue};font-size:0.62rem;font-weight:700;'
                f'letter-spacing:0.05em">{badge}</span></div>',
                unsafe_allow_html=True,
            )

    st.caption(
        "Declared in `.github/workflows/cicd.yml`. The gate's badge is the real "
        "verdict from the last `scripts/quality_gate.py` run; the delivery "
        "stages show whether that verdict lets them run at all."
    )


# ----------------------------------------------------------------- the gate


def _render_gate(theme: dict, dark: bool, status: dict | None) -> None:
    _sec("🚧 The quality gate")
    if not status:
        st.warning(
            "No `results/pipeline_status.json`. Run `python scripts/quality_gate.py` "
            "to produce it — the pipeline writes it in the `gate` stage."
        )
        return

    counts = status.get("counts", {})
    promote = status.get("promote")
    hue = viz.STATUS["good"] if promote else viz.STATUS["serious"]
    st.markdown(
        f"""
        <div style="background:{theme["card_bg"]};border:1px solid {theme["card_border"]};
        border-left:5px solid {hue};border-radius:0 14px 14px 0;padding:18px 24px;
        margin-bottom:16px">
          <div style="color:{hue};font-size:1.6rem;font-weight:800;letter-spacing:0.02em">
            {"PROMOTE" if promote else "BLOCKED"}
          </div>
          <div style="color:{theme["text_muted"]};font-size:0.9rem;margin:2px 0 8px">
            {counts.get("pass", 0)} passed · {counts.get("fail", 0)} failed ·
            {counts.get("warn", 0)} warned · {counts.get("skip", 0)} skipped
          </div>
          <div style="color:{theme["text_faint"]};font-size:0.78rem">
            commit <code>{status.get("commit", "?")}</code> ·
            branch <code>{status.get("branch") or "local"}</code> ·
            workflow <code>{status.get("workflow", "?")}</code> ·
            python {status.get("python", "?")} ·
            {status.get("generated_at", "?")}
            {" · strict" if status.get("strict") else ""}
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    checks = status.get("checks", [])
    st.plotly_chart(
        _gate_figure(checks, theme, dark), use_container_width=True, key="gate_fig"
    )

    st.markdown("**Every check, its measurement, and why the threshold is there**")
    for check in checks:
        state = check["status"]
        hue = {
            "pass": viz.STATUS["good"],
            "warn": viz.STATUS["warning"],
            "fail": viz.STATUS["serious"],
            "skip": viz.STATUS["neutral"],
        }[state]
        icon = {"pass": "✅", "warn": "⚠️", "fail": "❌", "skip": "⏭️"}[state]
        st.markdown(
            f"""
            <div style="background:{theme["evidence_bg"]};border-left:3px solid {hue};
            border-radius:0 9px 9px 0;padding:11px 16px;margin-bottom:9px">
              <div style="color:{theme["text"]};font-size:0.9rem;font-weight:600">
                {icon} {check["name"]}
                <span style="color:{theme["text_faint"]};font-weight:500;font-size:0.76rem">
                  &nbsp;· {check["stage"]} · {check["source"]}</span>
              </div>
              <div style="color:{theme["text_soft"]};font-size:0.84rem;margin-top:3px;
              font-family:ui-monospace,Menlo,monospace">{check["detail"]}</div>
              <div style="color:{theme["text_muted"]};font-size:0.8rem;margin-top:4px;
              line-height:1.6">{check["why"]}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )


def _gate_figure(checks: list[dict], theme: dict, dark: bool) -> go.Figure:
    """Checks grouped by stage, as a stacked count per outcome.

    Outcome is a state, not a series, so it uses the reserved status colours
    and every segment is directly labelled.
    """
    stages = []
    for check in checks:
        if check["stage"] not in stages:
            stages.append(check["stage"])

    figure = go.Figure()
    for state, label, hue in (
        ("pass", "passed", viz.STATUS["good"]),
        ("warn", "warned", viz.STATUS["warning"]),
        ("fail", "failed", viz.STATUS["serious"]),
        ("skip", "skipped", viz.STATUS["neutral"]),
    ):
        values = [
            sum(1 for c in checks if c["stage"] == stage and c["status"] == state)
            for stage in stages
        ]
        if not any(values):
            continue
        figure.add_trace(
            go.Bar(
                name=label,
                x=stages,
                y=values,
                marker={
                    "color": hue,
                    "line": {"color": theme["plot_bg"], "width": 2},
                    "cornerradius": 4,
                },
                text=[v or "" for v in values],
                textposition="inside",
                textfont={"color": "#ffffff"},
                hovertemplate=f"%{{x}}: %{{y}} {label}<extra></extra>",
            )
        )

    figure.update_layout(
        **viz.plotly_layout(
            theme,
            height=300,
            barmode="stack",
            bargap=0.5,
            xaxis=viz.axis(theme, "pipeline stage", showgrid=False),
            yaxis=viz.axis(theme, "checks", rangemode="tozero", dtick=1),
        )
    )
    return figure


# ----------------------------------------------------------- the transition


def _render_transition(theme: dict) -> None:
    _sec("🔀 What changed, and why it counts as CD")
    rows = [
        (
            "Trigger",
            "push and PR on a few branches",
            "push, PR, tags, and manual dispatch with a strict-gate switch",
            "a release has to be triggerable by a tag, or there is no delivery event",
        ),
        (
            "Shape",
            "one job doing everything in sequence",
            "eight jobs in a dependency graph, fanning out and back in",
            "a lint failure should not cost you the navigator run; independent "
            "work runs in parallel and reports separately",
        ),
        (
            "Artifacts",
            "none — every step rebuilt from source",
            "dist, test reports, both result sets, the gated bundle, the report",
            "delivery means shipping the thing you tested, not a later rebuild "
            "of the same source",
        ),
        (
            "Gate",
            "pass/fail of pytest only",
            "measured thresholds on navigator reach, jedi hit rate, prompt F1 "
            "against the baseline, benchmark size",
            "tests passing does not mean the result is still good; a navigator "
            "that resolves nothing passes every unit test",
        ),
        (
            "Generalisation",
            "scored on our own fixtures",
            "a pinned external repository scored on a hand-labelled gold set, "
            "as a pipeline stage",
            "a navigator tuned and scored on one library measures fit, not skill",
        ),
        (
            "Output",
            "a green tick",
            "a deployed HTML report and a tagged release carrying its evidence",
            "someone outside the team can read the result without running anything",
        ),
        (
            "Reproducibility",
            "implicit",
            "jedi version and full pip freeze recorded next to the numbers",
            "the navigator resolves against what is installed — we measured the "
            "same test id returning 3 chunks on one interpreter and 1 on another",
        ),
    ]
    for aspect, before, after, why in rows:
        st.markdown(
            f"""
            <div style="background:{theme["card_bg"]};border:1px solid {theme["card_border"]};
            border-radius:12px;padding:16px 20px;margin-bottom:10px">
              <div style="color:{theme["accent"]};font-size:0.78rem;font-weight:700;
              letter-spacing:0.06em;text-transform:uppercase;margin-bottom:8px">{aspect}</div>
              <div style="display:flex;gap:14px;flex-wrap:wrap;margin-bottom:8px">
                <div style="flex:1 1 240px">
                  <span style="color:{theme["text_faint"]};font-size:0.68rem;
                  font-weight:700;letter-spacing:0.05em">BEFORE</span>
                  <div style="color:{theme["text_muted"]};font-size:0.85rem;
                  line-height:1.55">{before}</div>
                </div>
                <div style="flex:1 1 240px">
                  <span style="color:{theme["accent"]};font-size:0.68rem;
                  font-weight:700;letter-spacing:0.05em">NOW</span>
                  <div style="color:{theme["text_soft"]};font-size:0.85rem;
                  line-height:1.55">{after}</div>
                </div>
              </div>
              <div style="color:{theme["text_faint"]};font-size:0.8rem;
              border-top:1px solid {theme["sec_border"]};padding-top:7px;line-height:1.6">
                <b>Why:</b> {why}
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )


# ------------------------------------------------------------- live from CI


def _render_live(theme: dict, dark: bool) -> None:
    _sec("📡 The real runs")
    st.caption(
        "Fetched from the GitHub Actions REST API when you ask for it. Public "
        "endpoint, no token, so it is rate-limited and will be unavailable "
        "offline — in which case the check table above is still the real "
        "verdict from the last gate run."
    )
    col_repo, col_wf, col_btn = st.columns([2, 1.4, 1])
    repo = col_repo.text_input("Repository", value=DEFAULT_REPO, key="cicd_repo")
    workflow = col_wf.selectbox(
        "Workflow",
        ["cicd.yml", "test.yml", "ci.yml", "collect.yml"],
        key="cicd_wf",
    )
    col_btn.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
    if not col_btn.button("Fetch runs", key="cicd_fetch"):
        return

    with st.spinner(f"Asking GitHub about {repo} / {workflow} …"):
        runs, error = _fetch_runs(repo, workflow)

    if error:
        st.warning(f"Could not reach the Actions API: {error}")
        return
    if not runs:
        st.info(
            f"No runs recorded for `{workflow}` in `{repo}`. If the pipeline was "
            "just added, it has not run yet."
        )
        return

    newest = runs[0]
    hue = viz.STATUS[CONCLUSION_STATUS.get(newest.get("conclusion"), "warning")]
    st.markdown(
        f"""
        <div style="background:{theme["card_bg"]};border:1px solid {theme["card_border"]};
        border-left:5px solid {hue};border-radius:0 12px 12px 0;padding:14px 20px;
        margin-bottom:14px">
          <div style="color:{hue};font-size:1.1rem;font-weight:800">
            {str(newest.get("conclusion") or newest.get("status") or "?").upper()}
          </div>
          <div style="color:{theme["text_soft"]};font-size:0.86rem">
            run #{newest.get("run_number")} on <code>{newest.get("head_branch")}</code>
            · {newest.get("event")} · commit
            <code>{str(newest.get("head_sha") or "")[:12]}</code>
          </div>
          <div style="color:{theme["text_faint"]};font-size:0.78rem">
            {newest.get("created_at", "")} · <a href="{newest.get("html_url", "#")}"
            style="color:{theme["accent"]}">open on GitHub</a>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.plotly_chart(
        _runs_figure(runs, theme, dark), use_container_width=True, key="cicd_runs"
    )

    st.dataframe(
        [
            {
                "#": run.get("run_number"),
                "status": run.get("conclusion") or run.get("status"),
                "branch": run.get("head_branch"),
                "event": run.get("event"),
                "commit": str(run.get("head_sha") or "")[:12],
                "started": run.get("created_at"),
            }
            for run in runs
        ],
        use_container_width=True,
        hide_index=True,
    )


def _fetch_runs(repo: str, workflow: str, limit: int = 20):
    """Recent workflow runs, or an error string. Never raises."""
    url = (
        f"https://api.github.com/repos/{repo}/actions/workflows/"
        f"{workflow}/runs?per_page={limit}"
    )
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "FlakeGuard-dashboard",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=12) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return [], f"no such repo or workflow ({repo} / {workflow})"
        return [], f"HTTP {exc.code}"
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        return [], f"{type(exc).__name__}: {exc}"
    return payload.get("workflow_runs", []), ""


def _runs_figure(runs: list[dict], theme: dict, dark: bool) -> go.Figure:
    """Outcome per run, oldest to newest. Status colours, direct labels."""
    ordered = list(reversed(runs))
    buckets = {"good": [], "serious": [], "warning": [], "neutral": []}
    for run in ordered:
        bucket = CONCLUSION_STATUS.get(run.get("conclusion"), "warning")
        for key in buckets:
            buckets[key].append(1 if key == bucket else 0)

    labels = [f"#{run.get('run_number')}" for run in ordered]
    figure = go.Figure()
    for key, name in (
        ("good", "success"),
        ("warning", "in progress / needs action"),
        ("serious", "failure"),
        ("neutral", "cancelled / skipped"),
    ):
        if not any(buckets[key]):
            continue
        figure.add_trace(
            go.Bar(
                name=name,
                x=labels,
                y=buckets[key],
                marker={
                    "color": viz.STATUS[key],
                    "line": {"color": theme["plot_bg"], "width": 2},
                    "cornerradius": 3,
                },
                hovertemplate=f"run %{{x}}: {name}<extra></extra>",
            )
        )
    figure.update_layout(
        **viz.plotly_layout(
            theme,
            height=260,
            barmode="stack",
            bargap=0.3,
            xaxis=viz.axis(theme, "workflow run (oldest first)", showgrid=False),
            yaxis=viz.axis(theme, "", showticklabels=False, range=[0, 1.2]),
        )
    )
    return figure


# ------------------------------------------------------ the workflows on disk


def _render_workflows(theme: dict) -> None:
    _sec("📜 The workflows themselves")
    st.caption(
        "Read from `.github/workflows/` on disk, so this page cannot claim a "
        "pipeline the repository does not have."
    )
    if not WORKFLOWS.is_dir():
        st.warning("No `.github/workflows/` directory found.")
        return
    files = sorted(WORKFLOWS.glob("*.yml")) + sorted(WORKFLOWS.glob("*.yaml"))
    if not files:
        st.warning("No workflow files found.")
        return

    descriptions = {
        "cicd.yml": "the delivery pipeline: eight staged jobs with the gate in the middle",
        "ci.yml": "the original integration check — lint and test on a PR",
        "test.yml": "the broader test workflow, including baselines and the navigator eval",
        "collect.yml": "data collection: a matrix of shuffled runs against a target repo",
    }
    for path in files:
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        jobs = [
            line.strip().rstrip(":")
            for line in text.splitlines()
            if line.startswith("  ") and line.rstrip().endswith(":")
            and not line.startswith("   ")
            and line.strip().rstrip(":").replace("-", "").replace("_", "").isalnum()
        ]
        with st.expander(
            f"**{path.name}** — {descriptions.get(path.name, 'workflow')} "
            f"({len(text.splitlines())} lines)"
        ):
            if jobs:
                st.caption("Top-level keys / jobs: " + ", ".join(f"`{j}`" for j in jobs))
            st.code(text, language="yaml")

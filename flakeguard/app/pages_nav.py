"""The two navigator pages: the knowledge tree, and the AST/jedi trace.

These answer the question the rest of the dashboard assumes: the evidence
bundle contains *this* code, so why that code and not some other code?

``render_knowledge_tree`` draws the tree the navigator built -- what the test
reaches, how far away each thing is, and which resolver found it.

``render_trace`` replays how it was built, one step at a time: the AST walk
collecting names out of the test body, then jedi resolving each one, then the
expansion hops going deeper. It is a player, not a summary -- you can step
through a real navigation and watch the tree fill in.

Both pages read exported JSON by default so they open with no checkout and no
warm cache, and both will re-run the navigator live against a repository on
disk when one is available.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from flakeguard.app import viz


def _sec(label: str) -> None:
    st.markdown(f'<div class="sec-label">{label}</div>', unsafe_allow_html=True)


def _metric_row(theme: dict, items: list[tuple[str, str]]) -> None:
    cols = st.columns(len(items))
    for col, (value, label) in zip(cols, items):
        col.markdown(
            f'<div class="metric-box"><div class="val">{value}</div>'
            f'<div class="lbl">{label}</div></div>',
            unsafe_allow_html=True,
        )


def _note(theme: dict, text: str) -> None:
    st.markdown(
        f'<div style="background:{theme["evidence_bg"]};border-left:3px solid '
        f'{theme["accent"]};border-radius:0 8px 8px 0;padding:12px 16px;'
        f'font-size:0.88rem;color:{theme["text_soft"]};line-height:1.65;'
        f'margin-bottom:14px">{text}</div>',
        unsafe_allow_html=True,
    )


# ============================================================ source selection


def _pick_source(theme: dict, key: str) -> tuple[dict | None, str, dict | None]:
    """Choose a case and return (payload, source label, set summary).

    Offers every exported tree set, plus a live run when a repository is
    reachable. The live path is what makes the page a demo rather than a
    screenshot: pick a repo, pick a test, watch the navigator work.
    """
    sets = viz.tree_dirs()
    options = list(sets) + ["live run (navigate a repo now)"]
    choice = st.selectbox(
        "Source",
        options,
        key=f"{key}_source",
        help=(
            "Exported sets come from scripts/export_knowledge_trees.py, which "
            "CI runs on every push. A live run navigates a checkout on this "
            "machine right now."
        ),
    )

    if choice != "live run (navigate a repo now)":
        directory = sets[choice]
        index = viz.load_tree_index(directory)
        if not index:
            st.warning(f"No exported trees in `{directory}`.")
            return None, choice, None
        case = st.selectbox(
            "Test case",
            list(index),
            key=f"{key}_case",
            format_func=lambda cid: cid.split("/")[-1],
        )
        return viz.load_tree(index[case]), choice, viz.load_summary(directory)

    return _live_run(theme, key), "live run", None


def _live_run(theme: dict, key: str) -> dict | None:
    """Navigate a repository on this machine and build a tree from scratch."""
    from flakeguard.app import repos

    _note(
        theme,
        "A live run imports the navigator and resolves a real test id against a "
        "real checkout. You can provide a local folder path (e.g. <code>C:\\...</code>) "
        "or a Git clone URL. Nothing is read from <code>results/</code> — the tree and "
        "the trace below are produced on the spot.",
    )
    col_repo, col_name = st.columns([3, 1])
    repo = col_repo.text_input(
        "Repository path or Git URL",
        value=".",
        key=f"{key}_repo",
        help="Local folder path or git clone URL. '.' is FlakeGuard itself, which carries the synthetic benchmark.",
    )
    repo_name = col_name.text_input("Repo label", value="", key=f"{key}_name", placeholder="auto-derived")

    clean_repo = (repo or "").strip().strip('"').strip("'").strip()
    discovered_tests: list[dict] = []
    target_dir: Path | None = None
    resolve_err: str = ""

    if clean_repo:
        try:
            resolved = repos.resolve(clean_repo)
            target_dir = resolved.path
            discovered_tests = repos.discover_tests(target_dir, limit=100)
        except repos.RepoError as exc:
            resolve_err = str(exc)
        except Exception as exc:
            resolve_err = f"Failed to inspect repository: {exc}"

    if discovered_tests:
        test_ids = [t["test_id"] for t in discovered_tests]
        default_idx = 0
        for i, tid in enumerate(test_ids):
            if "test_connect_launches" in tid or "test_agent_chrome_command" in tid:
                default_idx = i
                break
            elif "test_suite_02" in tid:
                default_idx = i
                break

        test_options = ["✏️ Enter custom test ID..."] + test_ids
        pick = st.selectbox(
            "Discovered Tests in Repository (select to navigate)",
            test_options,
            index=default_idx + 1,
            key=f"{key}_pick",
            help=f"Found {len(discovered_tests)} tests in {clean_repo}. Pick one or enter custom.",
        )
        if pick == "✏️ Enter custom test ID...":
            test_id = st.text_input(
                "Test id",
                value="",
                key=f"{key}_tid",
                help="A pytest node id: path::Class::test_name",
            )
        else:
            test_id = pick
    else:
        test_id = st.text_input(
            "Test id",
            value="synthetic/tests/test_suite_02.py::test_case_13",
            key=f"{key}_tid",
            help="A pytest node id: path::Class::test_name",
        )

    payload_key = f"{key}_live_payload"
    col_btn1, col_btn2 = st.columns([1, 4])
    clicked = col_btn1.button("Navigate", key=f"{key}_go", type="primary")
    if col_btn2.button("Reset / Clear", key=f"{key}_clear"):
        st.session_state.pop(payload_key, None)
        st.rerun()

    if clicked:
        if resolve_err:
            st.error(resolve_err)
            return None

        if not target_dir or not target_dir.is_dir():
            st.error(f"`{clean_repo}` is not a valid directory.")
            return None

        effective_name = repo_name.strip()
        if not effective_name:
            effective_name = target_dir.name or "custom"

        clean_test_id = (test_id or "").strip().strip('"').strip("'").strip()
        if not clean_test_id:
            st.error("Please specify a test id to navigate.")
            return None

        from flakeguard.navigator.ast_nav import AstNavigator

        with st.spinner(f"Navigating {clean_test_id} …"):
            try:
                nav = AstNavigator(target_dir, repo=effective_name, sha="live")
                explained = nav.explain(clean_test_id)
            except Exception as exc:
                st.error(f"Navigation failed: {type(exc).__name__}: {exc}")
                return None

        payload = explained.to_dict(include_text=True)
        payload["rendered"] = explained.tree.render()
        payload["rows"] = explained.tree.rows()
        payload["repo_dir"] = str(target_dir)
        payload["navigated_test"] = clean_test_id
        if not explained.result.code_under_test and not explained.result.shared_state:
            payload["_empty_warning"] = clean_test_id
        st.session_state[payload_key] = payload

    cached = st.session_state.get(payload_key)
    if cached is None:
        st.info("Set a repository and a test id, then press **Navigate**.")
        return None

    if cached.get("_empty_warning"):
        warn_id = cached["_empty_warning"]
        st.warning(
            f"`{warn_id}` resolved to nothing. Check the test id against the repository — "
            "the trace below still shows where it stopped."
        )
        if target_dir:
            sample_tests = repos.discover_tests(target_dir, limit=5)
            if sample_tests:
                st.info(
                    "💡 **Sample test IDs discovered in this repository:**\n\n"
                    + "\n".join(f"- `{t['test_id']}`" for t in sample_tests)
                )

    if cached.get("navigated_test"):
        st.caption(f"⚡ *Showing active navigation for:* `{cached['navigated_test']}`")
    return cached


def _generate_tree_dot(
    rows: list[dict],
    theme: dict,
    dark: bool,
    orientation: str = "TB",
    highlight_id: str | None = None,
) -> str:
    """Generate a clean Graphviz DOT string for the hierarchical knowledge tree."""
    font = "Inter, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif"
    edge_color = "#D4A843" if dark else "#64748b"
    label_edge_color = "#E8DCC8" if dark else "#334155"

    dot = [
        "digraph KnowledgeTree {",
        f'    graph [rankdir={orientation}, bgcolor="transparent", fontname="{font}", nodesep=0.35, ranksep=0.75, pad=0.2];',
        f'    node [shape=box, style="filled,rounded", fontname="{font}", fontsize=10.5, penwidth=1.5, margin="0.18,0.12"];',
        f'    edge [fontname="{font}", fontsize=9, fontcolor="{label_edge_color}", color="{edge_color}", penwidth=1.5, arrowsize=0.7];',
    ]

    nid_map = {r["id"]: f"n_{i}" for i, r in enumerate(rows)}

    # Group by depth so rank levels stay mathematically organized as a tree hierarchy
    by_depth: dict[int, list[str]] = {}
    for r in rows:
        by_depth.setdefault(r.get("depth", 0), []).append(nid_map[r["id"]])

    for d, nids in by_depth.items():
        dot.append(f'    {{ rank=same; {"; ".join(nids)}; }}')

    for r in rows:
        nid = nid_map[r["id"]]
        raw_label = r.get("label", "node")
        kind = r.get("kind", "")
        depth = r.get("depth", 0)
        via = r.get("via", "ast")
        edge = r.get("edge", "")
        path = r.get("path", "")
        start_line = r.get("start_line", 0)
        file_hint = f"{Path(path).name}:{start_line}" if path else ""
        is_highlighted = (r["id"] == highlight_id)

        if depth == 0 or edge == "root":
            fill = "#2e1065" if dark else "#fef3c7"
            border = "#D4A843" if dark else "#b45309"
            font_c = "#F5EDD6" if dark else "#78350f"
            icon = "🧪"
            penwidth = 2.5
        elif edge in ("fixture", "fixture-builds"):
            fill = "#3b1e08" if dark else "#fffbeb"
            border = "#f59e0b" if dark else "#d97706"
            font_c = "#fef3c7" if dark else "#92400e"
            icon = "🔧"
            penwidth = 1.5
        elif edge == "smells":
            fill = "#4c0519" if dark else "#fff1f2"
            border = "#f43f5e" if dark else "#e11d48"
            font_c = "#ffe4e6" if dark else "#9f1239"
            icon = "⚠️"
            penwidth = 1.5
        elif via == "jedi":
            fill = "#064e3b" if dark else "#ecfdf5"
            border = "#10b981" if dark else "#059669"
            font_c = "#d1fae5" if dark else "#065f46"
            icon = "🔍"
            penwidth = 1.8
        else:
            fill = "#1e1b4b" if dark else "#eff6ff"
            border = "#6366f1" if dark else "#3b82f6"
            font_c = "#e0e7ff" if dark else "#1e3a8a"
            icon = "⚡"
            penwidth = 1.5

        if is_highlighted:
            border = "#F59E0B" if dark else "#D97706"
            penwidth = 3.5

        safe_label = raw_label.replace('"', '\\"').replace("\n", " ")
        if len(safe_label) > 38:
            safe_label = safe_label[:35] + "…"
        safe_file = file_hint.replace('"', '\\"')

        lbl = f"{icon} {safe_label}\\n[{kind}] {safe_file} · hop {depth}"
        dot.append(f'    {nid} [label="{lbl}", fillcolor="{fill}", color="{border}", fontcolor="{font_c}", penwidth={penwidth}];')

    for r in rows:
        parent_id = r.get("parent")
        if parent_id and parent_id in nid_map and parent_id != r["id"]:
            p_nid = nid_map[parent_id]
            c_nid = nid_map[r["id"]]
            edge_lbl = r.get("edge", "")
            score = r.get("score")
            score_str = f" [{score:.2f}]" if score is not None and score > 0 else ""
            safe_edge = f"{edge_lbl}{score_str}".replace('"', '\\"')
            dot.append(f'    {p_nid} -> {c_nid} [label=" {safe_edge} "];')

    dot.append("}")
    return "\n".join(dot)


def _get_node_source(
    row: dict, root_node: dict, repo_dir: str = "", test_source: dict | None = None
) -> tuple[str, str]:
    """Retrieve source code text for a node either from tree text, test source, or directly from file."""
    if (row.get("depth") == 0 or row.get("edge") == "root") and test_source and test_source.get("text"):
        return test_source["text"], f"{test_source.get('path', 'test')}:{test_source.get('start_line', 1)}-{test_source.get('end_line', 1)}"

    def find_in_tree(node: dict) -> str | None:
        if node.get("node_id") == row.get("id"):
            return node.get("text")
        for child in node.get("children", []):
            hit = find_in_tree(child)
            if hit:
                return hit
        return None

    text = find_in_tree(root_node) if root_node else None
    if text:
        return text, "extracted from tree"

    path_str = row.get("path")
    if path_str:
        p = Path(path_str)
        if not p.is_absolute() and repo_dir:
            p = Path(repo_dir) / path_str
        elif not p.is_file() and repo_dir:
            p = Path(repo_dir) / path_str

        if p.is_file():
            try:
                lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
                start = max(1, row.get("start_line", 1))
                end = row.get("end_line") or (start + 35)
                end = min(len(lines), max(start, end))
                extracted = "\n".join(lines[start - 1 : end])
                return extracted, f"{p.name}:{start}-{end}"
            except Exception as exc:
                return "", f"could not read file: {exc}"
    return "", "no source available"


def _render_jedi_symbol_card(
    theme: dict,
    dark: bool,
    row: dict,
    root: dict,
    all_rows: list[dict],
    repo_dir: str,
    test_source: dict | None = None,
) -> None:
    """Render the Jedi Definition and Source inspector for the selected symbol."""
    source_code, source_note = _get_node_source(row, root, repo_dir, test_source)

    via = row.get("via", "ast")
    via_label = "Jedi Static Resolution" if via == "jedi" else "AST Lexical Walk"
    via_color = "#10b981" if via == "jedi" else "#6366f1"

    edge = row.get("edge", "root")
    edge_desc = viz.EDGE_HELP.get(edge, edge)

    score = row.get("score")
    score_display = f"{score:.2f}" if score is not None and score > 0 else "—"

    parent_row = next((r for r in all_rows if r["id"] == row.get("parent")), None)
    caller_name = parent_row["label"] if parent_row else "(Root Test)"

    children_rows = [r for r in all_rows if r.get("parent") == row["id"]]
    callees_str = ", ".join(f"`{c['label']}`" for c in children_rows) if children_rows else "*(leaf node — no callees reached)*"

    card_bg = theme["card_bg"]
    card_bd = theme["card_border"]
    txt_soft = theme["text_soft"]
    accent = theme["accent"]

    st.markdown(
        f"""
        <div style="background:{card_bg};border:1.5px solid {card_bd};border-radius:14px;padding:18px 22px;margin:12px 0 16px;">
            <div style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:8px;margin-bottom:12px;">
                <div style="display:flex;align-items:center;gap:10px;">
                    <span style="font-size:1.35rem;font-weight:700;color:{txt_soft};font-family:Yellow Banana,Inter,sans-serif;">{row.get('label')}</span>
                    <span style="background:{via_color}22;color:{via_color};border:1px solid {via_color}66;font-size:0.75rem;padding:3px 8px;border-radius:6px;font-weight:600;">{via_label}</span>
                    <span style="background:{accent}22;color:{accent};border:1px solid {accent}66;font-size:0.75rem;padding:3px 8px;border-radius:6px;font-weight:600;">Hop {row.get('depth', 0)} · {edge}</span>
                </div>
                <div style="font-size:0.8rem;color:{theme['text_muted']};">
                    Relevance Score: <b style="color:{accent};">{score_display}</b>
                </div>
            </div>
            <div style="font-size:0.84rem;color:{txt_soft};line-height:1.6;margin-bottom:10px;">
                📍 <b>Location:</b> <code>{row.get('path', 'unknown')}:{row.get('start_line', 0)}-{row.get('end_line', 0)}</code> ({row.get('kind', 'symbol')})<br>
                🔗 <b>Called by:</b> <code>{caller_name}</code> &nbsp;|&nbsp; <b>Next Callees:</b> {callees_str}<br>
                💡 <b>Edge Meaning:</b> {edge_desc}
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if source_code:
        st.markdown(f"<p style='color:{theme['text_muted']};font-size:0.8rem;margin-bottom:4px;'>📄 <b>Definition Source Code</b> ({source_note}):</p>", unsafe_allow_html=True)
        st.code(source_code, language="python", line_numbers=True)
    else:
        st.info(f"Source code could not be resolved directly for {row.get('path')}. ({source_note})")


# ============================================================== knowledge tree


def render_knowledge_tree(theme: dict, dark: bool) -> None:
    _sec("🌳 Knowledge Tree")
    _note(
        theme,
        "The navigator's answer is four flat lists, which loses the one thing "
        "that explains it: <b>distance from the test</b>. The knowledge tree puts "
        "it back. The root is the failing test; every other node is something the "
        "test reaches, hung under whatever reached it. Colour says which resolver "
        "found it — <b>the AST walk</b> or <b>jedi</b> — and the horizontal axis "
        "is how many hops away it is.",
    )

    payload, source, summary = _pick_source(theme, "tree")
    if payload is None:
        if summary:
            _render_set_summary(theme, dark, summary)
        return

    tree = payload.get("tree", {})
    stats = tree.get("stats", {})
    rows = payload.get("rows") or []
    if not rows:
        st.warning("This export has no node rows; re-run the export script.")
        return

    label = payload.get("label") or "—"
    root_cause = payload.get("root_cause") or "—"
    repo_dir = payload.get("repo_dir", "")

    _metric_row(
        theme,
        [
            (str(stats.get("nodes", 0)), "Nodes in tree"),
            (str(stats.get("max_depth", 0)), "Max hop depth"),
            (str(stats.get("files_touched", 0)), "Files reached"),
            (str(label), "Ground-truth label"),
            (str(root_cause), "Root cause"),
        ],
    )
    st.markdown("<br>", unsafe_allow_html=True)

    max_depth = max(int(stats.get("max_depth", 0)), 1)
    ctrl_col1, ctrl_col2 = st.columns([2, 1])
    with ctrl_col1:
        depth_limit = st.slider(
            "Show hops up to",
            min_value=0,
            max_value=max_depth,
            value=max_depth,
            key="tree_depth",
            help=(
                "Hop 1 is code the test names directly. Hop 2 and beyond is what "
                "that code is built on — base classes, decorators, callees. Drag to "
                "0 to see the test alone."
            ),
        )
    with ctrl_col2:
        orientation_choice = st.radio(
            "Tree Layout Direction",
            ["⬇️ Top-to-Bottom (AST Tree)", "➡️ Left-to-Right (Call Flow)"],
            horizontal=True,
            key="tree_orientation",
        )
        dot_orientation = "TB" if "Top-to-Bottom" in orientation_choice else "LR"

    shown = [row for row in rows if row["depth"] <= depth_limit]

    sel_node_key = "tree_selected_node_id"
    active_node_id = st.session_state.get(sel_node_key)
    if not active_node_id or not any(r["id"] == active_node_id for r in shown):
        default_node = next((r for r in shown if r.get("depth", 0) > 0), shown[0])
        active_node_id = default_node["id"]
        st.session_state[sel_node_key] = active_node_id

    # 1. VISUAL HIERARCHICAL TREE
    _sec("🌳 Knowledge Tree Hierarchy")
    st.caption("Visual directed graph from root test through AST walk and Jedi symbol resolution. Golden border highlights the currently inspected symbol.")
    dot_str = _generate_tree_dot(shown, theme, dark, orientation=dot_orientation, highlight_id=active_node_id)
    st.graphviz_chart(dot_str, use_container_width=True)
    _legend_note(theme, shown)

    # 2. INTERACTIVE TREE EXPLORER & JEDI INSPECTOR
    _sec("🔍 Jedi Symbol Inspector — Go to Definition")
    st.caption("Click any symbol node in the tree hierarchy below or choose from the dropdown to open its definition in Jedi.")

    with st.expander("🌲 Interactive Tree Explorer (Click any node to open with Jedi)", expanded=True):
        st.caption("Browse the tree depth hierarchy and click **Inspect with Jedi** on any symbol to open its definition.")
        for r in shown:
            d = r.get("depth", 0)
            indent = "&nbsp;&nbsp;&nbsp;&nbsp;" * d
            branch = "└─ " if d > 0 else ""
            icon = "🧪" if d == 0 else ("🔍" if r.get("via") == "jedi" else "⚡")
            is_cur = (r["id"] == active_node_id)
            cur_marker = " 👈 <b>[ACTIVE]</b>" if is_cur else ""
            path_hint = f"({Path(r['path']).name}:{r['start_line']})" if r.get("path") else ""

            c_text, c_btn = st.columns([4, 1])
            c_text.markdown(
                f"<div style='font-family:monospace;font-size:0.86rem;padding:4px 0;'>"
                f"{indent}{branch}{icon} <b>{r['label']}</b> <span style='color:{theme['text_muted']};'>{path_hint} · hop {d}</span>{cur_marker}</div>",
                unsafe_allow_html=True,
            )
            if c_btn.button("Inspect 🔍", key=f"btn_inspect_{r['id']}", type="primary" if is_cur else "secondary"):
                st.session_state[sel_node_key] = r["id"]
                st.rerun()

    symbol_options = []
    symbol_id_to_idx = {}
    for i, r in enumerate(shown):
        icon = "🧪" if r.get("depth") == 0 else ("🔍" if r.get("via") == "jedi" else "⚡")
        file_hint = f"({Path(r['path']).name}:{r['start_line']})" if r.get("path") else ""
        opt_text = f"{icon} {r['label']} {file_hint} — hop {r['depth']} · {r['edge']}"
        symbol_options.append(opt_text)
        symbol_id_to_idx[r["id"]] = i

    cur_idx = symbol_id_to_idx.get(active_node_id, 0)
    selected_sym_text = st.selectbox(
        "Jump to symbol definition in tree:",
        symbol_options,
        index=cur_idx,
        key="tree_jedi_inspector_dropdown",
    )
    selected_idx = symbol_options.index(selected_sym_text)
    selected_row = shown[selected_idx]
    if selected_row["id"] != active_node_id:
        st.session_state[sel_node_key] = selected_row["id"]
        st.rerun()

    _render_jedi_symbol_card(
        theme,
        dark,
        selected_row,
        tree.get("root", {}),
        shown,
        repo_dir,
        test_source=payload.get("test_source"),
    )

    # 3. DETAILED ANALYTICS & ALTERNATIVE VIEWS
    tab_containment, tab_scatter, tab_text, tab_table = st.tabs([
        "📐 Containment & Hop Dist",
        "🧭 Scatter Layout",
        "🪵 Tree as Text",
        "🔎 Node Table",
    ])

    with tab_containment:
        c1, c2 = st.columns([1, 1])
        with c1:
            st.plotly_chart(_icicle_figure(shown, theme, dark), use_container_width=True, key="tree_icicle")
        with c2:
            st.plotly_chart(_depth_bar_figure(shown, theme, dark), use_container_width=True, key="tree_depthbar")

    with tab_scatter:
        st.plotly_chart(_node_link_figure(shown, theme, dark), use_container_width=True, key="tree_nodelink")

    with tab_text:
        st.code(payload.get("rendered") or "(not exported)", language="text")

    with tab_table:
        frame = pd.DataFrame(shown)
        frame["why"] = frame["edge"].map(lambda e: viz.EDGE_HELP.get(e, ""))
        display = frame[
            ["depth", "edge", "via", "label", "kind", "score", "path", "start_line", "lines", "why"]
        ].rename(
            columns={
                "depth": "hop",
                "edge": "edge",
                "via": "found by",
                "label": "name",
                "kind": "kind",
                "score": "score",
                "path": "file",
                "start_line": "line",
                "lines": "LOC",
                "why": "what the edge means",
            }
        )
        st.dataframe(display, use_container_width=True, hide_index=True)

    if summary:
        _render_set_summary(theme, dark, summary)


def _legend_note(theme: dict, rows: list[dict]) -> None:
    palette = viz.resolvers(True)
    edges = sorted({row["edge"] for row in rows if row["edge"] != "root"})
    chips = " ".join(
        f'<span style="background:{theme["evidence_tag_bg"]};color:{theme["text_soft"]};'
        f'padding:3px 9px;border-radius:7px;font-size:0.74rem;margin-right:6px;'
        f'display:inline-block;margin-bottom:5px">'
        f'{edge} — {viz.EDGE_HELP.get(edge, "")}</span>'
        for edge in edges
    )
    st.markdown(
        f'<p style="color:{theme["text_faint"]};font-size:0.76rem;margin:2px 0 10px">'
        f'Marker shape encodes the edge as well as its colour, so the chart survives '
        f'greyscale. <span style="color:{palette["ast"]};font-weight:700">●</span> AST '
        f'&nbsp; <span style="color:{palette["jedi"]};font-weight:700">●</span> jedi'
        f'</p><div style="margin-bottom:12px">{chips}</div>',
        unsafe_allow_html=True,
    )


def _node_link_figure(rows: list[dict], theme: dict, dark: bool) -> go.Figure:
    """Depth on x, tidy-tree placement on y, resolver as the only hue."""
    nodes, edges = viz.layout_nodes(rows)
    palette = viz.resolvers(dark)
    figure = go.Figure()

    # Edges first so markers sit on top of them.
    edge_x: list[float | None] = []
    edge_y: list[float | None] = []
    for parent, child in edges:
        edge_x += [parent["x"], child["x"], None]
        edge_y += [parent["y"], child["y"], None]
    if edge_x:
        figure.add_trace(
            go.Scatter(
                x=edge_x,
                y=edge_y,
                mode="lines",
                line={"color": viz.tree_edge(dark), "width": 2},
                hoverinfo="skip",
                showlegend=False,
            )
        )

    scores = [node["score"] for node in nodes if node["score"]]
    top_score = max(scores) if scores else 1.0

    for via, color, name in (
        ("ast", palette["ast"], "found by the AST walk"),
        ("jedi", palette["jedi"], "found by jedi"),
    ):
        group = [n for n in nodes if (n["via"] if n["via"] != "-" else "ast") == via]
        if not group:
            continue
        figure.add_trace(
            go.Scatter(
                x=[n["x"] for n in group],
                y=[n["y"] for n in group],
                mode="markers+text",
                name=name,
                marker={
                    "color": color,
                    "size": [
                        10 + 16 * (n["score"] / top_score if top_score else 0)
                        for n in group
                    ],
                    "symbol": [viz.EDGE_SYMBOL.get(n["edge"], "circle") for n in group],
                    "line": {"color": theme["plot_bg"], "width": 2},
                },
                text=[n["label"] for n in group],
                textposition="middle right",
                textfont={"color": theme["plot_text"], "size": 11},
                customdata=[
                    [
                        n["edge"],
                        n["kind"],
                        n["score"],
                        f"{n['path']}:{n['start_line']}" if n["path"] else "—",
                        viz.EDGE_HELP.get(n["edge"], ""),
                    ]
                    for n in group
                ],
                hovertemplate=(
                    "<b>%{text}</b><br>hop %{x} · edge %{customdata[0]}"
                    "<br>kind %{customdata[1]} · score %{customdata[2]}"
                    "<br>%{customdata[3]}<br><i>%{customdata[4]}</i><extra></extra>"
                ),
            )
        )

    depths = sorted({int(n["x"]) for n in nodes})
    figure.update_layout(
        **viz.plotly_layout(
            theme,
            height=max(340, 54 * max(1, len([n for n in nodes if not n.get("_p")]))),
            xaxis=viz.axis(
                theme,
                "hops from the test  →",
                tickmode="array",
                tickvals=depths,
                ticktext=[("the test" if d == 0 else f"hop {d}") for d in depths],
                range=[-0.35, max(depths) + 0.9],
            ),
            yaxis=viz.axis(theme, "", showticklabels=False, showgrid=False),
        )
    )
    figure.update_layout(height=max(320, 46 * len(nodes)))
    return figure


def _icicle_figure(rows: list[dict], theme: dict, dark: bool) -> go.Figure:
    """Containment, coloured by hop depth off the single-hue gold ramp."""
    max_depth = max((row["depth"] for row in rows), default=0)
    figure = go.Figure(
        go.Icicle(
            ids=[row["id"] for row in rows],
            labels=[row["label"] for row in rows],
            parents=[row["parent"] for row in rows],
            values=[max(1, row["lines"] or 1) for row in rows],
            # "remainder", not "total": each value is that node's OWN size in
            # lines, and plotly adds the children on top. With "total" a parent
            # would have to be at least as big as its children combined, which
            # is not true here -- the root is a test id with no lines at all,
            # and a subclass is routinely shorter than the base it extends.
            branchvalues="remainder",
            marker={
                "colors": [
                    viz.depth_color(row["depth"], max_depth, dark) for row in rows
                ],
                "line": {"color": theme["plot_bg"], "width": 2},
            },
            tiling={"orientation": "h"},
            textfont={"size": 11},
            customdata=[[row["edge"], row["depth"]] for row in rows],
            hovertemplate=(
                "<b>%{label}</b><br>hop %{customdata[1]} · %{customdata[0]}"
                "<br>%{value} lines<extra></extra>"
            ),
        )
    )
    figure.update_layout(**viz.plotly_layout(theme, height=360, margin={"l": 0, "r": 0, "t": 10, "b": 10}))
    return figure


def _depth_bar_figure(rows: list[dict], theme: dict, dark: bool) -> go.Figure:
    counts: dict[int, int] = {}
    for row in rows:
        counts[row["depth"]] = counts.get(row["depth"], 0) + 1
    depths = sorted(counts)
    max_depth = max(depths) if depths else 0
    figure = go.Figure(
        go.Bar(
            x=[("the test" if d == 0 else f"hop {d}") for d in depths],
            y=[counts[d] for d in depths],
            marker={
                "color": [viz.depth_color(d, max_depth, dark, marks=True) for d in depths],
                "line": {"color": theme["plot_bg"], "width": 2},
                "cornerradius": 4,
            },
            text=[counts[d] for d in depths],
            textposition="outside",
            textfont={"color": theme["plot_text"]},
            hovertemplate="%{x}: %{y} node(s)<extra></extra>",
        )
    )
    figure.update_layout(
        **viz.plotly_layout(
            theme,
            height=360,
            showlegend=False,
            xaxis=viz.axis(theme, "", showgrid=False),
            yaxis=viz.axis(theme, "nodes", rangemode="tozero"),
        )
    )
    return figure


def _show_source(theme: dict, root: dict, row: dict) -> None:
    """The source text for a node, if the export carried it."""

    def find(node: dict) -> dict | None:
        if node.get("node_id") == row["id"]:
            return node
        for child in node.get("children", []):
            hit = find(child)
            if hit is not None:
                return hit
        return None

    node = find(root) if root else None
    text = (node or {}).get("text")
    header = f"{row['path']}:{row['start_line']}-{row['end_line']}  ({row['kind']})"
    st.caption(header)
    if text:
        st.code(text, language="python")
    else:
        st.info(
            "This export was written without source text. Re-run "
            "`scripts/export_knowledge_trees.py --with-text`, or use a live run."
        )


def _render_set_summary(theme: dict, dark: bool, summary: dict) -> None:
    """Across-the-set numbers, so one case is not mistaken for the result."""
    st.divider()
    _sec("📦 Across the whole exported set")
    _metric_row(
        theme,
        [
            (str(summary.get("cases", 0)), "Cases navigated"),
            (f"{summary.get('resolution_rate', 0):.0%}", "Resolved to something"),
            (str(summary.get("mean_tree_nodes", 0)), "Mean nodes per tree"),
            (str(summary.get("max_tree_depth", 0)), "Deepest tree"),
            (f"{summary.get('jedi_hit_rate', 0):.0%}", "jedi hit rate"),
        ],
    )
    unresolved = summary.get("unresolved_cases") or []
    if unresolved:
        st.warning(
            f"{len(unresolved)} case(s) resolved to nothing: "
            + ", ".join(c.split("/")[-1] for c in unresolved[:8])
        )
    st.caption(
        f"Repo `{summary.get('repo', '?')}` @ `{summary.get('sha', '?')}` · "
        f"gold `{summary.get('gold', '?')}` · median "
        f"{summary.get('median_ms', 0)} ms, max {summary.get('max_ms', 0)} ms per case."
    )


# ================================================================== the trace


def render_trace(theme: dict, dark: bool) -> None:
    _sec("🔬 AST → jedi: how the search actually runs")
    _note(
        theme,
        "Navigation is two different machines in sequence. First the <b>AST walk</b> "
        "reads the test body and writes down every name it sees — that is pure "
        "syntax, no types, and it is what decides the work list. Then <b>jedi</b> "
        "takes each name and resolves it: <code>goto</code> for a name, "
        "<code>infer</code> for an expression whose <i>type</i> is the real target "
        "(<code>cache[1] = 1</code> never names <code>__setitem__</code>). "
        "Finally the <b>expansion</b> hops take the definitions just found and goes "
        "one level deeper into their bases, decorators and callees. "
        "Every one of those steps is recorded below, in order.",
    )

    payload, source, _ = _pick_source(theme, "trace")
    if payload is None:
        return

    trace = payload.get("trace", {})
    events = trace.get("events", [])
    summary = trace.get("summary", {})
    if not events:
        st.warning("This export carries no trace events.")
        return

    _metric_row(
        theme,
        [
            (str(summary.get("ast_names", 0)), "Names the AST walk found"),
            (str(summary.get("jedi_goto_calls", 0)), "jedi.goto calls"),
            (str(summary.get("jedi_infer_calls", 0)), "jedi.infer calls"),
            (f"{summary.get('jedi_hit_rate', 0):.0%}", "jedi hit rate"),
            (str(summary.get("max_depth", 0)), "Deepest hop reached"),
        ],
    )
    st.markdown("<br>", unsafe_allow_html=True)

    _sec("▶️ Step through the navigation")
    st.caption(
        "Every step the navigator took, in order. Drag to replay it: the chart "
        "highlights where you are and the card below says what that step did."
    )
    position = st.slider(
        "Step",
        min_value=1,
        max_value=len(events),
        value=len(events),
        key="trace_step",
        help="Step 1 is parsing the test file; the last step is the smell scan.",
    )
    st.plotly_chart(
        _raster_figure(events, position, theme, dark),
        use_container_width=True,
        key="trace_raster",
    )
    _step_card(theme, events[position - 1], len(events))

    left, right = st.columns([1, 1])
    with left:
        _sec("🪜 Steps per hop depth")
        st.plotly_chart(
            _trace_depth_figure(events, theme, dark),
            use_container_width=True,
            key="trace_depth",
        )
    with right:
        _sec("🎯 Did jedi resolve it?")
        st.plotly_chart(
            _hit_figure(events, theme, dark),
            use_container_width=True,
            key="trace_hits",
        )

    _sec("⏱️ Where the time went")
    st.plotly_chart(
        _phase_time_figure(summary, theme, dark), use_container_width=True, key="trace_ms"
    )

    _sec("🧾 The full trace")
    frame = pd.DataFrame(events)
    frame["phase means"] = frame["phase"].map(lambda p: viz.PHASE_HELP.get(p, ""))
    columns = [
        "seq",
        "phase",
        "op",
        "label",
        "depth",
        "via",
        "results",
        "kept",
        "duration_ms",
        "path",
        "line",
        "detail",
    ]
    show_all = st.checkbox(
        "Show every step (otherwise only the resolver calls)",
        value=False,
        key="trace_all",
    )
    table = frame if show_all else frame[frame["phase"].str.startswith("jedi")]
    st.dataframe(
        table[columns].rename(
            columns={
                "seq": "#",
                "op": "operation",
                "label": "subject",
                "depth": "hop",
                "via": "resolver",
                "results": "returned",
                "kept": "kept",
                "duration_ms": "ms",
                "line": "line",
            }
        ),
        use_container_width=True,
        hide_index=True,
        height=420,
    )
    st.caption(
        "**returned** is how many definitions jedi handed back; **kept** is how "
        "many survived filtering — a definition in the standard library or in "
        "site-packages is not this repository's code under test. The gap between "
        "those two columns is where the navigator's precision comes from."
    )


def _raster_figure(events: list[dict], position: int, theme: dict, dark: bool) -> go.Figure:
    """One row per phase, one mark per step. Position carries phase identity.

    Phase is not coloured: nine categorical hues cannot be told apart, and the
    row a mark sits on already names its phase unambiguously. Colour is spent
    on hop depth instead, which is a magnitude and takes a single-hue ramp.
    """
    order = [p for p in viz.PHASE_HELP if any(e["phase"] == p for e in events)]
    row_of = {phase: index for index, phase in enumerate(order)}
    max_depth = max((e["depth"] for e in events), default=0)
    palette = viz.resolvers(dark)

    figure = go.Figure()
    done = [e for e in events if e["seq"] <= position]
    todo = [e for e in events if e["seq"] > position]

    if todo:
        figure.add_trace(
            go.Scatter(
                x=[e["seq"] for e in todo],
                y=[row_of[e["phase"]] for e in todo],
                mode="markers",
                name="not yet run",
                marker={
                    "color": theme["plot_grid"],
                    "size": 7,
                    "symbol": "circle-open",
                },
                hoverinfo="skip",
            )
        )

    figure.add_trace(
        go.Scatter(
            x=[e["seq"] for e in done],
            y=[row_of[e["phase"]] for e in done],
            mode="markers",
            name="run so far",
            marker={
                "color": [
                    viz.depth_color(e["depth"], max_depth, dark, marks=True)
                    for e in done
                ],
                "size": [9 + min(14, (e["duration_ms"] or 0) / 6) for e in done],
                "symbol": [
                    "x" if not e.get("ok", True) else "circle" for e in done
                ],
                "line": {"color": theme["plot_bg"], "width": 1.5},
            },
            customdata=[
                [
                    e["phase"],
                    e["op"],
                    e["label"][:60],
                    e["depth"],
                    e["results"],
                    e["kept"],
                    round(e["duration_ms"], 2),
                ]
                for e in done
            ],
            hovertemplate=(
                "step %{x} · <b>%{customdata[0]}</b> / %{customdata[1]}"
                "<br>%{customdata[2]}<br>hop %{customdata[3]} · "
                "returned %{customdata[4]}, kept %{customdata[5]}"
                "<br>%{customdata[6]} ms<extra></extra>"
            ),
        )
    )

    current = events[position - 1]
    figure.add_vline(
        x=current["seq"],
        line_width=2,
        line_dash="dash",
        line_color=palette["jedi"],
    )

    figure.update_layout(
        **viz.plotly_layout(
            theme,
            height=70 + 42 * len(order),
            xaxis=viz.axis(theme, "step  →", rangemode="tozero"),
            yaxis=viz.axis(
                theme,
                "",
                tickmode="array",
                tickvals=list(range(len(order))),
                ticktext=order,
                autorange="reversed",
                showgrid=True,
            ),
        )
    )
    return figure


def _step_card(theme: dict, event: dict, total: int) -> None:
    ok = event.get("ok", True)
    accent = theme["accent"] if ok else viz.STATUS["serious"]
    where = (
        f'{event["path"]}:{event["line"]}' if event.get("path") else "—"
    )
    kept = event.get("kept", 0)
    results = event.get("results", 0)
    verdict = (
        f"returned {results}, kept {kept}"
        if event["phase"].startswith("jedi")
        else f"{results} item(s)"
    )
    st.markdown(
        f"""
        <div style="background:{theme["card_bg"]};border:1px solid {theme["card_border"]};
        border-left:4px solid {accent};border-radius:0 12px 12px 0;padding:18px 22px">
          <div style="color:{theme["text_faint"]};font-size:0.72rem;font-weight:700;
          letter-spacing:0.08em;text-transform:uppercase;margin-bottom:6px">
            Step {event["seq"]} of {total} &nbsp;·&nbsp; {event["phase"]} / {event["op"]}
            &nbsp;·&nbsp; hop {event["depth"]} &nbsp;·&nbsp; via {event["via"]}
            {"" if ok else " &nbsp;·&nbsp; FAILED"}
          </div>
          <div style="color:{theme["text"]};font-size:1.05rem;font-weight:600;
          font-family:ui-monospace,SFMono-Regular,Menlo,monospace;margin-bottom:8px">
            {event["label"]}
          </div>
          <div style="color:{theme["text_muted"]};font-size:0.86rem;line-height:1.7">
            <b>What this phase does:</b> {viz.PHASE_HELP.get(event["phase"], "—")}<br>
            <b>This step:</b> {event.get("detail") or "—"}<br>
            <b>Outcome:</b> {verdict} &nbsp;·&nbsp; {event.get("duration_ms", 0)} ms
            &nbsp;·&nbsp; <code>{where}</code>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _trace_depth_figure(events: list[dict], theme: dict, dark: bool) -> go.Figure:
    counts: dict[int, int] = {}
    for event in events:
        counts[event["depth"]] = counts.get(event["depth"], 0) + 1
    depths = sorted(counts)
    max_depth = max(depths) if depths else 0
    figure = go.Figure(
        go.Bar(
            x=[("the test body" if d == 0 else f"hop {d}") for d in depths],
            y=[counts[d] for d in depths],
            marker={
                "color": [viz.depth_color(d, max_depth, dark, marks=True) for d in depths],
                "line": {"color": theme["plot_bg"], "width": 2},
                "cornerradius": 4,
            },
            text=[counts[d] for d in depths],
            textposition="outside",
            textfont={"color": theme["plot_text"]},
            hovertemplate="%{x}: %{y} step(s)<extra></extra>",
        )
    )
    figure.update_layout(
        **viz.plotly_layout(
            theme,
            height=340,
            showlegend=False,
            xaxis=viz.axis(theme, "", showgrid=False),
            yaxis=viz.axis(theme, "navigation steps", rangemode="tozero"),
        )
    )
    return figure


def _hit_figure(events: list[dict], theme: dict, dark: bool) -> go.Figure:
    """goto vs infer, split into resolved / returned nothing.

    Two bars, two segments. The segments are a state, not a series, so they
    use the reserved status colours and are both directly labelled.
    """
    palette = viz.resolvers(dark)
    groups = [("jedi_goto", "jedi.goto"), ("jedi_infer", "jedi.infer")]
    hits, misses = [], []
    for phase, _ in groups:
        calls = [e for e in events if e["phase"] == phase]
        hits.append(sum(1 for e in calls if e["results"]))
        misses.append(sum(1 for e in calls if not e["results"]))

    figure = go.Figure()
    figure.add_trace(
        go.Bar(
            name="resolved to a definition",
            x=[name for _, name in groups],
            y=hits,
            marker={
                "color": palette["jedi"],
                "line": {"color": theme["plot_bg"], "width": 2},
                "cornerradius": 4,
            },
            text=hits,
            textposition="inside",
            textfont={"color": "#ffffff"},
            hovertemplate="%{x}: %{y} resolved<extra></extra>",
        )
    )
    figure.add_trace(
        go.Bar(
            name="returned nothing",
            x=[name for _, name in groups],
            y=misses,
            marker={
                "color": viz.STATUS["neutral"],
                "line": {"color": theme["plot_bg"], "width": 2},
                "cornerradius": 4,
            },
            text=misses,
            textposition="inside",
            textfont={"color": "#ffffff"},
            hovertemplate="%{x}: %{y} unresolved<extra></extra>",
        )
    )
    figure.update_layout(
        **viz.plotly_layout(
            theme,
            height=340,
            barmode="stack",
            bargap=0.45,
            xaxis=viz.axis(theme, "", showgrid=False),
            yaxis=viz.axis(theme, "calls", rangemode="tozero"),
        )
    )
    return figure


def _phase_time_figure(summary: dict, theme: dict, dark: bool) -> go.Figure:
    ms = summary.get("ms_by_phase", {})
    ordered = [(p, ms[p]) for p in viz.PHASE_HELP if ms.get(p)]
    if not ordered:
        ordered = sorted(ms.items(), key=lambda kv: -kv[1])
    ramp = viz.gold_scale(dark, marks=True)
    figure = go.Figure(
        go.Bar(
            y=[phase for phase, _ in ordered],
            x=[round(value, 2) for _, value in ordered],
            orientation="h",
            marker={
                "color": ramp[-2],
                "line": {"color": theme["plot_bg"], "width": 2},
                "cornerradius": 4,
            },
            text=[f"{value:.1f} ms" for _, value in ordered],
            textposition="outside",
            textfont={"color": theme["plot_text"]},
            customdata=[viz.PHASE_HELP.get(phase, "") for phase, _ in ordered],
            hovertemplate="<b>%{y}</b>: %{x} ms<br><i>%{customdata}</i><extra></extra>",
        )
    )
    figure.update_layout(
        **viz.plotly_layout(
            theme,
            height=60 + 40 * max(1, len(ordered)),
            showlegend=False,
            margin={"l": 120, "r": 70, "t": 20, "b": 40},
            xaxis=viz.axis(theme, "milliseconds", rangemode="tozero"),
            yaxis=viz.axis(theme, "", autorange="reversed", showgrid=False),
        )
    )
    return figure

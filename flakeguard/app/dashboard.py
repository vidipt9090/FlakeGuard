"""
FlakeGuard Dashboard
====================
Offline dashboard reading from results/*.csv files (no live LLM dependency).

Run from the repo root:
    streamlit run flakeguard/app/dashboard.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# ── make sure the repo root is on sys.path when launched directly ──────────
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# These follow the sys.path bootstrap above on purpose, so that running
# `streamlit run flakeguard/app/dashboard.py` from the repo root resolves
# `flakeguard` without an editable install. E402 is suppressed, not fixed.
import pandas as pd  # noqa: E402
import plotly.graph_objects as go  # noqa: E402
import streamlit as st  # noqa: E402

from flakeguard.app import pages_cicd, pages_nav  # noqa: E402

# ── page config (MUST be the very first streamlit call) ───────────────────
st.set_page_config(
    page_title="FlakeGuard — Flake Detector",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── theme selection (persisted in session state) ───────────────────────────
if "theme" not in st.session_state:
    st.session_state["theme"] = "light"

_DARK = st.session_state["theme"] == "dark"

# ── theme-aware colour tokens ──────────────────────────────────────────────
if _DARK:
    # ── existing dark / purple-gold palette ───────────────────────────────
    T = {
        "app_bg":          "radial-gradient(ellipse at 20% 20%, #1a1035 0%, #0d0b1a 40%, #080610 100%)",
        "text":            "#F5EDD6",
        "text_soft":       "#F0E4C8",
        "text_muted":      "#C8B99A",
        "text_faint":      "#A89880",
        "accent":          "#D4A843",
        "accent2":         "#C8922A",
        "accent3":         "#A87030",
        "sidebar_bg":      "linear-gradient(180deg, #0d0b1a 0%, #12102a 100%)",
        "sidebar_border":  "rgba(212,168,67,0.25)",
        "sidebar_text":    "#E8DCC8",
        "card_bg":         "linear-gradient(135deg, rgba(255,255,255,0.06) 0%, rgba(212,168,67,0.04) 100%)",
        "card_border":     "rgba(212,168,67,0.28)",
        "card_border_h":   "rgba(212,168,67,0.6)",
        "card_topline":    "rgba(212,168,67,0.5)",
        "header_bg":       "linear-gradient(120deg, rgba(212,168,67,0.12) 0%, rgba(200,146,42,0.06) 60%, rgba(13,11,26,0) 100%)",
        "header_border":   "rgba(212,168,67,0.4)",
        "header_topline":  "rgba(212,168,67,0.8)",
        "header_h1_grad":  "linear-gradient(90deg, #F5EDD6 30%, #D4A843 100%)",
        "pipeline_bg":     "rgba(212,168,67,0.07)",
        "pipeline_bg_h":   "rgba(212,168,67,0.12)",
        "pipeline_border": "rgba(212,168,67,0.25)",
        "pipeline_text":   "#E8DCC8",
        "evidence_bg":     "rgba(212,168,67,0.06)",
        "evidence_tag_bg": "rgba(212,168,67,0.2)",
        "rq_bg":           "linear-gradient(120deg,rgba(212,168,67,0.1) 0%,rgba(13,11,26,0) 100%)",
        "rq_border":       "rgba(212,168,67,0.35)",
        "input_bg":        "rgba(255,255,255,0.06)",
        "input_border":    "rgba(212,168,67,0.35)",
        "code_bg":         "rgba(0,0,0,0.5)",
        "code_border":     "rgba(212,168,67,0.2)",
        "hr_color":        "rgba(212,168,67,0.2)",
        "verdict_text":    "#F5EDD6",
        "sec_border":      "rgba(212,168,67,0.2)",
        "badge_done_bg":   "rgba(74,222,128,0.12)",
        "badge_done_bd":   "#4ade80",
        "badge_done_tx":   "#bbf7d0",
        "plot_bg":         "rgba(0,0,0,0)",
        "plot_grid":       "rgba(212,168,67,0.12)",
        "plot_text":       "#E8DCC8",
        "plot_axis":       "#C8B99A",
        "plot_legend_bg":  "rgba(13,11,26,0.7)",
        "plot_legend_bd":  "rgba(212,168,67,0.3)",
        "gt_box_bg":       "rgba(212,168,67,0.07)",
        "gt_box_border":   "rgba(212,168,67,0.25)",
    }
else:
    # ── cream / light palette ─────────────────────────────────────────────
    T = {
        "app_bg":          "#ffffff",
        "text":            "#000000",
        "text_soft":       "#1a1a1a",
        "text_muted":      "#4a4a4a",
        "text_faint":      "#6a6a6a",
        "accent":          "#9A6F1A",
        "accent2":         "#7A5514",
        "accent3":         "#5C3D0A",
        "sidebar_bg":      "#ffffff",
        "sidebar_border":  "rgba(154,111,26,0.20)",
        "sidebar_text":    "#000000",
        "card_bg":         "#ffffff",
        "card_border":     "rgba(154,111,26,0.22)",
        "card_border_h":   "rgba(154,111,26,0.55)",
        "card_topline":    "rgba(154,111,26,0.35)",
        "header_bg":       "#ffffff",
        "header_border":   "rgba(154,111,26,0.35)",
        "header_topline":  "rgba(154,111,26,0.55)",
        "header_h1_grad":  "linear-gradient(90deg, #000000 0%, #000000 100%)",
        "pipeline_bg":     "rgba(154,111,26,0.06)",
        "pipeline_bg_h":   "rgba(154,111,26,0.12)",
        "pipeline_border": "rgba(154,111,26,0.20)",
        "pipeline_text":   "#1a1a1a",
        "evidence_bg":     "rgba(154,111,26,0.05)",
        "evidence_tag_bg": "rgba(154,111,26,0.12)",
        "rq_bg":           "rgba(154,111,26,0.04)",
        "rq_border":       "rgba(154,111,26,0.28)",
        "input_bg":        "rgba(255,255,255,0.95)",
        "input_border":    "rgba(154,111,26,0.35)",
        "code_bg":         "rgba(250,250,250,0.90)",
        "code_border":     "rgba(154,111,26,0.18)",
        "hr_color":        "rgba(154,111,26,0.18)",
        "verdict_text":    "#000000",
        "sec_border":      "rgba(154,111,26,0.18)",
        "badge_done_bg":   "rgba(22,163,74,0.09)",
        "badge_done_bd":   "#16a34a",
        "badge_done_tx":   "#14532d",
        "plot_bg":         "rgba(0,0,0,0)",
        "plot_grid":       "rgba(154,111,26,0.12)",
        "plot_text":       "#1a1a1a",
        "plot_axis":       "#4a4a4a",
        "plot_legend_bg":  "rgba(255,255,255,0.92)",
        "plot_legend_bd":  "rgba(154,111,26,0.25)",
        "gt_box_bg":       "rgba(154,111,26,0.06)",
        "gt_box_border":   "rgba(154,111,26,0.20)",
    }

# ── load Yellow Banana font as base64 for CSS embedding ───────────────────
import base64 as _b64  # noqa: E402  (kept beside the font it decodes)

_FONT_PATH = _REPO_ROOT / "static" / "YellowBanana.otf"
_YB_FONT_SRC = ""
if _FONT_PATH.exists():
    _YB_FONT_SRC = _b64.b64encode(_FONT_PATH.read_bytes()).decode()

# ── inject theme CSS ───────────────────────────────────────────────────────
_app_text_color = T["text"]
_app_text_soft  = T["text_soft"]
st.markdown(
    f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

/* ── Yellow Banana local font ── */
@font-face {{
    font-family: 'Yellow Banana';
    src: url('data:font/otf;base64,{_YB_FONT_SRC}') format('opentype');
    font-weight: normal;
    font-style: normal;
}}

/* ── Base — Inter for body, Yellow Banana for display ── */
html, body, [class*="css"] {{
    font-family: 'Inter', sans-serif;
    font-size: 15px;
    color: {T["text"]};
    -webkit-font-smoothing: antialiased;
}}

.stApp {{
    background: {T["app_bg"]};
    color: {T["text"]};
}}

/* ── ALL native streamlit text ── */
.stMarkdown, .stMarkdown p, .stMarkdown li, .stMarkdown span,
[data-testid="stMarkdownContainer"] p,
[data-testid="stMarkdownContainer"] li,
.element-container p, .element-container span,
label, .stRadio label, .stSelectbox label,
.stSlider label, .stTextInput label,
.stMultiSelect label, .stCaption,
.css-1629p8f, .css-10trblm {{
    color: {T["text_soft"]} !important;
    font-size: 14.5px !important;
    font-weight: 500 !important;
}}

/* Streamlit headers */
h1, h2, h3, h4, h5 {{
    font-family: 'Yellow Banana', 'Inter', sans-serif !important;
    color: {T["text"]} !important;
}}

/* Metric values and labels */
[data-testid="stMetricValue"] {{
    font-family: 'Yellow Banana', 'Inter', sans-serif !important;
    color: {T["accent"]} !important;
    font-weight: 700 !important;
    font-size: 2rem !important;
}}
[data-testid="stMetricLabel"] {{
    color: {T["text_muted"]} !important;
    font-size: 13px !important;
    font-weight: 600 !important;
}}
[data-testid="stMetricDelta"] {{ color: {T["accent3"]} !important; font-size: 13px !important; }}

/* ── Sidebar ── */
[data-testid="stSidebar"] {{
    background: {T["sidebar_bg"]};
    border-right: 1px solid {T["sidebar_border"]};
}}
[data-testid="stSidebar"] * {{ color: {T["sidebar_text"]} !important; }}
[data-testid="stSidebar"] .stRadio label {{
    color: {T["sidebar_text"]} !important;
    font-size: 15px !important;
    font-weight: 600 !important;
}}
[data-testid="stSidebar"] [aria-checked="true"] + div {{
    color: {T["accent"]} !important;
    font-weight: 700 !important;
}}

/* ── Tabs ── */
[data-baseweb="tab"] {{
    color: {T["text_muted"]} !important;
    font-size: 14px !important;
    font-weight: 600 !important;
}}
[aria-selected="true"][data-baseweb="tab"] {{
    color: {T["accent"]} !important;
    border-bottom-color: {T["accent"]} !important;
    font-weight: 700 !important;
}}

/* ── Inputs, Selectboxes, Textareas ── */
div[data-baseweb="input"],
div[data-baseweb="base-input"],
.stTextInput > div,
.stTextInput > div > div,
.stSelectbox [data-baseweb="select"] > div,
.stTextArea > div,
.stTextArea > div > div {{
    background-color: {'#18122B' if _DARK else '#ffffff'} !important;
    background: {'#18122B' if _DARK else '#ffffff'} !important;
    border: 1px solid {T["input_border"]} !important;
    border-radius: 8px !important;
    color: {T["text"]} !important;
}}

div[data-baseweb="input"]:focus-within,
div[data-baseweb="base-input"]:focus-within {{
    border-color: {T["accent"]} !important;
    box-shadow: 0 0 0 1px {T["accent"]} !important;
}}

.stTextInput input,
.stTextArea textarea {{
    background-color: transparent !important;
    background: transparent !important;
    color: {T["text"]} !important;
    -webkit-text-fill-color: {T["text"]} !important;
    border: none !important;
    font-size: 14px !important;
}}

.stTextInput input::placeholder,
.stTextArea textarea::placeholder {{
    color: {T["text_muted"]} !important;
    -webkit-text-fill-color: {T["text_muted"]} !important;
    opacity: 0.65 !important;
}}

.stSelectbox [data-baseweb="select"] * {{
    color: {T["text"]} !important;
    -webkit-text-fill-color: {T["text"]} !important;
}}

/* BaseWeb dropdown menu popup */
ul[role="listbox"] {{
    background-color: {'#18122B' if _DARK else '#ffffff'} !important;
}}
ul[role="listbox"] li {{
    color: {T["text"]} !important;
}}

/* ── Buttons ── */
.stButton > button {{
    background: linear-gradient(135deg, {T["accent2"]} 0%, {T["accent"]} 100%) !important;
    color: {'#0d0b1a' if _DARK else '#ffffff'} !important;
    font-family: 'Yellow Banana', 'Inter', sans-serif !important;
    font-size: 15px !important;
    font-weight: 700 !important;
    border: none !important;
    border-radius: 10px !important;
    letter-spacing: 0.04em !important;
    padding: 0.5rem 1.4rem !important;
    box-shadow: 0 4px 20px rgba(79,70,229,0.25) !important;
    transition: all 0.2s ease !important;
}}
.stButton > button:hover {{
    box-shadow: 0 6px 28px rgba(79,70,229,0.42) !important;
    transform: translateY(-1px) !important;
}}

/* ── Code blocks ── */
.stCode, code, pre {{
    background: {T["code_bg"]} !important;
    border: 1px solid {T["code_border"]} !important;
    color: {T["text_soft"]} !important;
    border-radius: 8px !important;
    font-size: 13px !important;
}}

/* ── Dataframe ── */
[data-testid="stDataFrame"] {{
    border: 1px solid {T["card_border"]} !important;
    border-radius: 10px !important;
    box-shadow: 0 2px 12px rgba(79,70,229,0.07) !important;
}}

/* ── Alerts / Info boxes ── */
.stAlert {{ border-radius: 10px !important; font-size: 14px !important; }}
[data-testid="stInfo"]    {{ background: rgba(79,70,229,0.07) !important; border-left-color: {T["accent"]} !important; color: {T["text_soft"]} !important; }}
[data-testid="stSuccess"] {{ background: rgba(22,163,74,0.07) !important; border-left-color: #16a34a !important; color: {T["text_soft"]} !important; }}
[data-testid="stWarning"] {{ background: rgba(202,138,4,0.07) !important; border-left-color: #ca8a04 !important; color: {T["text_soft"]} !important; }}
[data-testid="stError"]   {{ background: rgba(220,38,38,0.07) !important; border-left-color: #dc2626 !important; color: {T["text_soft"]} !important; }}

/* ── Progress bar ── */
[data-testid="stProgress"] > div > div {{ background: linear-gradient(90deg,{T["accent2"]},{T["accent"]}) !important; border-radius: 99px !important; }}

/* ── Divider ── */
hr {{ border-color: {T["hr_color"]} !important; }}

/* ══════════════ CUSTOM COMPONENTS ══════════════ */

.fg-header {{
    background: {T["header_bg"]};
    border: 1.5px solid {T["header_border"]};
    border-radius: 22px;
    padding: 30px 40px;
    margin-bottom: 28px;
    position: relative;
    overflow: hidden;
    box-shadow: 0 4px 28px rgba(79,70,229,0.10);
}}
.fg-header::before {{
    content: '';
    position: absolute;
    top: 0; left: 0; right: 0;
    height: 2px;
    background: linear-gradient(90deg, transparent, {T["header_topline"]}, transparent);
}}
.fg-header h1 {{
    font-family: 'Yellow Banana', 'Inter', sans-serif;
    font-size: 3rem;
    font-weight: 700;
    background: {T["header_h1_grad"]};
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    margin: 0 0 8px 0;
    letter-spacing: 0.01em;
}}
.fg-header p {{
    color: {T["text_muted"]};
    font-size: 1.0rem;
    margin: 0;
    letter-spacing: 0.01em;
    font-weight: 500;
}}

.metric-box {{
    background: {T["card_bg"]};
    border: 1.5px solid {T["card_border"]};
    border-radius: 16px;
    padding: 20px 14px;
    text-align: center;
    height: 106px;
    display: flex;
    flex-direction: column;
    justify-content: center;
    transition: all 0.22s ease;
    position: relative;
    overflow: hidden;
    box-shadow: 0 2px 10px rgba(79,70,229,0.07);
}}
.metric-box::after {{
    content: '';
    position: absolute;
    top: 0; left: 10%; right: 10%;
    height: 2px;
    background: linear-gradient(90deg, transparent, {T["card_topline"]}, transparent);
}}
.metric-box:hover {{
    border-color: {T["card_border_h"]};
    box-shadow: 0 6px 22px rgba(79,70,229,0.15);
    transform: translateY(-2px);
}}
.metric-box .val {{
    font-family: 'Yellow Banana', 'Inter', sans-serif;
    font-size: 2rem;
    font-weight: 700;
    color: {T["accent"]};
}}
.metric-box .lbl {{
    font-size: 0.75rem;
    color: {T["text_faint"]};
    margin-top: 5px;
    white-space: pre-line;
    letter-spacing: 0.05em;
    text-transform: uppercase;
    font-weight: 600;
}}

.pipeline-stage {{
    background: {T["pipeline_bg"]};
    border: 1px solid {T["pipeline_border"]};
    border-radius: 12px;
    padding: 14px 10px;
    text-align: center;
    font-size: 0.82rem;
    color: {T["pipeline_text"]};
    font-weight: 600;
    transition: all 0.2s;
}}
.pipeline-stage:hover {{
    background: {T["pipeline_bg_h"]};
    border-color: {T["card_border_h"]};
    transform: translateY(-2px);
    box-shadow: 0 4px 14px rgba(79,70,229,0.10);
}}
.pipeline-stage b {{
    font-family: 'Yellow Banana', 'Inter', sans-serif;
    color: {T["accent"]};
    font-size: 0.9rem;
}}

.verdict-flaky     {{ background:rgba(124,58,237,0.15); border:2px solid #7c3aed; color:{T["verdict_text"]}; padding:7px 22px; border-radius:26px; font-family:'Yellow Banana','Inter',sans-serif; font-size:1.1rem; display:inline-block; letter-spacing:0.06em; }}
.verdict-real      {{ background:rgba(220,38,38,0.15);  border:2px solid #dc2626; color:{T["verdict_text"]}; padding:7px 22px; border-radius:26px; font-family:'Yellow Banana','Inter',sans-serif; font-size:1.1rem; display:inline-block; letter-spacing:0.06em; }}
.verdict-uncertain {{ background:rgba(79,70,229,0.15);  border:2px solid {T["accent"]}; color:{T["verdict_text"]}; padding:7px 22px; border-radius:26px; font-family:'Yellow Banana','Inter',sans-serif; font-size:1.1rem; display:inline-block; letter-spacing:0.06em; }}

.evidence-block {{
    background: {T["evidence_bg"]};
    border-left: 3px solid {T["accent"]};
    border-radius: 0 10px 10px 0;
    padding: 11px 16px;
    margin-bottom: 10px;
    font-size: 0.88rem;
    color: {T["text_muted"]};
    font-weight: 500;
}}
.evidence-tag {{
    display: inline-block;
    background: {T["evidence_tag_bg"]};
    color: {T["accent"]};
    border: 1px solid {T["card_border"]};
    border-radius: 5px;
    padding: 3px 10px;
    font-size: 0.76rem;
    font-weight: 700;
    margin-bottom: 5px;
    letter-spacing: 0.05em;
}}

.badge-done  {{ background:{T["badge_done_bg"]}; border:1.5px solid {T["badge_done_bd"]}; color:{T["badge_done_tx"]}; padding:4px 13px; border-radius:14px; font-size:0.80rem; font-weight:700; }}
.badge-bonus {{ background:rgba(79,70,229,0.10); border:1.5px solid {T["accent"]}; color:{T["accent"]};  padding:4px 13px; border-radius:14px; font-size:0.80rem; font-weight:700; }}
.badge-stub  {{ background:rgba(148,163,184,0.1); border:1.5px solid #64748b; color:{'#94a3b8' if _DARK else '#475569'};  padding:4px 13px; border-radius:14px; font-size:0.80rem; font-weight:700; }}

/* Section label */
.sec-label {{
    font-family: 'Yellow Banana', 'Inter', sans-serif;
    font-size: 0.80rem;
    font-weight: 700;
    letter-spacing: 0.12em;
    color: {T["accent"]};
    text-transform: uppercase;
    margin-bottom: 12px;
    padding-bottom: 7px;
    border-bottom: 1.5px solid {T["sec_border"]};
}}

#MainMenu, footer {{ visibility: hidden; }}
</style>
""",
    unsafe_allow_html=True,
)

# ═══════════════════════════════════════════════════════════════════════════
# Load data from results/*.csv
# ═══════════════════════════════════════════════════════════════════════════
@st.cache_data(show_spinner=False)
def load_data():
    results_dir = _REPO_ROOT / "results"
    labels_path = _REPO_ROOT / "labels" / "labels.json"

    data = {}

    # Load CSV files
    try:
        data["baseline_metrics"] = pd.read_csv(results_dir / "baseline_metrics.csv")
        data["llm_metrics"] = pd.read_csv(results_dir / "llm_metrics.csv")
        data["failure_log"] = pd.read_csv(results_dir / "failure_log.csv")
        data["runs"] = pd.read_csv(results_dir / "runs.csv")

        # Load labels
        with open(labels_path) as f:
            data["labels"] = {item["id"]: item for item in json.load(f)}

        data["loaded"] = True
    except Exception as exc:
        data["loaded"] = False
        data["error"] = str(exc)

    return data

# Load LLM raw outputs for case explorer
def load_llm_output(version, test_case_num):
    """Load JSON output for a specific version and test case"""
    llm_raw_path = _REPO_ROOT / "results" / "llm_raw" / version / f"test_case_{test_case_num:02d}.json"
    try:
        with open(llm_raw_path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        # A missing or malformed case file is an expected gap, not a crash:
        # the caller renders "no output available" for it. Anything else is a
        # real bug and should surface.
        return None


# ═══════════════════════════════════════════════════════════════════════════
# Sidebar
# ── load Yellow Banana font as base64 for CSS embedding ───────────────────
# ── short aliases so f-strings stay clean (no backslash inside {}) ────────
_accent      = T["accent"]
_accent2     = T["accent2"]
_text        = T["text"]
_text_soft   = T["text_soft"]
_text_muted  = T["text_muted"]
_text_faint  = T["text_faint"]
_sidebar_txt = T["sidebar_text"]

# ═══════════════════════════════════════════════════════════════════════════
with st.sidebar:
    st.markdown(
        f"<h2 style='font-family:Yellow Banana,Inter,sans-serif;color:{_accent};margin:0;font-size:1.6rem;letter-spacing:0.01em'>⚡ FlakeGuard</h2>"
        f"<p style='color:{_text_faint};font-size:0.82rem;margin:4px 0 14px;letter-spacing:0.03em;font-weight:500'>Eval 1 · October 2026</p>",
        unsafe_allow_html=True,
    )
    st.divider()
    page = st.radio(
        "Pages",
        [
            "🏠 Overview",
            "📊 Dataset",
            "🌳 Knowledge Tree",
            "🔬 AST → Jedi Trace",
            "📈 Results",
            "🔍 Case Explorer",
            "❌ Failures",
            "🚀 CI/CD Pipeline",
            "🗺️ Roadmap",
        ],
        label_visibility="collapsed",
    )
    st.divider()

    # ── theme toggle ──────────────────────────────────────────────────────
    st.markdown(
        f"<p style='color:{_accent};font-size:0.72rem;font-weight:700;letter-spacing:0.08em;"
        "text-transform:uppercase;margin-bottom:6px'>Appearance</p>",
        unsafe_allow_html=True,
    )
    _theme_choice = st.radio(
        "theme_radio",
        ["☀️ Light", "🌙 Dark"],
        index=1 if _DARK else 0,
        label_visibility="collapsed",
        horizontal=True,
    )
    if (_theme_choice == "🌙 Dark") != _DARK:
        st.session_state["theme"] = "dark" if _theme_choice == "🌙 Dark" else "light"
        st.rerun()

    st.divider()
    st.markdown(
        f"<p style='color:{_accent};font-size:0.72rem;font-weight:700;letter-spacing:0.08em;text-transform:uppercase;margin-bottom:6px'>Team</p>"
        f"<p style='color:{_sidebar_txt};font-size:0.82rem;line-height:1.8;margin:0'>"
        f"<span style='color:{_accent};font-weight:600'>A</span> — Data &amp; CI<br>"
        f"<span style='color:{_accent};font-weight:600'>B</span> — Navigation &amp; Retrieval<br>"
        f"<span style='color:{_accent};font-weight:600'>C</span> — LLM &amp; Evaluation</p>",
        unsafe_allow_html=True,
    )
    st.divider()
    st.markdown(
        f"<p style='color:{_text_faint};font-size:0.7rem;line-height:1.6'>collect → parse → navigate<br>→ retrieve → LLM → verdict</p>",
        unsafe_allow_html=True,
    )

# ── global header ─────────────────────────────────────────────────────────
st.markdown(
    '<div class="fg-header">'
    "<h1>🛡️ FlakeGuard</h1>"
    "<p>LLM-assisted flaky test detection &nbsp;·&nbsp; AST navigation &nbsp;·&nbsp; Structured evidence &nbsp;·&nbsp; Eval 1 demo</p>"
    "</div>",
    unsafe_allow_html=True,
)


# ═══════════════════════════════════════════════════════════════════════════
# Page 1: OVERVIEW
# ═══════════════════════════════════════════════════════════════════════════
if page == "🏠 Overview":
    st.markdown('<div class="sec-label">🎯 Problem Statement</div>', unsafe_allow_html=True)
    st.markdown(
        f"""
        <div style="background:{T["card_bg"]};border:1px solid {T["card_border"]};border-radius:14px;padding:24px;margin-bottom:20px">
        <p style="color:{T["text_soft"]};font-size:1.0rem;line-height:1.8;margin:0">
        Flaky tests — tests that pass or fail non-deterministically — waste developer time and erode confidence in CI pipelines.
        Root causes include <strong>order dependencies</strong>, <strong>shared state</strong>, <strong>timing races</strong>,
        <strong>unseeded randomness</strong>, and <strong>time/timezone dependencies</strong>.
        <br><br>
        <strong style="color:{T["accent"]}">FlakeGuard</strong> uses LLM-based analysis combined with AST navigation to automatically
        detect flaky tests and identify their root causes from CI run data.
        </p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # Pipeline
    st.markdown('<div class="sec-label">⚙️ Pipeline Architecture</div>', unsafe_allow_html=True)
    stages = [
        ("GitHub\nActions",   "collect.yml\n20 shuffled runs"),
        ("JUnit\nParser",     "Parse XML\nExtract flip-rate"),
        ("AST\nNavigator",    "Walk the test body\nCollect every name"),
        ("jedi\nResolver",    "goto + infer\nHop deeper"),
        ("Knowledge\nTree",   "Root = the test\nNodes by distance"),
        ("Evidence\nBuilder", "Bundle failures\nCode context"),
        ("LLM\nClassifier",   "Prompt v1-v3\nllama3.2:3b"),
        ("Verdict\n& Report", "stable/flaky/real\nRoot cause"),
    ]
    cols = st.columns(len(stages))
    for col, (t, s) in zip(cols, stages):
        with col:
            st.markdown(
                f'<div class="pipeline-stage"><b>{t}</b><br>'
                f'<span style="color:{T["text_faint"]};font-size:0.65rem">{s}</span></div>',
                unsafe_allow_html=True,
            )

    st.markdown(
        f'<p style="color:{T["text_faint"]};font-size:0.8rem;margin:12px 0 0;line-height:1.7">'
        f'The two middle stages are where the code context comes from, and they are '
        f'the ones you can watch run: <b>AST</b> decides <i>what to look for</i> by '
        f'reading the test body as syntax, then <b>jedi</b> works out <i>what each '
        f'name actually is</i> and how deep to follow it. '
        f'See <b>🌳 Knowledge Tree</b> and <b>🔬 AST → Jedi Trace</b>.</p>',
        unsafe_allow_html=True,
    )

    st.markdown("<br>", unsafe_allow_html=True)

    # Where the pipeline stands right now, read from the last gate run.
    _status_path = _REPO_ROOT / "results" / "pipeline_status.json"
    try:
        with open(_status_path, encoding="utf-8") as _f:
            _status = json.load(_f)
    except (OSError, json.JSONDecodeError):
        _status = None

    if _status:
        _promote = _status.get("promote")
        _hue = "#16a34a" if _promote else "#dc2626"
        _counts = _status.get("counts", {})
        st.markdown('<div class="sec-label">🚧 Delivery status</div>', unsafe_allow_html=True)
        st.markdown(
            f"""
            <div style="background:{T["card_bg"]};border:1px solid {T["card_border"]};
            border-left:5px solid {_hue};border-radius:0 12px 12px 0;padding:16px 22px">
              <span style="color:{_hue};font-size:1.2rem;font-weight:800">
              {"PROMOTE" if _promote else "BLOCKED"}</span>
              <span style="color:{T["text_muted"]};font-size:0.88rem">
              &nbsp;— {_counts.get("pass", 0)} checks passed,
              {_counts.get("fail", 0)} failed, {_counts.get("warn", 0)} warned
              at the quality gate</span>
              <div style="color:{T["text_faint"]};font-size:0.78rem;margin-top:4px">
              commit <code>{_status.get("commit", "?")}</code> ·
              {_status.get("generated_at", "?")} ·
              full breakdown on <b>🚀 CI/CD Pipeline</b></div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.markdown("<br>", unsafe_allow_html=True)

    # Research question
    st.markdown('<div class="sec-label">❓ Research Question</div>', unsafe_allow_html=True)
    st.markdown(
        f"""
        <div style="background:{T["rq_bg"]};border:1px solid {T["rq_border"]};border-radius:14px;padding:22px 28px;position:relative">
        <p style="color:{T["text_soft"]};font-size:1.0rem;margin:0;line-height:1.7">
        <strong style="color:{T["accent"]}">Can an LLM, given shuffled-run evidence and retrieved source context, correctly identify the
        root cause of a flaky test at accuracy ≥ 0.70?</strong>
        <br><br>
        We evaluate across three test labels: <code style='background:{T["evidence_tag_bg"]};color:{T["accent"]};padding:2px 8px;border-radius:5px;font-size:0.85rem'>stable</code>,
        <code style='background:{T["evidence_tag_bg"]};color:{T["accent"]};padding:2px 8px;border-radius:5px;font-size:0.85rem'>flaky</code>, and
        <code style='background:{T["evidence_tag_bg"]};color:{T["accent"]};padding:2px 8px;border-radius:5px;font-size:0.85rem'>real</code>
        on synthetic test suites with planted flake types.
        </p>
        </div>
        """,
        unsafe_allow_html=True,
    )


# ═══════════════════════════════════════════════════════════════════════════
# Page 2: DATASET
# ═══════════════════════════════════════════════════════════════════════════
elif page == "📊 Dataset":
    data = load_data()

    if not data["loaded"]:
        st.error(f"❌ Could not load data: {data.get('error')}")
        st.stop()

    st.markdown('<div class="sec-label">📊 Dataset Overview</div>', unsafe_allow_html=True)

    labels = data["labels"]
    runs = data["runs"]

    # Count cases by label and root cause
    label_counts = {}
    root_cause_counts = {}
    for test_id, info in labels.items():
        label = info["label"]
        root_cause = info["root_cause"]
        label_counts[label] = label_counts.get(label, 0) + 1
        root_cause_counts[root_cause] = root_cause_counts.get(root_cause, 0) + 1

    # Metrics
    total_cases = len(labels)
    total_runs = len(runs)
    unique_tests = runs["test_id"].nunique()

    c1, c2, c3, c4 = st.columns(4)
    c1.markdown(f'<div class="metric-box"><div class="val">{total_cases}</div><div class="lbl">Total Test Cases</div></div>', unsafe_allow_html=True)
    c2.markdown(f'<div class="metric-box"><div class="val">{total_runs}</div><div class="lbl">Total Runs</div></div>', unsafe_allow_html=True)
    c3.markdown(f'<div class="metric-box"><div class="val">{label_counts.get("flaky", 0)}</div><div class="lbl">Flaky Tests</div></div>', unsafe_allow_html=True)
    c4.markdown(f'<div class="metric-box"><div class="val">{label_counts.get("stable", 0)}</div><div class="lbl">Stable Tests</div></div>', unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)

    # Root cause distribution
    st.markdown('<div class="sec-label">� Root Cause Distribution</div>', unsafe_allow_html=True)

    root_cause_labels = {
        "order_dep": "⚡ Order Dependency",
        "shared_state": "🗄️ Shared State",
        "timing": "⏰ Timing",
        "randomness": "🎯 Randomness",
        "time_tz": "🌐 Time/TZ",
        "none": "✅ None (stable/real)"
    }

    fig = go.Figure(data=[go.Bar(
        x=[root_cause_labels.get(rc, rc) for rc in root_cause_counts.keys()],
        y=list(root_cause_counts.values()),
        marker_color=T["accent"],
        text=list(root_cause_counts.values()),
        textposition="outside",
        textfont=dict(color=T["plot_text"])
    )])

    fig.update_layout(
        plot_bgcolor=T["plot_bg"],
        paper_bgcolor=T["plot_bg"],
        font=dict(color=T["plot_text"], family="Inter"),
        yaxis=dict(gridcolor=T["plot_grid"], title="Count", color=T["plot_axis"]),
        xaxis=dict(gridcolor=T["plot_grid"], color=T["plot_axis"]),
        height=400,
    )
    st.plotly_chart(fig, use_container_width=True)

    # Flip rate chart
    st.markdown('<div class="sec-label">📈 Flip Rate Analysis</div>', unsafe_allow_html=True)

    # Calculate flip rate per test
    flip_rates = {}
    for test_id in runs["test_id"].unique():
        test_runs = runs[runs["test_id"] == test_id]
        total = len(test_runs)
        passes = (test_runs["outcome"] == "PASS").sum()
        fails = (test_runs["outcome"] == "FAIL").sum()
        flip_rate = min(passes, fails) / total if total > 0 else 0
        flip_rates[test_id] = flip_rate

    # Sort and plot top flaky tests
    sorted_flips = sorted(flip_rates.items(), key=lambda x: x[1], reverse=True)[:15]

    fig = go.Figure(data=[go.Bar(
        y=[t[0].split("::")[-1][:30] for t in sorted_flips],
        x=[t[1] for t in sorted_flips],
        orientation='h',
        marker_color=T["accent2"],
        text=[f"{t[1]:.0%}" for t in sorted_flips],
        textposition="outside",
        textfont=dict(color=T["plot_text"])
    )])

    fig.update_layout(
        plot_bgcolor=T["plot_bg"],
        paper_bgcolor=T["plot_bg"],
        font=dict(color=T["plot_text"], family="Inter"),
        xaxis=dict(gridcolor=T["plot_grid"], title="Flip Rate", color=T["plot_axis"], range=[0, 0.6]),
        yaxis=dict(gridcolor=T["plot_grid"], color=T["plot_axis"]),
        height=500,
        margin=dict(l=200)
    )
    st.plotly_chart(fig, use_container_width=True)


# ═══════════════════════════════════════════════════════════════════════════
# Page 2b: KNOWLEDGE TREE — what the navigator reached, and how far away it is
# ═══════════════════════════════════════════════════════════════════════════
elif page == "🌳 Knowledge Tree":
    pages_nav.render_knowledge_tree(T, _DARK)


# ═══════════════════════════════════════════════════════════════════════════
# Page 2c: AST → JEDI TRACE — the same navigation, replayed step by step
# ═══════════════════════════════════════════════════════════════════════════
elif page == "🔬 AST → Jedi Trace":
    pages_nav.render_trace(T, _DARK)


# ═══════════════════════════════════════════════════════════════════════════
# Page 3: RESULTS
# ═══════════════════════════════════════════════════════════════════════════
elif page == "📈 Results":
    data = load_data()

    if not data["loaded"]:
        st.error(f"❌ Could not load data: {data.get('error')}")
        st.stop()

    baseline_df = data["baseline_metrics"]
    llm_df = data["llm_metrics"]

    st.markdown('<div class="sec-label">📈 Baseline vs LLM Performance</div>', unsafe_allow_html=True)

    # Comparison table
    st.markdown("**Performance Metrics with Bootstrap Confidence Intervals**")

    # Combine baseline and LLM data
    comparison_data = []

    # Baseline (rerun @ N=20)
    baseline_row = baseline_df[baseline_df["N"] == 20].iloc[0] if len(baseline_df[baseline_df["N"] == 20]) > 0 else baseline_df.iloc[-1]
    comparison_data.append({
        "Method": "Baseline (Rerun N=20)",
        "Precision": f"{baseline_row['precision']:.3f}",
        "Precision CI": f"[{baseline_row['precision_ci_lower']:.3f}, {baseline_row['precision_ci_upper']:.3f}]",
        "Recall": f"{baseline_row['recall']:.3f}",
        "Recall CI": f"[{baseline_row['recall_ci_lower']:.3f}, {baseline_row['recall_ci_upper']:.3f}]",
        "F1": f"{baseline_row['f1']:.3f}",
        "F1 CI": f"[{baseline_row['f1_ci_lower']:.3f}, {baseline_row['f1_ci_upper']:.3f}]",
        "Root Cause Acc": f"{baseline_row['root_cause_acc']:.3f}",
        "False Quarantine": f"{baseline_row['false_quarantine_rate']:.3f}"
    })

    # LLM versions
    for _, row in llm_df.iterrows():
        comparison_data.append({
            "Method": f"{row['prompt_version']} ({row['model'].split(':')[0]})",
            "Precision": f"{row['precision']:.3f}",
            "Precision CI": f"[{row['precision_ci_lower']:.3f}, {row['precision_ci_upper']:.3f}]",
            "Recall": f"{row['recall']:.3f}",
            "Recall CI": f"[{row['recall_ci_lower']:.3f}, {row['recall_ci_upper']:.3f}]",
            "F1": f"{row['f1']:.3f}",
            "F1 CI": f"[{row['f1_ci_lower']:.3f}, {row['f1_ci_upper']:.3f}]",
            "Root Cause Acc": f"{row['root_cause_acc']:.3f}",
            "False Quarantine": f"{row['false_quarantine_rate']:.3f}"
        })

    st.dataframe(comparison_data, use_container_width=True, hide_index=True)

    st.markdown("<br>", unsafe_allow_html=True)

    # F1 Score comparison chart
    st.markdown('<div class="sec-label">🎯 F1 Score Comparison</div>', unsafe_allow_html=True)

    methods = ["Baseline"] + [f"{row['prompt_version']}" for _, row in llm_df.iterrows()]
    f1_scores = [baseline_row['f1']] + llm_df['f1'].tolist()
    f1_lower = [baseline_row['f1_ci_lower']] + llm_df['f1_ci_lower'].tolist()
    f1_upper = [baseline_row['f1_ci_upper']] + llm_df['f1_ci_upper'].tolist()

    colors = [T["accent3"]] + [T["accent"], T["accent2"], T["accent"]][:len(llm_df)]

    fig = go.Figure()

    for i, (method, f1, lower, upper, color) in enumerate(zip(methods, f1_scores, f1_lower, f1_upper, colors)):
        fig.add_trace(go.Bar(
            name=method,
            x=[method],
            y=[f1],
            error_y=dict(
                type='data',
                symmetric=False,
                array=[upper - f1],
                arrayminus=[f1 - lower],
                color=T["plot_text"]
            ),
            marker_color=color,
            text=[f"{f1:.3f}"],
            textposition="outside",
            textfont=dict(color=T["plot_text"])
        ))

    fig.add_hline(y=0.70, line_dash="dash", line_color="#16a34a",
                  annotation_text="Target: 0.70", annotation_font_color=T["plot_text"])

    fig.update_layout(
        showlegend=False,
        plot_bgcolor=T["plot_bg"],
        paper_bgcolor=T["plot_bg"],
        font=dict(color=T["plot_text"], family="Inter"),
        yaxis=dict(range=[0, 1.1], gridcolor=T["plot_grid"], title="F1 Score", color=T["plot_axis"]),
        xaxis=dict(gridcolor=T["plot_grid"], color=T["plot_axis"]),
        height=400,
    )
    st.plotly_chart(fig, use_container_width=True)

    # Confusion matrix for best model (v3)
    st.markdown('<div class="sec-label">🎯 Confusion Matrix (v3)</div>', unsafe_allow_html=True)

    v3_row = llm_df[llm_df["prompt_version"] == "v3"].iloc[0]

    col1, col2 = st.columns(2)

    with col1:
        st.markdown("**Key Metrics**")
        c1, c2, c3 = st.columns(3)
        c1.metric("Precision", f"{v3_row['precision']:.3f}")
        c2.metric("Recall", f"{v3_row['recall']:.3f}")
        c3.metric("F1 Score", f"{v3_row['f1']:.3f}")

        st.metric("Root Cause Accuracy", f"{v3_row['root_cause_acc']:.3f}")
        st.metric("False Quarantine Rate", f"{v3_row['false_quarantine_rate']:.3f}")

    with col2:
        st.markdown("**Performance Summary**")
        st.markdown(
            f"""
            <div style="background:{T["card_bg"]};border:1px solid {T["card_border"]};border-radius:10px;padding:18px">
            <p style="color:{T["text_soft"]};font-size:0.9rem;line-height:1.7;margin:0">
            <strong style="color:{T["accent"]}">v3 has the best F1</strong> of the three prompts:
            <br>• Recall {v3_row['recall']:.1%} — it flags every flaky test in the set
            <br>• Precision {v3_row['precision']:.1%}, up from {llm_df.iloc[0]['precision']:.1%} at v1
            <br>• Root-cause accuracy {v3_row['root_cause_acc']:.1%} — it names the
            right family for about {v3_row['root_cause_acc']:.0%} of cases
            <br>• Parse failures: {int(v3_row['parse_failures'])}
            </p>
            </div>
            """,
            unsafe_allow_html=True
        )

    # ── the number the F1 chart hides ────────────────────────────────────
    # Recall 1.0 is not free. The way this prompt reaches it is by calling
    # almost everything flaky, and the benchmark's six real bugs are included
    # in "everything". Reporting F1 without this is reporting half the result.
    _worst_fq = llm_df["false_quarantine_rate"].max()
    if _worst_fq > 0.1:
        _n_real = sum(
            1 for info in data["labels"].values() if info["label"] == "real"
        )
        st.markdown(
            f"""
            <div style="background:rgba(220,38,38,0.07);border:1px solid rgba(220,38,38,0.35);
            border-left:4px solid #dc2626;border-radius:0 12px 12px 0;padding:18px 22px;margin-top:18px">
            <div style="color:#dc2626;font-weight:800;font-size:0.95rem;margin-bottom:8px">
            ⚠️ Read the false-quarantine column before the F1 column
            </div>
            <p style="color:{T["text_soft"]};font-size:0.9rem;line-height:1.75;margin:0">
            Recall of 1.0 is reached by calling almost everything flaky — and the
            benchmark's <strong>{_n_real} real failures</strong> are part of
            "everything". The false-quarantine rate is
            <strong style="color:#dc2626">{_worst_fq:.2f}</strong>, meaning the prompt
            labels <strong>every real bug in the set as flaky</strong>. The rerun
            baseline's rate is <strong>{baseline_row['false_quarantine_rate']:.2f}</strong>.
            <br><br>
            So F1 alone makes the LLM look strictly better than the baseline, and on
            the one error that costs more than a flake does — hiding a real bug behind
            a quarantine — it is <em>worse</em>. This is exactly why the frozen
            decision is that <strong>v1 never quarantines on its own; a person
            approves every quarantine</strong>. The quality gate reports this on every
            pipeline run and blocks delivery on it under <code>--strict</code>.
            </p>
            </div>
            """,
            unsafe_allow_html=True
        )

    # ── navigator contribution ──────────────────────────────────────────
    st.divider()
    st.markdown('<div class="sec-label">🌳 What the navigator contributed</div>', unsafe_allow_html=True)
    _nav_summary_path = _REPO_ROOT / "results" / "nav_trace_summary.json"
    try:
        with open(_nav_summary_path, encoding="utf-8") as _f:
            _nav = json.load(_f)
    except (OSError, json.JSONDecodeError):
        _nav = None

    if _nav is None:
        st.info(
            "No `results/nav_trace_summary.json` yet. Run "
            "`python scripts/export_knowledge_trees.py` to produce it — the "
            "`navigate` stage of the pipeline does this on every push."
        )
    else:
        st.markdown(
            f"""
            <p style="color:{T["text_muted"]};font-size:0.9rem;line-height:1.7;max-width:78ch">
            Every verdict above was made from an evidence bundle, and the bundle's
            code context comes from the navigator. These are the numbers behind
            that step — if the navigator stops resolving test ids, the bundle
            silently empties and the metrics above keep reporting on nothing.
            That is what the gate's navigator checks exist to catch.
            </p>
            """,
            unsafe_allow_html=True,
        )
        _c = st.columns(5)
        for _col, (_val, _lbl) in zip(
            _c,
            [
                (str(_nav.get("cases", 0)), "Cases navigated"),
                (f"{_nav.get('resolution_rate', 0):.0%}", "Resolved"),
                (str(_nav.get("mean_tree_nodes", 0)), "Mean tree nodes"),
                (f"{_nav.get('jedi_hit_rate', 0):.0%}", "jedi hit rate"),
                (f"{_nav.get('median_ms', 0):.0f} ms", "Median latency"),
            ],
        ):
            _col.markdown(
                f'<div class="metric-box"><div class="val">{_val}</div>'
                f'<div class="lbl">{_lbl}</div></div>',
                unsafe_allow_html=True,
            )
        st.caption(
            f"Repo `{_nav.get('repo', '?')}` @ `{_nav.get('sha', '?')}`. "
            f"{_nav.get('trees_with_depth_2plus', 0)} of {_nav.get('cases', 0)} "
            "trees reach a second hop — see **🌳 Knowledge Tree** for the trees "
            "themselves and **🔬 AST → Jedi Trace** for how each was built."
        )


# ═══════════════════════════════════════════════════════════════════════════
# Page 4: CASE EXPLORER
# ═══════════════════════════════════════════════════════════════════════════
elif page == "🔍 Case Explorer":
    data = load_data()

    if not data["loaded"]:
        st.error(f"❌ Could not load data: {data.get('error')}")
        st.stop()

    labels = data["labels"]

    st.markdown('<div class="sec-label">🔍 Explore Individual Test Cases</div>', unsafe_allow_html=True)

    # Case selector
    test_ids = sorted(labels.keys())
    selected_case = st.selectbox(
        "Select a test case",
        test_ids,
        format_func=lambda x: f"{x.split('::')[-1]} ({labels[x]['label']})"
    )

    if selected_case:
        case_info = labels[selected_case]

        # Ground truth
        st.markdown("**Ground Truth**")
        col1, col2, col3 = st.columns(3)
        with col1:
            st.markdown(
                f'<div style="background:{T["gt_box_bg"]};border:1px solid {T["gt_box_border"]};'
                f'border-radius:10px;padding:14px;text-align:center">'
                f'<div style="color:{T["text_muted"]};font-size:0.7rem;font-weight:600;margin-bottom:5px">LABEL</div>'
                f'<div style="color:{T["accent"]};font-size:1.1rem;font-weight:700">{case_info["label"].upper()}</div>'
                f'</div>',
                unsafe_allow_html=True
            )
        with col2:
            st.markdown(
                f'<div style="background:{T["gt_box_bg"]};border:1px solid {T["gt_box_border"]};'
                f'border-radius:10px;padding:14px;text-align:center">'
                f'<div style="color:{T["text_muted"]};font-size:0.7rem;font-weight:600;margin-bottom:5px">ROOT CAUSE</div>'
                f'<div style="color:{T["accent"]};font-size:1.1rem;font-weight:700">{case_info["root_cause"]}</div>'
                f'</div>',
                unsafe_allow_html=True
            )
        with col3:
            st.markdown(
                f'<div style="background:{T["gt_box_bg"]};border:1px solid {T["gt_box_border"]};'
                f'border-radius:10px;padding:14px;text-align:center">'
                f'<div style="color:{T["text_muted"]};font-size:0.7rem;font-weight:600;margin-bottom:5px">FILE</div>'
                f'<div style="color:{T["text_soft"]};font-size:0.75rem;font-weight:600">{case_info["file_path"].split("/")[-1]}</div>'
                f'</div>',
                unsafe_allow_html=True
            )

        st.divider()

        # Extract test case number from ID
        case_num = int(selected_case.split("_")[-1])

        # LLM outputs for v1, v2, v3
        st.markdown("**LLM Analysis (v1, v2, v3)**")

        tabs = st.tabs(["v1", "v2", "v3"])

        for idx, (tab, version) in enumerate(zip(tabs, ["v1", "v2", "v3"])):
            with tab:
                llm_output = load_llm_output(version, case_num)

                if llm_output:
                    parsed = llm_output.get("parsed_output", {})

                    # Verdict and correctness
                    pred_label = parsed.get("label", "unknown")
                    pred_root_cause = parsed.get("root_cause", "unknown")
                    confidence = parsed.get("confidence", 0.0)
                    reasoning = parsed.get("reasoning", "No reasoning provided")

                    # Check if correct
                    label_correct = pred_label == case_info["label"]
                    root_cause_correct = pred_root_cause == case_info["root_cause"]

                    col_a, col_b, col_c = st.columns(3)
                    with col_a:
                        icon = "✅" if label_correct else "❌"
                        st.metric("Predicted Label", f"{icon} {pred_label}")
                    with col_b:
                        icon = "✅" if root_cause_correct else "❌"
                        st.metric("Predicted Root Cause", f"{icon} {pred_root_cause}")
                    with col_c:
                        st.metric("Confidence", f"{confidence:.0%}")

                    st.markdown("**Reasoning:**")
                    st.markdown(
                        f'<div style="background:{T["evidence_bg"]};border-left:3px solid {T["accent"]};'
                        f'border-radius:0 8px 8px 0;padding:12px 16px;font-size:0.88rem;color:{T["text_soft"]};line-height:1.6">'
                        f'{reasoning}</div>',
                        unsafe_allow_html=True
                    )

                    # Self-consistency
                    if "self_consistency_runs" in llm_output:
                        st.markdown("**Self-Consistency Runs:**")
                        sc_runs = llm_output["self_consistency_runs"]
                        st.code(str(sc_runs), language="python")
                else:
                    st.warning(f"No {version} output available for this case")


# ═══════════════════════════════════════════════════════════════════════════
# Page 5: FAILURES
# ═══════════════════════════════════════════════════════════════════════════
elif page == "❌ Failures":
    data = load_data()

    if not data["loaded"]:
        st.error(f"❌ Could not load data: {data.get('error')}")
        st.stop()

    failure_log = data["failure_log"]

    st.markdown('<div class="sec-label">❌ Failure Log & Limitations</div>', unsafe_allow_html=True)

    st.markdown(
        f"""
        <div style="background:{T["card_bg"]};border:1px solid {T["card_border"]};border-radius:10px;padding:18px;margin-bottom:20px">
        <p style="color:{T["text_soft"]};font-size:0.95rem;line-height:1.7;margin:0">
        This page shows cases where the LLM made incorrect predictions.
        Analysis of these failures helps identify limitations and areas for improvement.
        </p>
        </div>
        """,
        unsafe_allow_html=True
    )

    # failure_log is pre-filtered (only contains misclassifications)
    # so all rows are failures — show count vs total predictions (31 cases × 3 versions)
    failures = failure_log
    total_predictions = failure_log["prompt_version"].nunique() * len(failure_log["case_id"].unique())
    # More accurately: count unique (version, case_id) pairs from llm_metrics context
    # Use 31 cases × 3 prompt versions = 93 total predictions
    total_predictions = 31 * failure_log["prompt_version"].nunique()

    st.markdown(f"**Total Failures: {len(failures)} / {total_predictions} predictions**")

    # Group by version
    versions = failure_log["prompt_version"].unique()

    for version in sorted(versions):
        version_failures = failures[failures["prompt_version"] == version]

        with st.expander(f"**{version.upper()} Failures ({len(version_failures)} cases)**", expanded=(version == "v1")):
            if len(version_failures) == 0:
                st.success(f"✅ No failures in {version}!")
            else:
                for _, row in version_failures.iterrows():
                    st.markdown(
                        f"""
                        <div style="background:{T["evidence_bg"]};border-left:3px solid #dc2626;border-radius:0 10px 10px 0;padding:14px;margin-bottom:12px">
                        <div style="color:{T["accent"]};font-weight:700;font-size:0.9rem;margin-bottom:8px">
                        {row['case_id'].split('::')[-1]}
                        </div>
                        <div style="color:{T["text_soft"]};font-size:0.82rem;line-height:1.6">
                        <strong>Actual:</strong> {row['actual_label']} / {row['actual_root_cause']}<br>
                        <strong>Predicted:</strong> {row['pred_label']} / {row['pred_root_cause']}<br>
                        <strong>Reasoning:</strong> {row['reasoning'][:200]}...
                        </div>
                        </div>
                        """,
                        unsafe_allow_html=True
                    )

    st.divider()

    # Limitations section
    st.markdown('<div class="sec-label">🚧 Known Limitations</div>', unsafe_allow_html=True)

    limitations = [
        ("Parse Failures", "Some LLM outputs fail JSON parsing, especially with complex reasoning chains"),
        ("Order Dependency Confusion", "v1/v2 often confuse order_dep with timing issues due to similar failure patterns"),
        ("Stable Misclassification", "Stable tests sometimes flagged as flaky when they have close-to-failure patterns"),
        ("Context Window", "Limited evidence bundle size may miss relevant distant dependencies"),
        ("Model Hallucination", "LLM occasionally invents plausible but incorrect explanations")
    ]

    for title, desc in limitations:
        st.markdown(
            f"""
            <div style="background:{T["card_bg"]};border:1px solid {T["card_border"]};border-left:3px solid {T["accent3"]};
            border-radius:0 10px 10px 0;padding:16px;margin-bottom:12px">
            <div style="color:{T["accent"]};font-weight:700;font-size:0.95rem;margin-bottom:6px">{title}</div>
            <div style="color:{T["text_muted"]};font-size:0.85rem;line-height:1.6">{desc}</div>
            </div>
            """,
            unsafe_allow_html=True
        )


# ═══════════════════════════════════════════════════════════════════════════
# Page 5b: CI/CD PIPELINE — the testing/delivery boundary, and what ran
# ═══════════════════════════════════════════════════════════════════════════
elif page == "🚀 CI/CD Pipeline":
    pages_cicd.render(T, _DARK)


# ═══════════════════════════════════════════════════════════════════════════
# Page 6: ROADMAP
# ═══════════════════════════════════════════════════════════════════════════
elif page == "🗺️ Roadmap":
    st.markdown('<div class="sec-label">🗺️ Roadmap — Planned Features (Not Built)</div>', unsafe_allow_html=True)

    st.markdown(
        f"""
        <div style="background:{T["rq_bg"]};border:1px solid {T["rq_border"]};border-radius:14px;padding:22px;margin-bottom:24px">
        <p style="color:{T["text_soft"]};font-size:0.95rem;line-height:1.8;margin:0">
        These features are planned for future development but <strong style="color:{T["accent"]}">not yet implemented</strong>.
        They represent the next evolution of FlakeGuard's capabilities.
        </p>
        </div>
        """,
        unsafe_allow_html=True
    )

    roadmap_items = [
        {
            "title": "🤖 Agentic Verification",
            "status": "planned",
            "description": "Multi-agent system where one agent proposes fixes and another verifies them by running tests in isolation",
            "impact": "High",
            "effort": "Large",
            "details": [
                "Agent 1: Analyze flake and generate fix proposal",
                "Agent 2: Apply fix in sandbox and run verification tests",
                "Agent 3: Review results and suggest refinements",
                "Iterative loop until fix is validated or max attempts reached"
            ]
        },
        {
            "title": "🔧 MCP (Model Context Protocol) Tools",
            "status": "planned",
            "description": "Standardized tool interfaces for LLM to interact with codebase, git, and CI systems",
            "impact": "High",
            "effort": "Medium",
            "details": [
                "Git tools: checkout, commit, push, branch management",
                "Code tools: read, edit, search, refactor",
                "CI tools: trigger runs, fetch results, analyze logs",
                "Test tools: run specific tests, collect coverage"
            ]
        },
        {
            "title": "🤔 Abstention Mechanism",
            "status": "planned",
            "description": "Allow LLM to abstain from classification when confidence is too low, reducing false positives",
            "impact": "Medium",
            "effort": "Small",
            "details": [
                "Confidence threshold tuning (e.g., abstain if < 0.6)",
                "Separate 'uncertain' category with escalation path",
                "Human-in-the-loop for abstained cases",
                "Metric: precision@coverage curves"
            ]
        },
        {
            "title": "🎓 Knowledge Distillation",
            "status": "planned",
            "description": "Distill large model (GPT-4) into smaller local model (Llama) for faster, cheaper inference",
            "impact": "Medium",
            "effort": "Large",
            "details": [
                "Generate training data using GPT-4 on expanded dataset",
                "Fine-tune Llama 3.2 3B on distilled dataset",
                "Compare performance: distilled vs teacher vs baseline",
                "Target: 90% of teacher performance at 10x speed"
            ]
        },
        {
            "title": "📊 Real-Time Dashboard",
            "status": "planned",
            "description": "Live dashboard showing flake detection results as CI runs complete",
            "impact": "Low",
            "effort": "Medium",
            "details": [
                "WebSocket connection to CI pipeline",
                "Real-time classification as tests complete",
                "Alerts for newly detected flaky tests",
                "Historical trend charts"
            ]
        },
        {
            "title": "🔍 Root Cause Explanation Improvements",
            "status": "planned",
            "description": "Enhanced explanations with code snippets, diffs, and suggested fixes",
            "impact": "Medium",
            "effort": "Medium",
            "details": [
                "Extract relevant code snippets from evidence bundle",
                "Generate diff showing problematic lines",
                "Suggest concrete fix with code example",
                "Link to similar resolved cases"
            ]
        }
    ]

    for item in roadmap_items:
        status_badge = {
            "planned": '<span style="background:rgba(148,163,184,0.15);border:1.5px solid #64748b;color:#64748b;'
                      'padding:4px 12px;border-radius:12px;font-size:0.75rem;font-weight:700">PLANNED</span>',
            "in_progress": f'<span style="background:rgba(79,70,229,0.15);border:1.5px solid {T["accent"]};color:{T["accent"]};'
                          f'padding:4px 12px;border-radius:12px;font-size:0.75rem;font-weight:700">IN PROGRESS</span>',
        }

        impact_color = {"High": "#16a34a", "Medium": "#ca8a04", "Low": "#64748b"}
        effort_color = {"Large": "#dc2626", "Medium": "#d97706", "Small": "#16a34a"}

        st.markdown(
            f"""
            <div style="background:{T["card_bg"]};border:1px solid {T["card_border"]};border-radius:14px;padding:22px;margin-bottom:18px">
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px">
                <div style="font-family:'Yellow Banana','Inter',sans-serif;font-size:1.2rem;color:{T["text"]}">{item['title']}</div>
                {status_badge[item['status']]}
            </div>
            <p style="color:{T["text_soft"]};font-size:0.9rem;line-height:1.7;margin-bottom:14px">{item['description']}</p>
            <div style="display:flex;gap:12px;margin-bottom:12px">
                <span style="background:{T["evidence_tag_bg"]};color:{impact_color[item['impact']]};padding:4px 10px;border-radius:8px;font-size:0.75rem;font-weight:700">
                Impact: {item['impact']}
                </span>
                <span style="background:{T["evidence_tag_bg"]};color:{effort_color[item['effort']]};padding:4px 10px;border-radius:8px;font-size:0.75rem;font-weight:700">
                Effort: {item['effort']}
                </span>
            </div>
            <div style="color:{T["text_muted"]};font-size:0.82rem;line-height:1.7">
            {"<br>".join(["• " + detail for detail in item['details']])}
            </div>
            </div>
            """,
            unsafe_allow_html=True
        )

    st.success("🎉 Roadmap complete — these features represent the next phase of FlakeGuard development!")


# Fallback for old benchmark page
elif page == "📊 Benchmark":
    st.info("This page has been replaced. Please use � Results page.")

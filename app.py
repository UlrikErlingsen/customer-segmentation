from __future__ import annotations

import base64
import hashlib
import inspect
import json
import os
import platform
import sys
import traceback
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.express as px
import sklearn
import streamlit as st

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from segmentsignal import __version__
from segmentsignal.errors import DataProblem, friendly_message
from segmentsignal.features import build_rfm
from segmentsignal.io import LoadedData, load_data, results_to_excel, results_to_json, safe_for_spreadsheet
from segmentsignal.modeling import ALGORITHM_LABELS, SPECTRAL_ROW_LIMIT, compare_solutions, fit_solution
from segmentsignal.preprocessing import PreprocessConfig, infer_feature_types, prepare_features
from segmentsignal.profiling import build_segment_map, profile_segments
from segmentsignal.validation import (
    data_quality_report,
    likely_id_columns,
    likely_pii_columns,
    likely_sensitive_columns,
    suggest_basis_columns,
    usable_basis_columns,
    validate_customer_table,
)


MARK_URI = "data:image/svg+xml;base64," + base64.b64encode(
    (ROOT / "assets" / "segmentsignal-mark.svg").read_bytes()
).decode("ascii")

PAGES = [
    "Welcome",
    "1 · Data & purpose",
    "2 · Compare solutions",
    "3 · Profiles & export",
    "Methods & limits",
]

CAUTION = (
    "**Treat segments as decision support, not discovered truth.** Clusters are patterns in this sample. "
    "They depend on the customers, variables, preparation, and method you choose—and a useful market may "
    "have no reliable cluster structure at all."
)

_USES_STRETCH_WIDTH = "width" in inspect.signature(st.button).parameters


def full_width(widget, *args, **kwargs):
    """Use Streamlit's full-width API across both older and newer releases."""
    if _USES_STRETCH_WIDTH:
        kwargs["width"] = "stretch"
    else:
        kwargs["use_container_width"] = True
    return widget(*args, **kwargs)


st.set_page_config(page_title="SegmentSignal | Open customer segmentation", page_icon="◉", layout="wide")
st.markdown(
    """
    <style>
    :root {
        --ss-ink: #17322e; --ss-deep: #102c2a; --ss-teal: #173c3a;
        --ss-coral: #d95b40; --ss-mint: #83d2b4; --ss-gold: #f2c66d;
        --ss-paper: #f8f5ed; --ss-line: rgba(23, 50, 46, 0.14);
    }
    [data-testid="stAppViewContainer"] {
        background: radial-gradient(circle at 93% 2%, rgba(131,210,180,.20), transparent 27rem),
                    linear-gradient(180deg,#fbf9f3 0%,var(--ss-paper) 100%);
    }
    [data-testid="stHeader"] { background: rgba(248,245,237,.78); }
    [data-testid="stSidebar"] { background: linear-gradient(165deg,#173c3a 0%,#102c2a 65%,#0c2422 100%); }
    [data-testid="stSidebar"] h1,[data-testid="stSidebar"] h2,[data-testid="stSidebar"] h3,
    [data-testid="stSidebar"] p,[data-testid="stSidebar"] label,[data-testid="stSidebar"] span { color:#f8f5ed; }
    [data-testid="stSidebar"] [data-testid="stCaptionContainer"] p { color:#b9cbc5; }
    [data-testid="stSidebar"] [data-testid="stFileUploaderDropzone"] { background:rgba(255,255,255,.06); border-color:rgba(131,210,180,.32); }
    [data-testid="stSidebar"] [data-testid="stFileUploaderDropzone"] small,
    [data-testid="stSidebar"] [data-testid="stFileUploaderDropzone"] small span { color:#b9cbc5 !important; }
    [data-testid="stSidebar"] button { border-color:rgba(255,255,255,.23); }
    [data-testid="stSidebar"] [data-testid="stButton"] button { background:rgba(255,255,255,.08); color:#f8f5ed !important; }
    [data-testid="stSidebar"] [data-testid="stButton"] button:hover { background:rgba(131,210,180,.16); border-color:rgba(131,210,180,.48); }
    [data-testid="stSidebar"] [data-testid="stButton"] button p,
    [data-testid="stSidebar"] [data-testid="stButton"] button span { color:#f8f5ed !important; }
    [data-testid="stSidebar"] [data-testid="stFileUploaderDropzone"] button { background:#f8f5ed; color:#17322e !important; }
    [data-testid="stSidebar"] [data-testid="stFileUploaderDropzone"] button * { color:#17322e !important; }
    .block-container { max-width:1240px; padding-top:4.4rem; padding-bottom:4rem; }
    h1,h2,h3 { color:var(--ss-ink); letter-spacing:-.025em; }
    a { color:#9b3e2b; }
    [data-testid="stMetric"] { background:rgba(255,255,255,.75); border:1px solid var(--ss-line); border-radius:16px; padding:1rem 1.05rem; box-shadow:0 8px 28px rgba(23,50,46,.045); }
    [data-testid="stMetricValue"] { color:var(--ss-ink); }
    .stButton > button[kind="primary"] { background:linear-gradient(135deg,#e26748,#c94c34); color:white; border:0; box-shadow:0 8px 20px rgba(217,91,64,.22); font-weight:750; }
    .stButton > button[kind="primary"]:hover { background:linear-gradient(135deg,#c94c34,#b63f2b); color:white; }
    [data-testid="stExpander"],[data-testid="stAlert"],[data-testid="stVerticalBlockBorderWrapper"] { border-radius:14px; }
    .ss-brand { padding:.25rem 0 1.1rem; }
    .ss-lockup { display:flex; align-items:center; gap:.65rem; }
    .ss-mark { width:38px; height:38px; }
    .ss-name { color:white; font-size:1.28rem; line-height:1; font-weight:850; letter-spacing:-.04em; }
    .ss-name span { color:#f2c66d !important; }
    .ss-tag { margin:.55rem 0 0 !important; color:#b9cbc5 !important; font-size:.77rem; line-height:1.4; }
    .ss-masthead { display:flex; justify-content:space-between; align-items:center; gap:1rem; padding:.72rem 1rem .72rem .78rem; margin-bottom:1.35rem; background:rgba(255,255,255,.65); border:1px solid var(--ss-line); border-radius:18px; box-shadow:0 10px 36px rgba(23,50,46,.05); }
    .ss-masthead .ss-mark { width:48px; height:48px; }
    .ss-wordmark { color:var(--ss-ink); font-weight:850; letter-spacing:-.045em; font-size:1.55rem; line-height:1; }
    .ss-wordmark span { color:var(--ss-coral); }
    .ss-kicker { margin-top:.32rem; color:#59716c; font-size:.67rem; font-weight:800; letter-spacing:.13em; }
    .ss-promise { color:#47645e; font-size:.78rem; font-weight:700; white-space:nowrap; }
    .ss-promise span { color:var(--ss-coral); padding:0 .3rem; }
    .ss-hero { position:relative; overflow:hidden; padding:clamp(1.7rem,4vw,3.4rem); margin-bottom:1.3rem; background:linear-gradient(135deg,#173c3a 0%,#102c2a 75%); border-radius:26px; box-shadow:0 18px 50px rgba(23,50,46,.17); }
    .ss-hero:after { content:""; position:absolute; width:310px; height:310px; right:-100px; top:-135px; border-radius:50%; border:58px solid rgba(131,210,180,.12); }
    .ss-eyebrow { color:#83d2b4; font-size:.72rem; font-weight:850; letter-spacing:.16em; }
    .ss-hero h1 { color:white; font-size:clamp(2.25rem,5vw,4.7rem); line-height:.97; margin:.75rem 0 1rem; max-width:900px; }
    .ss-hero h1 em { color:#f2c66d; font-style:normal; }
    .ss-hero p { color:#d7e3df; font-size:1.06rem; line-height:1.6; max-width:780px; }
    .ss-pills { display:flex; flex-wrap:wrap; gap:.55rem; margin-top:1.15rem; }
    .ss-pill { padding:.4rem .72rem; border:1px solid rgba(255,255,255,.16); border-radius:999px; color:#f8f5ed; font-size:.78rem; font-weight:700; background:rgba(255,255,255,.055); }
    .ss-step { height:100%; padding:1.2rem 1.2rem 1rem; background:rgba(255,255,255,.66); border:1px solid var(--ss-line); border-radius:18px; }
    .ss-step b { color:var(--ss-coral); font-size:.72rem; letter-spacing:.12em; }
    .ss-step h3 { margin:.4rem 0 .5rem; }
    .ss-step p { color:#59716c; font-size:.9rem; line-height:1.55; }
    .ss-footer { margin-top:3.2rem; padding-top:1rem; border-top:1px solid var(--ss-line); color:#617670; font-size:.76rem; text-align:center; }
    .ss-footer span { color:var(--ss-coral); padding:0 .38rem; }
    @media (max-width:760px) { .ss-promise{display:none}.ss-hero{border-radius:20px} }
    </style>
    """,
    unsafe_allow_html=True,
)


def show_error(exc: Exception) -> None:
    st.error(friendly_message(exc))
    if not isinstance(exc, DataProblem) and os.getenv("SEGMENTSIGNAL_DEBUG") == "1":
        with st.expander("Technical details"):
            st.code("".join(traceback.format_exception(exc)))


def set_loaded(loaded: LoadedData, grain: str | None = None) -> None:
    st.session_state["tables"] = loaded.tables
    st.session_state["source_name"] = loaded.source_name
    st.session_state["active_table"] = next(iter(loaded.tables))
    if grain:
        st.session_state["grain_hint"] = grain
    else:
        st.session_state.pop("grain_hint", None)
    for key in (
        "setup", "prepared", "comparison", "solution", "comparison_signature",
        "comparison_settings", "comparison_seed", "chosen_diagnostics",
    ):
        st.session_state.pop(key, None)


def load_demo(filename: str, grain: str) -> None:
    set_loaded(load_data(ROOT / "examples" / filename), grain=grain)


def current_frame() -> pd.DataFrame | None:
    tables = st.session_state.get("tables")
    if not tables:
        return None
    name = st.session_state.get("active_table", next(iter(tables)))
    return tables[name]


def require_data() -> pd.DataFrame | None:
    frame = current_frame()
    if frame is None:
        st.info("Bring a CSV, Excel, or JSON file in the sidebar—or use one of the fictional demo datasets.")
    return frame


def masthead() -> None:
    st.markdown(
        f"""
        <div class="ss-masthead"><div class="ss-lockup"><img class="ss-mark" src="{MARK_URI}"/>
        <div><div class="ss-wordmark">Segment<span>Signal</span></div><div class="ss-kicker">OPEN CUSTOMER SEGMENTATION</div></div></div>
        <div class="ss-promise">Local-first <span>•</span> Explainable <span>•</span> Open source</div></div>
        """,
        unsafe_allow_html=True,
    )


for key, default in (
    ("tables", None), ("source_name", None), ("active_table", None),
    ("upload_epoch", 0), ("_uploader_had_file", False),
    ("nav_target", PAGES[0]), ("nav_epoch", 0),
):
    st.session_state.setdefault(key, default)


def go_to(page_name: str) -> None:
    """Navigate programmatically.

    The sidebar radio is re-created with a fresh key so it adopts ``nav_target``
    even when a rerun interrupted the script before the radio was drawn —
    otherwise Streamlit silently resets the radio to "Welcome" while the
    sidebar still shows the old page as selected.
    """
    st.session_state["nav_target"] = page_name
    st.session_state["nav_epoch"] = int(st.session_state["nav_epoch"]) + 1

with st.sidebar:
    st.markdown(
        f"<div class='ss-brand'><div class='ss-lockup'><img class='ss-mark' src='{MARK_URI}'/><div class='ss-name'>Segment<span>Signal</span></div></div><p class='ss-tag'>Find the groups worth understanding.</p></div>",
        unsafe_allow_html=True,
    )
    st.markdown("### 1. Bring your data")
    uploaded = st.file_uploader(
        "CSV, Excel, or JSON",
        type=["csv", "xlsx", "xls", "xlsm", "json"],
        key=f"customer_upload_{st.session_state['upload_epoch']}",
    )
    if uploaded is not None:
        upload_identity = (
            str(getattr(uploaded, "file_id", "") or f"widget-{st.session_state['upload_epoch']}"),
            uploaded.name,
            int(getattr(uploaded, "size", 0)),
        )
        st.session_state["_uploader_had_file"] = True
        if st.session_state.get("upload_identity") != upload_identity:
            try:
                raw = uploaded.getvalue()
                fingerprint = hashlib.sha256(uploaded.name.encode("utf-8") + b"\0" + raw).hexdigest()
                set_loaded(load_data(raw, name=uploaded.name))
                st.session_state["upload_fingerprint"] = fingerprint
                st.session_state["upload_identity"] = upload_identity
                st.session_state["_uploader_had_file"] = False
                st.session_state["upload_epoch"] = int(st.session_state.get("upload_epoch", 0)) + 1
                go_to("1 · Data & purpose")
                st.rerun()
            except Exception as exc:
                show_error(exc)
    elif st.session_state.get("_uploader_had_file"):
        st.session_state.pop("upload_fingerprint", None)
        st.session_state["_uploader_had_file"] = False
    if full_width(st.button, "Demo · behavior table"):
        load_demo("demo_customers.csv", "customer")
        go_to("1 · Data & purpose")
        st.rerun()
    if full_width(st.button, "Demo · purchase log"):
        load_demo("demo_transactions.csv", "transaction")
        go_to("1 · Data & purpose")
        st.rerun()
    if full_width(st.button, "Demo · needs survey"):
        load_demo("demo_needs_survey.csv", "customer")
        go_to("1 · Data & purpose")
        st.rerun()
    with st.expander("What are the demos?"):
        st.caption(
            "**Behavior table:** one fictional row per customer with ready-made behavioral variables.\n\n"
            "**Purchase log:** repeated fictional orders; SegmentSignal builds optional RFM variables first.\n\n"
            "**Needs survey:** one fictional row per respondent with attitudes, needs, demographics, and no RFM data."
        )
    if st.session_state.get("tables") and full_width(st.button, "Clear session data"):
        for key in (
            "tables", "source_name", "active_table", "upload_fingerprint", "upload_identity", "_uploader_had_file",
            "grain_hint", "setup", "prepared", "comparison", "solution", "comparison_signature",
            "comparison_settings", "comparison_seed", "chosen_diagnostics",
        ):
            st.session_state.pop(key, None)
        st.session_state["upload_epoch"] = int(st.session_state.get("upload_epoch", 0)) + 1
        go_to("Welcome")
        st.rerun()
    if st.session_state.get("tables"):
        table_names = list(st.session_state["tables"])
        selected_table = st.selectbox(
            "Table / sheet",
            table_names,
            index=table_names.index(st.session_state.get("active_table"))
            if st.session_state.get("active_table") in table_names
            else 0,
        )
        if selected_table != st.session_state.get("active_table"):
            st.session_state["active_table"] = selected_table
            for key in ("setup", "prepared", "comparison", "solution"):
                st.session_state.pop(key, None)
        active = st.session_state["tables"][selected_table]
        st.caption(f"{st.session_state.get('source_name')} · {len(active):,} rows × {len(active.columns)} columns")
    st.markdown("### 2. Follow the workflow")
    page = st.radio(
        "Page",
        PAGES,
        index=PAGES.index(st.session_state["nav_target"]),
        key=f"nav_radio_{st.session_state['nav_epoch']}",
        label_visibility="collapsed",
    )
    st.session_state["nav_target"] = page

masthead()


def welcome_page() -> None:
    st.markdown(
        """
        <section class="ss-hero"><div class="ss-eyebrow">B2C SEGMENTATION, WITHOUT THE BLACK BOX</div>
        <h1>From customer data to <em>segments you can question.</em></h1>
        <p>Upload any structured customer table or a transaction log. Compare clustering choices, test whether the groups are stable, understand what formed them, and export a customer-to-segment map.</p>
        <div class="ss-pills"><span class="ss-pill">No account</span><span class="ss-pill">No telemetry</span><span class="ss-pill">Guided preprocessing</span><span class="ss-pill">Honest “no segments” outcome</span></div></section>
        """,
        unsafe_allow_html=True,
    )
    st.markdown(CAUTION)
    st.write("")
    columns = st.columns(3)
    steps = [
        ("STEP 01", "Choose the basis", "Start with the business decision. Separate the variables that form groups from descriptors used to reach them."),
        ("STEP 02", "Compare, don’t guess", "Test K-means, Gaussian mixtures, Ward, and spectral clustering across several segment counts and stability samples."),
        ("STEP 03", "Profile and activate", "Review sizes, uncertainty, profiles, and editable names—then export the customer-to-segment map and audit trail."),
    ]
    for column, (number, title, body) in zip(columns, steps):
        column.markdown(f"<div class='ss-step'><b>{number}</b><h3>{title}</h3><p>{body}</p></div>", unsafe_allow_html=True)
    st.write("")
    metric_columns = st.columns(4)
    metric_columns[0].metric("Input formats", "5", "CSV · Excel · JSON")
    metric_columns[1].metric("Clustering methods", "4", "compared together")
    metric_columns[2].metric("Segment-count control", "2–50", "guided or exact testing")
    metric_columns[3].metric("Data stored", "None", "by the app")
    with st.expander("Where this tool fits"):
        st.write(
            "SegmentSignal focuses on multi-variable B2C customer segmentation. WorthSignal remains the place for "
            "customer value, RFM targeting, retention, and CLV. Regression predicts an outcome; clustering forms groups. "
            "This app does not mix those jobs or claim that a cluster is automatically profitable or reachable."
        )


def data_page() -> None:
    st.title("Set the purpose and the segmentation basis")
    st.write("A useful segmentation begins with a decision—not with every column in the file.")
    frame = require_data()
    if frame is None:
        return

    top = st.columns(4)
    top[0].metric("Rows", f"{len(frame):,}")
    top[1].metric("Columns", len(frame.columns))
    top[2].metric("Missing cells", f"{int(frame.isna().sum().sum()):,}")
    top[3].metric("Duplicate rows", f"{int(frame.duplicated().sum()):,}")
    full_width(st.dataframe, frame.head(12), hide_index=True)

    with st.expander("Data quality and privacy check", expanded=True):
        report = data_quality_report(frame)
        full_width(st.dataframe, report, hide_index=True)
        pii = likely_pii_columns(frame)
        sensitive = likely_sensitive_columns(frame)
        if pii:
            st.warning("Likely direct identifiers are excluded from automatic basis suggestions: " + ", ".join(pii) + ".")
        if sensitive:
            st.warning(
                "Sensitive attributes detected: " + ", ".join(sensitive) + ". Consider fairness, legal, and ethical risks before using them."
            )

    goal = st.selectbox(
        "What decision should these segments support?",
        [
            "Choose different messages or creative",
            "Design products or service levels",
            "Plan channels and customer journeys",
            "Understand needs or usage patterns",
            "Explore the customer base before a later study",
        ],
    )
    grain_options = ["One row per customer", "Transaction log (many rows per customer)"]
    default_grain = 1 if st.session_state.get("grain_hint") == "transaction" else 0
    grain = st.radio("What does one row represent?", grain_options, index=default_grain, horizontal=True)
    columns = [str(column) for column in frame.columns]

    if grain == grain_options[0]:
        st.info(
            "RFM and customer-value fields are optional here. You can segment from needs ratings, survey scores, "
            "demographics, product usage, categories, or other structured variables—provided each row is one customer."
        )
        id_hints = likely_id_columns(frame)
        id_index = columns.index(id_hints[0]) if id_hints and id_hints[0] in columns else 0
        id_column = st.selectbox("Customer ID", columns, index=id_index)
        recipe_labels = {
            "Suggest from my file": "auto",
            "Behavior, needs, or value": "behavior",
            "Demographics or profile fields": "profile",
            "Choose any usable columns myself": "manual",
        }
        recipe_label = st.selectbox(
            "What kind of information should form the groups?",
            list(recipe_labels),
            help="This only changes the starting suggestion. You remain free to add or remove any available field below.",
        )
        recipe = recipe_labels[recipe_label]
        basis_options = usable_basis_columns(frame, id_column)
        familiar_defaults = [
            column
            for column in [
                "recency_days", "purchase_frequency", "annual_spend", "engagement_score",
                "discount_share", "return_rate", "satisfaction_score",
            ]
            if column in basis_options
        ]
        defaults = (
            familiar_defaults
            if recipe == "auto" and len(familiar_defaults) >= 2
            else suggest_basis_columns(frame, id_column, recipe)
        )
        if recipe == "profile":
            st.warning(
                "Profile-based groups can be technically valid, but demographics often describe who customers are—not why "
                "they respond differently. Check fairness, reachability, and business usefulness before activation."
            )
        elif recipe == "manual":
            st.caption("Start empty and choose any numeric, boolean, or low-cardinality categorical fields that fit your decision.")
        elif not defaults:
            st.warning("No obvious fields matched this recipe. Choose suitable variables manually below.")
        basis_columns = st.multiselect(
            "Segmentation bases — needs, benefits, values, or behavior that should form the groups",
            basis_options,
            default=defaults,
            help="These variables determine the clusters. Avoid names, contact details, and variables that do not relate to your decision.",
            key=f"basis_columns_{id_column}_{recipe}",
        )
        descriptor_options = [
            column
            for column in columns
            if column not in set(basis_columns + [id_column, "demo_truth"]) and column not in likely_pii_columns(frame)
        ]
        descriptor_defaults = [
            column
            for column in suggest_basis_columns(frame, id_column, "profile")
            if column in descriptor_options
        ][:8]
        descriptor_columns = st.multiselect(
            "Descriptors — variables used only to explain and reach the groups",
            descriptor_options,
            default=descriptor_defaults,
            help="Descriptors do not form the clusters. They help you understand who is in each segment and how they may be reached.",
        )
        numeric_basis = [column for column in basis_columns if pd.api.types.is_numeric_dtype(frame[column])]
        if len(numeric_basis) >= 2:
            correlations = frame[numeric_basis].corr(numeric_only=True).abs()
            high_pairs = [
                (left, right, float(correlations.loc[left, right]))
                for left_index, left in enumerate(numeric_basis)
                for right in numeric_basis[left_index + 1 :]
                if pd.notna(correlations.loc[left, right]) and correlations.loc[left, right] >= 0.85
            ]
            if high_pairs:
                examples = ", ".join(f"{left} ↔ {right} ({value:.2f})" for left, right, value in high_pairs[:4])
                st.warning(
                    "Some basis variables are strongly correlated and may double-count the same behavior: "
                    + examples
                    + ("…" if len(high_pairs) > 4 else ".")
                )
        advanced = st.expander("Preparation choices")
        with advanced:
            clip_outliers = st.toggle("Limit numeric values at the 1st and 99th percentiles", value=True)
            log_skewed = st.toggle("Log-transform strongly right-skewed, non-negative variables", value=True)
            categorical_weight = st.slider("Categorical basis weight", 0.25, 2.0, 1.0, 0.25)
            st.caption("Numeric missing values use the median. Categorical missing values become “Missing”. All numeric bases are standardized.")
        if st.button("Save this analysis setup", type="primary"):
            try:
                validate_customer_table(frame, id_column, basis_columns)
                numeric, categorical = infer_feature_types(frame, basis_columns)
                config = PreprocessConfig(
                    numeric_columns=tuple(numeric),
                    categorical_columns=tuple(categorical),
                    clip_outliers=clip_outliers,
                    log_skewed=log_skewed,
                    categorical_weight=categorical_weight,
                )
                st.session_state["setup"] = {
                    "frame": frame.copy(), "id_column": id_column, "basis": basis_columns,
                    "descriptors": descriptor_columns, "config": config, "goal": goal, "source": st.session_state.get("source_name"),
                }
                for key in ("prepared", "comparison", "solution"):
                    st.session_state.pop(key, None)
                st.success("Setup saved. Continue to Compare solutions.")
            except Exception as exc:
                show_error(exc)
    else:
        id_hints = likely_id_columns(frame)
        id_index = columns.index(id_hints[0]) if id_hints and id_hints[0] in columns else 0
        customer_column = st.selectbox("Customer ID", columns, index=id_index)
        date_hints = [i for i, column in enumerate(columns) if "date" in column.lower() or "time" in column.lower()]
        date_column = st.selectbox("Purchase date", columns, index=date_hints[0] if date_hints else 0)
        numeric_candidates = [column for column in columns if pd.api.types.is_numeric_dtype(frame[column])]
        amount_options = numeric_candidates or columns
        amount_column = st.selectbox("Purchase amount", amount_options)
        order_options = ["— count rows —"] + columns
        order_default = next((i for i, column in enumerate(order_options) if "order" in column.lower() and "id" in column.lower()), 0)
        order_selected = st.selectbox("Order ID (optional)", order_options, index=order_default)
        parsed_dates = pd.to_datetime(frame[date_column], errors="coerce")
        suggested_reference = (parsed_dates.max() + pd.Timedelta(days=1)).date() if parsed_dates.notna().any() else pd.Timestamp.today().date()
        reference_date = st.date_input("Analysis reference date", value=suggested_reference)
        rfm_feature_options = [
            "recency_days", "frequency", "monetary_value", "average_order_value", "customer_tenure_days"
        ]
        rfm_basis = st.multiselect(
            "Engineered variables to use as segmentation bases",
            rfm_feature_options,
            default=["recency_days", "frequency", "monetary_value"],
            help="Classic RFM is the safest starting point. Add tenure or replace monetary value with average order value when that better fits the decision.",
        )
        if {"frequency", "monetary_value", "average_order_value"} <= set(rfm_basis):
            st.warning(
                "Monetary value equals frequency × average order value. Using all three double-counts purchase behavior; remove one."
            )
        st.caption("We create recency, frequency, monetary value, average order value, and customer tenure. Refunds can remain negative if that matches your data.")
        if st.button("Build RFM features and save setup", type="primary"):
            try:
                rfm = build_rfm(
                    frame, customer_column, date_column, amount_column,
                    None if order_selected == "— count rows —" else order_selected,
                    reference_date,
                )
                basis_columns = rfm_basis
                validate_customer_table(rfm, "customer_id", basis_columns)
                config = PreprocessConfig(numeric_columns=tuple(basis_columns))
                st.session_state["setup"] = {
                    "frame": rfm, "id_column": "customer_id", "basis": basis_columns,
                    "descriptors": [], "config": config, "goal": goal, "source": st.session_state.get("source_name"),
                }
                for key in ("prepared", "comparison", "solution"):
                    st.session_state.pop(key, None)
                st.success(f"Created one customer table with {len(rfm):,} customers. Continue to Compare solutions.")
                full_width(st.dataframe, rfm.head(12), hide_index=True)
            except Exception as exc:
                show_error(exc)
    if st.session_state.get("setup"):
        st.write("")
        if full_width(st.button, "Continue to 2 · Compare solutions →"):
            go_to("2 · Compare solutions")
            st.rerun()


def compare_page() -> None:
    st.title("Compare several plausible solutions")
    st.write("No metric can choose the “true” segments. The recommendation balances separation, resampling stability, segment size, agreement, and simplicity.")
    setup = st.session_state.get("setup")
    if not setup:
        st.info("Save a data setup on page 1 first.")
        return
    frame = setup["frame"]
    context = st.columns(4)
    context[0].metric("Customers", f"{len(frame):,}")
    context[1].metric("Basis variables", len(setup["basis"]))
    context[2].metric("Descriptors", len(setup["descriptors"]))
    purpose_labels = {
        "Choose different messages or creative": "Messages",
        "Design products or service levels": "Products",
        "Plan channels and customer journeys": "Channels",
        "Understand needs or usage patterns": "Needs",
        "Explore the customer base before a later study": "Explore",
    }
    context[3].metric("Purpose", purpose_labels.get(setup["goal"], "Explore"))

    labels_to_keys = {label: key for key, label in ALGORITHM_LABELS.items()}
    binary_numeric = [
        column
        for column in setup["config"].numeric_columns
        if frame[column].dropna().nunique() <= 2
    ]
    if setup["config"].categorical_columns or binary_numeric:
        labels_to_keys.pop("Gaussian mixture", None)
        st.info(
            "Gaussian mixtures are omitted because this setup contains categorical or binary basis variables. "
            "A full-covariance Gaussian likelihood is not appropriate for an exact one-hot or binary block."
        )
    if len(frame) > SPECTRAL_ROW_LIMIT:
        labels_to_keys.pop(ALGORITHM_LABELS["spectral"], None)
        st.caption(
            f"Spectral clustering is hidden above {SPECTRAL_ROW_LIMIT:,} customers because it compares every "
            "customer with its neighbors in one large similarity graph."
        )
    default_methods = ["K-means"] + (
        ["Gaussian mixture"] if "Gaussian mixture" in labels_to_keys else []
    ) + (["Hierarchical (Ward)"] if len(frame) <= 1500 else [])
    chosen_labels = st.multiselect("Methods to compare", list(labels_to_keys), default=default_methods)
    maximum_k = min(50, len(frame) - 1)
    count_mode = st.radio(
        "How do you want to choose the number of segments?",
        ["Compare a guided range", "Test specific numbers"],
        horizontal=True,
    )
    if count_mode == "Compare a guided range":
        guided_maximum = min(12, maximum_k)
        k_range = st.slider("Candidate number of segments", 2, guided_maximum, (3, min(6, guided_maximum)))
        candidate_k_values = list(range(k_range[0], k_range[1] + 1))
    else:
        candidate_k_values = st.multiselect(
            "Exact segment counts to test",
            list(range(2, maximum_k + 1)),
            default=[min(4, maximum_k)],
            help="You can test statistically or managerially unusual counts; the diagnostics will show the consequences.",
        )
    if candidate_k_values and (
        max(candidate_k_values) > 8 or len(frame) / max(candidate_k_values) < 20
    ):
        st.warning(
            "You are free to test this. Expect smaller or less stable groups, and do not treat a fitted solution as useful "
            "unless the size, stability, and business interpretation support it."
        )
    with st.expander("Reproducibility and stability settings"):
        stability_repeats = st.slider("Resampling repeats", 4, 12, 6)
        seed = st.number_input("Random seed", min_value=0, max_value=999999, value=42, step=1)
        st.caption("Each candidate is refitted on repeated 80% subsamples. An adjusted Rand index near 1 means customer memberships are stable.")
    st.caption(
        f"Planned workload: {len(chosen_labels)} method(s) × {len(candidate_k_values)} segment count(s) × "
        f"{stability_repeats} stability refits on {len(frame):,} customers."
    )
    comparison_settings = {
        "algorithms": [labels_to_keys[label] for label in chosen_labels],
        "candidate_k_values": candidate_k_values,
        "stability_repeats": stability_repeats,
        "random_seed": int(seed),
    }
    current_signature = hashlib.sha256(
        json.dumps(comparison_settings, sort_keys=True).encode("utf-8")
    ).hexdigest()

    if st.button("Run the comparison", type="primary"):
        try:
            with st.spinner("Preparing variables and testing candidate solutions…"):
                prepared = prepare_features(frame, setup["config"])
                comparison = compare_solutions(
                    prepared.matrix,
                    algorithms=tuple(labels_to_keys[label] for label in chosen_labels),
                    k_values=tuple(candidate_k_values),
                    stability_repeats=stability_repeats,
                    seed=int(seed),
                )
            st.session_state["prepared"] = prepared
            st.session_state["comparison"] = comparison
            st.session_state["comparison_seed"] = int(seed)
            st.session_state["comparison_settings"] = comparison_settings
            st.session_state["comparison_signature"] = current_signature
            st.session_state.pop("solution", None)
        except Exception as exc:
            show_error(exc)

    prepared = st.session_state.get("prepared")
    comparison = st.session_state.get("comparison")
    if prepared is None or comparison is None:
        return
    if st.session_state.get("comparison_signature") != current_signature:
        st.warning("The comparison controls changed. Run the comparison again before choosing a solution.")
        return
    for warning in prepared.warnings:
        st.warning(warning)
    with st.expander("What preparation changed"):
        st.json(prepared.audit)

    diagnostics = comparison.diagnostics.copy()
    best = diagnostics.iloc[0]
    if (diagnostics["quality"] == "Weak").all():
        st.error(
            "No reliable segmentation was found among these candidates. The top row is shown only as the least-weak option. "
            "Reconsider the business question and basis variables, collect better data, or use transparent rule-based groups."
        )
    elif best["quality"] == "Exploratory":
        st.warning("The leading solution is exploratory. Validate it on new data and with the people who must use it before activation.")
    else:
        st.success(f"The leading candidate is {best['method']} with {int(best['segments'])} segments ({best['quality'].lower()} evidence).")

    display = diagnostics[
        ["recommended", "method", "segments", "quality", "recommendation_score", "silhouette", "stability", "stability_std", "cross_method_agreement", "smallest_segment_customers", "smallest_segment_%", "davies_bouldin"]
    ].rename(
        columns={
            "recommended": "top candidate", "recommendation_score": "balanced score", "stability_std": "stability spread", "cross_method_agreement": "method agreement",
            "smallest_segment_customers": "smallest segment n", "smallest_segment_%": "smallest segment %", "davies_bouldin": "Davies–Bouldin",
        }
    )
    full_width(
        st.dataframe,
        display.style.format({
            "balanced score": "{:.1f}", "silhouette": "{:.3f}", "stability": "{:.3f}",
            "stability spread": "{:.3f}", "method agreement": "{:.3f}", "smallest segment %": "{:.1f}", "Davies–Bouldin": "{:.3f}",
        }),
        hide_index=True,
    )
    with st.expander("All technical diagnostics"):
        technical = diagnostics.copy()
        full_width(st.dataframe, technical, hide_index=True)
        st.download_button(
            "Download candidate diagnostics CSV",
            safe_for_spreadsheet(technical).to_csv(index=False).encode("utf-8"),
            "segmentsignal_candidate_diagnostics.csv",
            "text/csv",
        )
        if not comparison.failures.empty:
            st.warning("Some requested candidates could not be fitted and were excluded from ranking.")
            full_width(st.dataframe, comparison.failures, hide_index=True)
    chart = px.line(
        diagnostics.sort_values("segments"), x="segments", y="recommendation_score", color="method", markers=True,
        labels={"recommendation_score": "Balanced evidence score", "segments": "Number of segments", "method": "Method"},
    )
    chart.update_layout(height=390, legend_title_text="", hovermode="x unified", margin=dict(l=10, r=10, t=20, b=10))
    full_width(st.plotly_chart, chart)

    options = [f"{row.method} · {int(row.segments)} segments" for row in diagnostics.itertuples()]
    chosen = st.selectbox("Candidate to carry forward", options)
    chosen_row = diagnostics.iloc[options.index(chosen)]
    if st.button("Create this segmentation", type="primary"):
        try:
            solution = fit_solution(
                prepared.matrix,
                str(chosen_row["algorithm_key"]),
                int(chosen_row["segments"]),
                seed=st.session_state.get("comparison_seed", 42),
            )
            st.session_state["solution"] = solution
            st.session_state["chosen_diagnostics"] = chosen_row.to_dict()
            go_to("3 · Profiles & export")
            st.rerun()
        except Exception as exc:
            show_error(exc)

    with st.expander("Or fit a custom solution — any method and any segment count"):
        st.caption(
            "This uses the same prepared variables but fits your exact choice directly, even a combination that was "
            "not part of the comparison above. Its stability has not been tested here, so read page 3 with extra care."
        )
        custom_columns = st.columns(2)
        custom_method_label = custom_columns[0].selectbox("Method", list(labels_to_keys), key="custom_method")
        custom_k = custom_columns[1].number_input(
            "Number of segments", min_value=2, max_value=int(maximum_k),
            value=int(min(4, maximum_k)), step=1, key="custom_k",
        )
        if st.button("Create custom segmentation"):
            try:
                solution = fit_solution(
                    prepared.matrix,
                    labels_to_keys[custom_method_label],
                    int(custom_k),
                    seed=st.session_state.get("comparison_seed", 42),
                )
                st.session_state["solution"] = solution
                st.session_state["chosen_diagnostics"] = {
                    "algorithm_key": labels_to_keys[custom_method_label],
                    "method": custom_method_label,
                    "segments": int(custom_k),
                    "note": "Custom fit chosen by the user; this exact combination was not evaluated in the comparison table.",
                }
                go_to("3 · Profiles & export")
                st.rerun()
            except Exception as exc:
                show_error(exc)

    with st.expander("How to read these diagnostics"):
        st.markdown(
            """
            - **Silhouette**: separation and cohesion; higher is better, but context matters.
            - **Stability**: agreement after refitting on repeated subsamples; higher is better.
            - **Method agreement**: whether other algorithms find similar groups at the same segment count.
            - **Smallest segment**: a warning against statistically neat but commercially unusable microsegments.
            - **Davies–Bouldin**: compact, separated clusters score lower.

            The balanced score is a navigation aid, not a statistical test or a guarantee of actionability.
            """
        )


def profiles_page() -> None:
    st.title("Profile, name, and export the chosen segments")
    setup = st.session_state.get("setup")
    solution = st.session_state.get("solution")
    if not setup or solution is None:
        st.info("Run a comparison and create one candidate on page 2 first.")
        return
    chosen_info = st.session_state.get("chosen_diagnostics") or {}
    active_note = " · custom fit outside the comparison table" if chosen_info.get("note") else ""
    st.caption(
        f"Active solution: {ALGORITHM_LABELS.get(solution.algorithm, solution.algorithm)} · "
        f"{solution.k} segments{active_note}. Change it any time on page 2."
    )
    frame = setup["frame"]
    profile = profile_segments(frame, solution.segment_labels, setup["basis"], setup["descriptors"])
    st.markdown(CAUTION)

    cards_for_edit = profile.cards[["segment", "suggested_name"]].rename(columns={"suggested_name": "editable_name"})
    st.subheader("Give the groups names your team can actually use")
    st.caption(
        "Names are generated only from the basis variables you selected; they are not built-in RFM personas. "
        "With survey, demographic, or categorical data, the names and descriptions change accordingly. Edit them freely."
    )
    edited = full_width(
        st.data_editor,
        cards_for_edit,
        hide_index=True,
        disabled=["segment"],
        column_config={"segment": "Model label", "editable_name": st.column_config.TextColumn("Editable segment name", required=True)},
        key=f"segment_names_{solution.algorithm}_{solution.k}",
    )
    names = {
        str(segment): str(name).strip() if pd.notna(name) and str(name).strip() else str(segment)
        for segment, name in zip(edited["segment"], edited["editable_name"])
    }
    summary = profile.summary.copy()
    summary.insert(1, "name", summary["segment"].map(names))
    full_width(st.dataframe, summary, hide_index=True)

    st.subheader("Customer map")
    projection = solution.projection.copy()
    if len(projection) > 5000:
        projection = projection.sample(5000, random_state=st.session_state.get("comparison_seed", 42))
        st.caption("The map is sampled to 5,000 customers for browser performance; the customer-to-segment export still contains every customer.")
    projection["segment_name"] = projection["segment"].map(names)
    scatter = px.scatter(
        projection, x="PC1", y="PC2", color="segment_name", hover_data={"confidence": ":.2f", "segment": True},
        labels={"segment_name": "Segment", "PC1": "Projection axis 1", "PC2": "Projection axis 2"},
        opacity=0.72,
        render_mode="webgl",
    )
    scatter.update_layout(height=500, legend_title_text="", margin=dict(l=10, r=10, t=20, b=10))
    full_width(st.plotly_chart, scatter)
    st.caption(
        f"This scatter plot compresses every basis variable into two artificial axes that preserve "
        f"{solution.explained_variance:.0%} of variation. It is an orientation aid—not proof that clusters exist. "
        "To plot two real variables in their original units, open the Explore two variables tab further down."
    )

    numeric_basis_profile = profile.numeric[profile.numeric["role"] == "basis"] if not profile.numeric.empty else pd.DataFrame()
    if not numeric_basis_profile.empty:
        st.subheader("Snake profile: relative differences")
        snake_data = numeric_basis_profile.copy()
        snake_data["segment_name"] = snake_data["segment"].map(names)
        snake = px.line(
            snake_data, x="feature", y="z_difference", color="segment_name", markers=True,
            labels={"feature": "Segmentation basis", "z_difference": "Difference from overall mean (standard deviations)", "segment_name": "Segment"},
        )
        snake.add_hline(y=0, line_dash="dot", line_color="#73837f")
        snake.update_layout(height=470, legend_title_text="", margin=dict(l=10, r=10, t=20, b=10))
        full_width(st.plotly_chart, snake)
    elif not profile.categorical.empty and (profile.categorical["role"] == "basis").any():
        st.info(
            "The snake chart is only meaningful for numeric bases. Categorical basis differences are shown in the "
            "group cards and Categorical profiles tab below."
        )

    st.subheader("What formed each group")
    st.caption(
        "These differences come from the selected segmentation bases. Descriptor fields may describe or help reach a group, "
        "but they did not create it."
    )
    card_columns = st.columns(min(solution.k, 3))
    for index, row in enumerate(profile.cards.itertuples(index=False)):
        with card_columns[index % len(card_columns)]:
            with st.container(border=True):
                st.markdown(f"**{names[row.segment]}**")
                segment_row = summary[summary["segment"] == row.segment].iloc[0]
                st.caption(f"{int(segment_row['customers']):,} customers · {segment_row['share_%']:.1f}%")
                st.write(row.profile)

    numeric_descriptors = (
        profile.numeric[profile.numeric["role"] == "descriptor"] if not profile.numeric.empty else pd.DataFrame()
    )
    categorical_descriptors = (
        profile.categorical[profile.categorical["role"] == "descriptor"]
        if not profile.categorical.empty
        else pd.DataFrame()
    )
    if not numeric_descriptors.empty or not categorical_descriptors.empty:
        st.subheader("Who is overrepresented — descriptors only")
        st.caption(
            "These fields help describe or reach the groups. They were not used to form the clusters and do not explain why the differences exist."
        )
        descriptor_columns = st.columns(min(solution.k, 3))
        for index, segment in enumerate(summary["segment"]):
            notes: list[str] = []
            if not numeric_descriptors.empty:
                numeric_top = (
                    numeric_descriptors[numeric_descriptors["segment"] == segment]
                    .assign(strength=lambda data: data["z_difference"].abs())
                    .sort_values("strength", ascending=False)
                    .head(1)
                )
                for row in numeric_top.itertuples():
                    if np.isfinite(row.z_difference) and abs(row.z_difference) >= 0.25:
                        notes.append(
                            f"{str(row.feature).replace('_', ' ')} is "
                            f"{'higher' if row.z_difference > 0 else 'lower'} than average ({abs(row.z_difference):.1f} SD)."
                        )
            if not categorical_descriptors.empty:
                categorical_top = (
                    categorical_descriptors[categorical_descriptors["segment"] == segment]
                    .assign(difference=lambda data: data["segment_share_%"] - data["overall_share_%"])
                    .sort_values("difference", ascending=False)
                    .head(1)
                )
                for row in categorical_top.rename(
                    columns={"segment_share_%": "segment_share_", "overall_share_%": "overall_share_"}
                ).itertuples():
                    if np.isfinite(row.difference) and row.difference >= 10:
                        notes.append(
                            f"{str(row.feature).replace('_', ' ')}: {row.level} "
                            f"({row.segment_share_:.0f}% vs {row.overall_share_:.0f}% overall)."
                        )
            if notes:
                with descriptor_columns[index % len(descriptor_columns)]:
                    with st.container(border=True):
                        st.markdown(f"**{names[segment]}**")
                        for note in notes:
                            st.write(note)

    tabs = st.tabs(["Numeric profiles", "Categorical profiles", "Membership uncertainty", "Explore two variables"])
    with tabs[0]:
        if profile.numeric.empty:
            st.info("No numeric basis or descriptor variables were selected.")
        else:
            numeric = profile.numeric.copy()
            numeric.insert(1, "segment_name", numeric["segment"].map(names))
            full_width(st.dataframe, numeric, hide_index=True)
    with tabs[1]:
        if profile.categorical.empty:
            st.info("No categorical basis or descriptor variables were selected.")
        else:
            categorical = profile.categorical.copy()
            categorical.insert(1, "segment_name", categorical["segment"].map(names))
            full_width(st.dataframe, categorical, hide_index=True)
    with tabs[2]:
        confidence = pd.Series(solution.confidence)
        cols = st.columns(3)
        cols[0].metric("Median confidence", f"{confidence.median():.0%}")
        cols[1].metric("Below 60%", f"{(confidence < .60).mean():.1%}")
        cols[2].metric("Below 70%", f"{(confidence < .70).mean():.1%}")
        st.caption("Confidence describes relative model membership, not the probability that a customer is a real-world ‘type’. Borderline customers deserve flexible treatment.")
    with tabs[3]:
        explore_columns = [
            column
            for column in dict.fromkeys(list(setup["basis"]) + list(setup["descriptors"]))
            if column in frame.columns and pd.api.types.is_numeric_dtype(frame[column])
        ]
        if len(explore_columns) < 2:
            st.info("This view needs at least two numeric basis or descriptor variables from page 1.")
        else:
            st.caption(
                "The customer map above uses artificial compressed axes. Here you can plot any two of your real "
                "variables in their original units and see how the segments overlap in everyday terms."
            )
            explore = frame[explore_columns].copy()
            explore["segment_name"] = pd.Series(solution.segment_labels, index=frame.index).map(names)
            if len(explore) > 5000:
                explore = explore.sample(5000, random_state=st.session_state.get("comparison_seed", 42))
                st.caption("Sampled to 5,000 customers for browser performance.")
            axis_columns = st.columns(2)
            x_variable = axis_columns[0].selectbox("Horizontal axis", explore_columns, index=0, key="explore_x")
            y_variable = axis_columns[1].selectbox(
                "Vertical axis", explore_columns, index=min(1, len(explore_columns) - 1), key="explore_y"
            )
            pair = px.scatter(
                explore, x=x_variable, y=y_variable, color="segment_name", opacity=0.7,
                labels={"segment_name": "Segment"}, render_mode="webgl",
            )
            pair.update_layout(height=460, legend_title_text="", margin=dict(l=10, r=10, t=20, b=10))
            full_width(st.plotly_chart, pair)
            distribution_variable = st.selectbox(
                "Distribution check — one variable across all segments", explore_columns, key="explore_box"
            )
            box = px.box(
                explore, x="segment_name", y=distribution_variable, color="segment_name",
                labels={"segment_name": "Segment"},
            )
            box.update_layout(height=430, showlegend=False, margin=dict(l=10, r=10, t=20, b=10))
            full_width(st.plotly_chart, box)
            st.caption(
                "Each box covers the middle half of that segment’s customers, the line inside is the typical (median) "
                "customer, and the dots are unusual values. Overlapping boxes mean the segments are not very different "
                "on that variable."
            )

    st.subheader("Export the evidence and customer-to-segment map")
    st.caption(
        "The map records which segment the chosen model placed each customer in. It is not a list of marketing tasks or actions."
    )
    segment_map = build_segment_map(frame, setup["id_column"], solution.segment_labels, solution.confidence, names)
    numeric_export = profile.numeric.copy()
    categorical_export = profile.categorical.copy()
    diagnostics = pd.DataFrame([st.session_state.get("chosen_diagnostics", {})])
    all_candidates = st.session_state.get("comparison").diagnostics if st.session_state.get("comparison") else diagnostics
    candidate_failures = (
        st.session_state.get("comparison").failures
        if st.session_state.get("comparison") is not None
        else pd.DataFrame(columns=["method", "segments", "reason"])
    )
    fingerprint_columns = list(dict.fromkeys([setup["id_column"]] + setup["basis"]))
    dataset_fingerprint = hashlib.sha256(
        pd.util.hash_pandas_object(frame[fingerprint_columns].astype(str), index=True).values.tobytes()
    ).hexdigest()
    metadata = {
        "product": "SegmentSignal", "version": __version__, "source": setup.get("source"), "purpose": setup["goal"],
        "algorithm": solution.algorithm, "segments": solution.k, "random_seed": st.session_state.get("comparison_seed", 42),
        "basis_variables": setup["basis"], "descriptor_variables": setup["descriptors"],
        "preprocessing": st.session_state.get("prepared").audit if st.session_state.get("prepared") else {},
        "comparison_settings": st.session_state.get("comparison_settings", {}),
        "dataset_fingerprint_sha256": dataset_fingerprint,
        "customer_rows": len(frame),
        "library_versions": {
            "python": platform.python_version(), "numpy": np.__version__, "pandas": pd.__version__,
            "scikit_learn": sklearn.__version__, "streamlit": st.__version__,
        },
        "caution": "Patterns in this sample; not causal findings or objective customer types.",
    }
    manifest = pd.DataFrame(
        {
            "field": list(metadata),
            "value": [json.dumps(value, default=str, sort_keys=True) if isinstance(value, (dict, list)) else str(value) for value in metadata.values()],
        }
    )
    workbook = results_to_excel(
        {
            "Analysis manifest": manifest,
            "Customer segment map": segment_map,
            "Segment summary": summary,
            "Numeric profiles": numeric_export,
            "Category profiles": categorical_export,
            "Chosen diagnostics": diagnostics,
            "All candidates": all_candidates,
            "Candidate failures": candidate_failures,
        }
    )
    downloads = st.columns(3)
    full_width(
        downloads[0].download_button,
        "Download full Excel pack", workbook, "segmentsignal_results.xlsx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    full_width(
        downloads[1].download_button,
        "Download customer segment CSV", safe_for_spreadsheet(segment_map).to_csv(index=False).encode("utf-8"), "customer_segment_map.csv", "text/csv",
    )
    full_width(
        downloads[2].download_button,
        "Download JSON + audit trail",
        results_to_json(
            {
                "customer_segment_map": segment_map,
                "segment_summary": summary,
                "numeric_profiles": numeric_export,
                "categorical_profiles": categorical_export,
                "chosen_diagnostics": diagnostics,
                "all_candidates": all_candidates,
                "candidate_failures": candidate_failures,
            },
            metadata,
        ),
        "segmentsignal_results.json", "application/json",
    )


def methods_page() -> None:
    st.title("Methods, assumptions, and honest limits")
    st.markdown(CAUTION)
    st.subheader("The workflow follows segmentation practice, not just clustering software")
    st.write(
        "First define the decision, then distinguish segmentation bases from descriptors. Bases form groups; descriptors help profile and reach them. "
        "The app standardizes numeric scales, can tame extreme values and strong skew, one-hot encodes categorical bases, compares several methods, and profiles the selected solution in the original units."
    )
    method_cards = [
        ("K-means", "Fast and transparent for compact groups in scaled numeric space. It gives each customer one segment membership and can miss irregular or overlapping structures."),
        ("Gaussian mixture", "For numeric-only bases, allows overlapping elliptical groups and produces membership probabilities. It is omitted for categorical or binary bases and needs ample observations per dimension."),
        ("Ward hierarchy", "Builds a nested grouping by minimizing added within-group variance. It is useful for smaller datasets and cannot directly assign future customers."),
        ("Spectral (flexible shapes)", f"Connects each customer to its nearest neighbors and groups those who stay connected, which can capture stretched or curved patterns the other methods split. It is limited to {SPECTRAL_ROW_LIMIT:,} customers and cannot directly assign future customers."),
    ]
    method_columns = st.columns(2)
    for index, (card_title, card_body) in enumerate(method_cards):
        with method_columns[index % 2]:
            with st.container(border=True):
                st.markdown(f"#### {card_title}")
                st.write(card_body)
    st.subheader("What the app checks")
    st.markdown(
        """
        - **Homogeneity and separation:** silhouette, Calinski–Harabasz, and Davies–Bouldin diagnostics.
        - **Robustness:** refits on repeated 80% subsamples and cross-method adjusted Rand agreement.
        - **Parsimony:** a preference for simpler solutions when evidence is otherwise similar.
        - **Substantiality:** minimum segment share and imbalance warnings.
        - **Identifiability:** basis and descriptor profiles plus customer-level membership confidence.

        Accessibility, profitability, fairness, and operational fit cannot be inferred from cluster geometry. Your team must evaluate those separately.
        """
    )
    st.subheader("Important boundaries")
    st.markdown(
        """
        - A 2-D PCA chart is a projection, not validation.
        - Demographics may describe segments but often make poor substitutes for needs or behavior.
        - Outliers can be errors, isolated customers, or emerging needs. This app clips extremes by default but never silently deletes rows.
        - One-hot encoding makes mixed data usable, but distance in encoded space is still a modeling choice.
        - Segment names are editable descriptions, not facts about people.
        - Regression and classification predict outcomes or future membership; they are not segmentation methods and are outside this first release.
        - Segments can drift. Repeat the analysis on later data before keeping a strategy indefinitely.
        """
    )
    with st.expander("References and implementation notes"):
        st.write("See `docs/methods.md` in the project for formulas, thresholds, citations, and the balanced recommendation score. Every computational module is separate from Streamlit and covered by automated tests.")


if page == "Welcome":
    welcome_page()
elif page == "1 · Data & purpose":
    data_page()
elif page == "2 · Compare solutions":
    compare_page()
elif page == "3 · Profiles & export":
    profiles_page()
else:
    methods_page()

st.markdown(
    f"<div class='ss-footer'>SegmentSignal v{__version__} <span>•</span> Built for transparent B2C segmentation <span>•</span> Your uploaded file is not persisted by the app</div>",
    unsafe_allow_html=True,
)

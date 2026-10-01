"""Segment Signal Streamlit UI.

Everything that draws the app runs inside ``render()`` (or the functions it calls), so it runs on every rerun,
both in the standalone ``app.py`` and inside Signal Hub. Module-level code here only defines constants and
functions. ``render()`` never calls ``st.set_page_config`` or ``st.navigation``.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import os
import platform
import traceback

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import sklearn
import streamlit as st

from segmentsignal import __version__
from segmentsignal.errors import DataProblem, friendly_message
from segmentsignal.examples import demo_csv_bytes
from segmentsignal.features import build_rfm
from segmentsignal.io import LoadedData, load_data, results_to_excel, results_to_json, safe_for_spreadsheet
from segmentsignal.modeling import (
    ALGORITHM_LABELS,
    SPECTRAL_ROW_LIMIT,
    centroid_distances,
    compare_solutions,
    fit_solution,
    hierarchy_views,
)
from segmentsignal.preprocessing import PreprocessConfig, infer_feature_types, prepare_features
from segmentsignal.profiling import anova_table, build_segment_map, profile_segments
from segmentsignal.ui import signal_theme as sig
from segmentsignal.validation import (
    data_quality_report,
    likely_id_columns,
    likely_pii_columns,
    likely_sensitive_columns,
    suggest_basis_columns,
    usable_basis_columns,
    validate_customer_table,
)


NS = "segment"


def k(name: str) -> str:
    """Namespace a session-state or widget key with the app slug, so apps can share one Hub session."""
    return f"{NS}:{name}"


PAGES = [
    "Welcome",
    "1 · Data & purpose",
    "2 · Compare solutions",
    "3 · Profiles & export",
    "Methods & limits",
]

SIDEBAR_TAGLINE = "Find the groups worth understanding."
MASTHEAD_KICKER = "OPEN CUSTOMER SEGMENTATION"
MASTHEAD_PROMISES = ["Local-first", "Explainable", "Open source"]
FOOTER_LINE = "Patterns, not discovered truth"

CAUTION = (
    "**Treat segments as decision support, not discovered truth.** Clusters are patterns in this sample. "
    "They depend on the customers, variables, preparation, and method you choose—and a useful market may "
    "have no reliable cluster structure at all."
)

# Session-state keys that belong to one loaded dataset (cleared when new data arrives or the session is cleared).
ANALYSIS_KEYS = (
    "setup", "prepared", "comparison", "solution", "comparison_signature",
    "comparison_settings", "comparison_seed", "chosen_diagnostics",
    "hierarchy_views", "hierarchy_views_key",
)
DATA_KEYS = ("tables", "source_name", "active_table", "upload_fingerprint", "upload_identity", "_uploader_had_file")

_USES_STRETCH_WIDTH = "width" in inspect.signature(st.button).parameters


def full_width(widget, *args, **kwargs):
    """Use Streamlit's full-width API across both older and newer releases."""
    if _USES_STRETCH_WIDTH:
        kwargs["width"] = "stretch"
    else:
        kwargs["use_container_width"] = True
    return widget(*args, **kwargs)


def _digest(*parts: object) -> str:
    """Short stable fingerprint of a widget's data-dependent options and defaults.

    Keyed widgets keep their value when their options or default change. Folding those inputs into the key lets a
    widget start again from its new default, exactly as the former unkeyed widgets did.
    """
    return hashlib.sha256(json.dumps(parts, default=str, sort_keys=True).encode("utf-8")).hexdigest()[:12]


def show_error(exc: Exception) -> None:
    st.error(friendly_message(exc))
    if not isinstance(exc, DataProblem) and os.getenv("SEGMENTSIGNAL_DEBUG") == "1":
        with st.expander("Technical details"):
            st.code("".join(traceback.format_exception(exc)))


def _ensure_state() -> None:
    for name, default in (
        ("tables", None), ("source_name", None), ("active_table", None),
        ("upload_epoch", 0), ("data_epoch", 0), ("_uploader_had_file", False),
        ("nav_target", PAGES[0]),
    ):
        st.session_state.setdefault(k(name), default)


def _new_data_epoch() -> None:
    """New data or another table: data-dependent widgets start again from their defaults."""
    st.session_state[k("data_epoch")] = int(st.session_state.get(k("data_epoch"), 0)) + 1


def set_loaded(loaded: LoadedData, grain: str | None = None) -> None:
    st.session_state[k("tables")] = loaded.tables
    st.session_state[k("source_name")] = loaded.source_name
    st.session_state[k("active_table")] = next(iter(loaded.tables))
    if grain:
        st.session_state[k("grain_hint")] = grain
    else:
        st.session_state.pop(k("grain_hint"), None)
    for name in ANALYSIS_KEYS:
        st.session_state.pop(k(name), None)
    _new_data_epoch()


def load_demo(filename: str, grain: str) -> None:
    # Generated in code (identical to examples/), so the demos also work from an installed package.
    set_loaded(load_data(demo_csv_bytes(filename), name=filename), grain=grain)


def current_frame() -> pd.DataFrame | None:
    tables = st.session_state.get(k("tables"))
    if not tables:
        return None
    name = st.session_state.get(k("active_table")) or next(iter(tables))
    return tables[name]


def require_data() -> pd.DataFrame | None:
    frame = current_frame()
    if frame is None:
        st.info("Bring a CSV, Excel, or JSON file in the sidebar—or use one of the fictional demo datasets.")
    return frame


def go_to(page_name: str) -> None:
    """Navigate programmatically.

    The page radio cannot be changed once it has been drawn in a run, so the target is stored and applied at the
    start of the next run, before the radio is drawn. Callers follow this with ``st.rerun()``.
    """
    st.session_state[k("nav_target")] = page_name
    st.session_state[k("nav_pending")] = True


def _sidebar() -> str:
    """Draw the sidebar lockup, data controls and page selector; return the selected page."""
    sig.sidebar_brand(NS, SIDEBAR_TAGLINE)
    with st.sidebar:
        st.markdown("### 1. Bring your data")
        uploaded = st.file_uploader(
            "CSV, Excel, or JSON",
            type=["csv", "xlsx", "xls", "xlsm", "json"],
            key=k(f"customer_upload_{st.session_state[k('upload_epoch')]}"),
        )
        if uploaded is not None:
            upload_identity = (
                str(getattr(uploaded, "file_id", "") or f"widget-{st.session_state[k('upload_epoch')]}"),
                uploaded.name,
                int(getattr(uploaded, "size", 0)),
            )
            st.session_state[k("_uploader_had_file")] = True
            if st.session_state.get(k("upload_identity")) != upload_identity:
                try:
                    raw = uploaded.getvalue()
                    fingerprint = hashlib.sha256(uploaded.name.encode("utf-8") + b"\0" + raw).hexdigest()
                    set_loaded(load_data(raw, name=uploaded.name))
                    st.session_state[k("upload_fingerprint")] = fingerprint
                    st.session_state[k("upload_identity")] = upload_identity
                    st.session_state[k("_uploader_had_file")] = False
                    st.session_state[k("upload_epoch")] = int(st.session_state.get(k("upload_epoch"), 0)) + 1
                    go_to("1 · Data & purpose")
                    st.rerun()
                except Exception as exc:
                    show_error(exc)
        elif st.session_state.get(k("_uploader_had_file")):
            st.session_state.pop(k("upload_fingerprint"), None)
            st.session_state[k("_uploader_had_file")] = False
        if full_width(st.button, "Demo · behavior table", key=k("demo_behavior")):
            load_demo("demo_customers.csv", "customer")
            go_to("1 · Data & purpose")
            st.rerun()
        if full_width(st.button, "Demo · purchase log", key=k("demo_purchases")):
            load_demo("demo_transactions.csv", "transaction")
            go_to("1 · Data & purpose")
            st.rerun()
        if full_width(st.button, "Demo · needs survey", key=k("demo_survey")):
            load_demo("demo_needs_survey.csv", "customer")
            go_to("1 · Data & purpose")
            st.rerun()
        with st.expander("What are the demos?"):
            st.caption(
                "**Behavior table:** one fictional row per customer with ready-made behavioral variables.\n\n"
                "**Purchase log:** repeated fictional orders; Segment Signal builds optional RFM variables first.\n\n"
                "**Needs survey:** one fictional row per respondent with attitudes, needs, demographics, and no RFM data."
            )
        if st.session_state.get(k("tables")) and full_width(st.button, "Clear session data", key=k("clear_session")):
            for name in (*DATA_KEYS, "grain_hint", *ANALYSIS_KEYS):
                st.session_state.pop(k(name), None)
            st.session_state[k("upload_epoch")] = int(st.session_state.get(k("upload_epoch"), 0)) + 1
            _new_data_epoch()
            go_to("Welcome")
            st.rerun()
        if st.session_state.get(k("tables")):
            table_names = list(st.session_state[k("tables")])
            active_table = st.session_state.get(k("active_table"))
            selected_table = st.selectbox(
                "Table / sheet",
                table_names,
                index=table_names.index(active_table) if active_table in table_names else 0,
                key=k(f"table_{st.session_state[k('data_epoch')]}"),
            )
            if selected_table != active_table:
                st.session_state[k("active_table")] = selected_table
                for name in ("setup", "prepared", "comparison", "solution"):
                    st.session_state.pop(k(name), None)
                _new_data_epoch()
            active = st.session_state[k("tables")][selected_table]
            st.caption(
                f"{st.session_state.get(k('source_name'))} · {len(active):,} rows × {len(active.columns)} columns"
            )
        st.markdown("### 2. Follow the workflow")
        if st.session_state.pop(k("nav_pending"), False) or st.session_state.get(k("page")) not in PAGES:
            st.session_state[k("page")] = st.session_state[k("nav_target")]
        page = st.radio("Page", PAGES, key=k("page"), label_visibility="collapsed")
        st.session_state[k("nav_target")] = page
    return page


def welcome_page() -> None:
    sig.hero(
        NS,
        eyebrow="B2C SEGMENTATION, WITHOUT THE BLACK BOX",
        title="From customer data to",
        em="segments you can question.",
        body=(
            "Upload any structured customer table or a transaction log. Compare clustering choices, test whether the "
            "groups are stable, understand what formed them, and export a customer-to-segment map."
        ),
        pills=["No account", "No telemetry", "Guided preprocessing", "Honest “no segments” outcome"],
    )
    sig.note("warn", CAUTION)
    sig.cards(
        [
            ("STEP 01", "Choose the basis", "Start with the business decision. Separate the variables that form groups from descriptors used to reach them."),
            ("STEP 02", "Compare, don’t guess", "Test K-means, Gaussian mixtures, Ward, and spectral clustering across several segment counts and stability samples."),
            ("STEP 03", "Profile and activate", "Review sizes, uncertainty, profiles, and editable names—then export the customer-to-segment map and audit trail."),
        ]
    )
    metric_columns = st.columns(4)
    metric_columns[0].metric("Input formats", "5", "CSV · Excel · JSON")
    metric_columns[1].metric("Clustering methods", "4", "compared together")
    metric_columns[2].metric("Segment-count control", "2–50", "guided or exact testing")
    metric_columns[3].metric("Data stored", "None", "by the app")
    with st.expander("Where this tool fits"):
        st.write(
            "Segment Signal focuses on multi-variable B2C customer segmentation. Worth Signal remains the place for "
            "customer value, RFM targeting, retention, and CLV. Regression predicts an outcome; clustering forms groups. "
            "This app does not mix those jobs or claim that a cluster is automatically profitable or reachable."
        )


def data_page() -> None:
    sig.header(
        "Step 1",
        "Set the purpose and the segmentation basis",
        "A useful segmentation begins with a decision—not with every column in the file.",
    )
    frame = require_data()
    if frame is None:
        return
    epoch = st.session_state[k("data_epoch")]

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
        key=k("goal"),
    )
    grain_options = ["One row per customer", "Transaction log (many rows per customer)"]
    default_grain = 1 if st.session_state.get(k("grain_hint")) == "transaction" else 0
    grain = st.radio(
        "What does one row represent?", grain_options, index=default_grain, horizontal=True, key=k(f"grain_{epoch}")
    )
    columns = [str(column) for column in frame.columns]

    if grain == grain_options[0]:
        st.info(
            "RFM and customer-value fields are optional here. You can segment from needs ratings, survey scores, "
            "demographics, product usage, categories, or other structured variables—provided each row is one customer."
        )
        id_hints = likely_id_columns(frame)
        id_index = columns.index(id_hints[0]) if id_hints and id_hints[0] in columns else 0
        id_column = st.selectbox("Customer ID", columns, index=id_index, key=k(f"id_column_{epoch}"))
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
            key=k("recipe"),
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
            key=k(f"basis_columns_{epoch}_{id_column}_{recipe}"),
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
            key=k(f"descriptors_{epoch}_{_digest(descriptor_options, descriptor_defaults)}"),
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
        looks_like_partworths = any(" · " in column for column in columns) and "r_squared" in columns
        if looks_like_partworths:
            st.info(
                "This file looks like a **Choice Signal part-worth export** (one row per respondent, one column per "
                "feature level). Use the part-worth columns as bases, keep `r_squared` as a descriptor, and consider "
                "turning off standardization under Preparation choices — part-worths already share one scale, and "
                "standardizing would erase which attributes matter most."
            )
        advanced = st.expander("Preparation choices")
        with advanced:
            clip_outliers = st.toggle(
                "Limit numeric values at the 1st and 99th percentiles", value=True, key=k("clip_outliers")
            )
            log_skewed = st.toggle(
                "Log-transform strongly right-skewed, non-negative variables", value=True, key=k("log_skewed")
            )
            standardize = st.toggle(
                "Standardize numeric bases (recommended)",
                value=not looks_like_partworths,
                help="Keep this on for ordinary data so no variable dominates just because of its unit. Turn it off "
                "only when all bases already share one meaningful scale, such as conjoint part-worths.",
                key=k(f"standardize_{epoch}"),
            )
            categorical_weight = st.slider(
                "Categorical basis weight", 0.25, 2.0, 1.0, 0.25, key=k("categorical_weight")
            )
            st.caption("Numeric missing values use the median. Categorical missing values become “Missing”.")
        if st.button("Save this analysis setup", type="primary", key=k("save_setup")):
            try:
                validate_customer_table(frame, id_column, basis_columns)
                numeric, categorical = infer_feature_types(frame, basis_columns)
                config = PreprocessConfig(
                    numeric_columns=tuple(numeric),
                    categorical_columns=tuple(categorical),
                    clip_outliers=clip_outliers,
                    log_skewed=log_skewed,
                    standardize=standardize,
                    categorical_weight=categorical_weight,
                )
                st.session_state[k("setup")] = {
                    "frame": frame.copy(), "id_column": id_column, "basis": basis_columns,
                    "descriptors": descriptor_columns, "config": config, "goal": goal,
                    "source": st.session_state.get(k("source_name")),
                }
                for name in ("prepared", "comparison", "solution"):
                    st.session_state.pop(k(name), None)
                st.success("Setup saved. Continue to Compare solutions.")
            except Exception as exc:
                show_error(exc)
    else:
        id_hints = likely_id_columns(frame)
        id_index = columns.index(id_hints[0]) if id_hints and id_hints[0] in columns else 0
        customer_column = st.selectbox("Customer ID", columns, index=id_index, key=k(f"customer_column_{epoch}"))
        date_hints = [i for i, column in enumerate(columns) if "date" in column.lower() or "time" in column.lower()]
        date_column = st.selectbox(
            "Purchase date", columns, index=date_hints[0] if date_hints else 0, key=k(f"date_column_{epoch}")
        )
        numeric_candidates = [column for column in columns if pd.api.types.is_numeric_dtype(frame[column])]
        amount_options = numeric_candidates or columns
        amount_column = st.selectbox("Purchase amount", amount_options, key=k(f"amount_column_{epoch}"))
        order_options = ["— count rows —"] + columns
        order_default = next((i for i, column in enumerate(order_options) if "order" in column.lower() and "id" in column.lower()), 0)
        order_selected = st.selectbox(
            "Order ID (optional)", order_options, index=order_default, key=k(f"order_column_{epoch}")
        )
        parsed_dates = pd.to_datetime(frame[date_column], errors="coerce")
        suggested_reference = (
            (pd.Timestamp(parsed_dates.max()) + pd.Timedelta(1, unit="D")).date()
            if parsed_dates.notna().any()
            else pd.Timestamp.today().date()
        )
        reference_date = st.date_input(
            "Analysis reference date",
            value=suggested_reference,
            key=k(f"reference_date_{epoch}_{_digest(date_column, suggested_reference)}"),
        )
        rfm_feature_options = [
            "recency_days", "frequency", "monetary_value", "average_order_value", "customer_tenure_days"
        ]
        rfm_basis = st.multiselect(
            "Engineered variables to use as segmentation bases",
            rfm_feature_options,
            default=["recency_days", "frequency", "monetary_value"],
            help="Classic RFM is the safest starting point. Add tenure or replace monetary value with average order value when that better fits the decision.",
            key=k("rfm_basis"),
        )
        if {"frequency", "monetary_value", "average_order_value"} <= set(rfm_basis):
            st.warning(
                "Monetary value equals frequency × average order value. Using all three double-counts purchase behavior; remove one."
            )
        st.caption("We create recency, frequency, monetary value, average order value, and customer tenure. Refunds can remain negative if that matches your data.")
        if st.button("Build RFM features and save setup", type="primary", key=k("build_rfm")):
            try:
                rfm = build_rfm(
                    frame, customer_column, date_column, amount_column,
                    None if order_selected == "— count rows —" else order_selected,
                    reference_date,
                )
                basis_columns = rfm_basis
                validate_customer_table(rfm, "customer_id", basis_columns)
                config = PreprocessConfig(numeric_columns=tuple(basis_columns))
                st.session_state[k("setup")] = {
                    "frame": rfm, "id_column": "customer_id", "basis": basis_columns,
                    "descriptors": [], "config": config, "goal": goal,
                    "source": st.session_state.get(k("source_name")),
                }
                for name in ("prepared", "comparison", "solution"):
                    st.session_state.pop(k(name), None)
                st.success(f"Created one customer table with {len(rfm):,} customers. Continue to Compare solutions.")
                full_width(st.dataframe, rfm.head(12), hide_index=True)
            except Exception as exc:
                show_error(exc)
    if st.session_state.get(k("setup")):
        st.write("")
        if full_width(st.button, "Continue to 2 · Compare solutions →", key=k("continue_compare")):
            go_to("2 · Compare solutions")
            st.rerun()


def compare_page() -> None:
    sig.header(
        "Step 2",
        "Compare several plausible solutions",
        "No metric can choose the “true” segments. The recommendation balances separation, resampling stability, "
        "segment size, agreement, and simplicity.",
    )
    setup = st.session_state.get(k("setup"))
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
    chosen_labels = st.multiselect(
        "Methods to compare",
        list(labels_to_keys),
        default=default_methods,
        key=k(f"methods_{_digest(list(labels_to_keys), default_methods)}"),
    )
    maximum_k = min(50, len(frame) - 1)
    count_mode = st.radio(
        "How do you want to choose the number of segments?",
        ["Compare a guided range", "Test specific numbers"],
        horizontal=True,
        key=k("count_mode"),
    )
    if count_mode == "Compare a guided range":
        guided_maximum = min(12, maximum_k)
        k_range = st.slider(
            "Candidate number of segments", 2, guided_maximum, (3, min(6, guided_maximum)), key=k("k_range")
        )
        candidate_k_values = list(range(k_range[0], k_range[1] + 1))
    else:
        candidate_k_values = st.multiselect(
            "Exact segment counts to test",
            list(range(2, maximum_k + 1)),
            default=[min(4, maximum_k)],
            help="You can test statistically or managerially unusual counts; the diagnostics will show the consequences.",
            key=k(f"exact_counts_{maximum_k}"),
        )
    if candidate_k_values and (
        max(candidate_k_values) > 8 or len(frame) / max(candidate_k_values) < 20
    ):
        st.warning(
            "You are free to test this. Expect smaller or less stable groups, and do not treat a fitted solution as useful "
            "unless the size, stability, and business interpretation support it."
        )
    with st.expander("Reproducibility and stability settings"):
        stability_repeats = st.slider("Resampling repeats", 4, 12, 6, key=k("stability_repeats"))
        seed = st.number_input("Random seed", min_value=0, max_value=999999, value=42, step=1, key=k("seed"))
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

    if st.button("Run the comparison", type="primary", key=k("run_comparison")):
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
            st.session_state[k("prepared")] = prepared
            st.session_state[k("comparison")] = comparison
            st.session_state[k("comparison_seed")] = int(seed)
            st.session_state[k("comparison_settings")] = comparison_settings
            st.session_state[k("comparison_signature")] = current_signature
            st.session_state.pop(k("solution"), None)
        except Exception as exc:
            show_error(exc)

    prepared = st.session_state.get(k("prepared"))
    comparison = st.session_state.get(k("comparison"))
    if prepared is None or comparison is None:
        return
    if st.session_state.get(k("comparison_signature")) != current_signature:
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
            key=k("download_diagnostics"),
        )
        if not comparison.failures.empty:
            st.warning("Some requested candidates could not be fitted and were excluded from ranking.")
            full_width(st.dataframe, comparison.failures, hide_index=True)
    chart = px.line(
        diagnostics.sort_values("segments"), x="segments", y="recommendation_score", color="method", markers=True,
        labels={"recommendation_score": "Balanced evidence score", "segments": "Number of segments", "method": "Method"},
        template=sig.template(NS),
    )
    chart.update_layout(height=390, legend_title_text="", hovermode="x unified", margin=dict(l=10, r=10, t=20, b=10))
    sig.chart(NS, chart, key=k("score_chart"))

    if len(frame) <= 5000:
        with st.expander("How the customer base splits — hierarchy views"):
            st.caption(
                "These views use Ward hierarchical clustering on the same prepared variables. "
                "They help you sense-check a segment count; they do not prove one is correct."
            )
            views_key = st.session_state.get(k("comparison_signature"))
            if st.session_state.get(k("hierarchy_views_key")) != views_key:
                try:
                    with st.spinner("Building the customer hierarchy…"):
                        st.session_state[k("hierarchy_views")] = hierarchy_views(prepared.matrix, max_segments=8)
                    st.session_state[k("hierarchy_views_key")] = views_key
                except Exception as exc:
                    show_error(exc)
            views = st.session_state.get(k("hierarchy_views"))
            if views is not None and st.session_state.get(k("hierarchy_views_key")) == views_key:
                st.markdown("**Split boxes (icicle):** the top box is every customer; each level shows one group dividing in two.")
                icicle_chart = go.Figure(
                    go.Icicle(
                        ids=views.icicle["id"],
                        labels=views.icicle["label"],
                        parents=views.icicle["parent"],
                        values=views.icicle["customers"],
                        branchvalues="total",
                        tiling=dict(orientation="v"),
                        hovertemplate="%{label}<br>%{percentRoot:.0%} of all customers<extra></extra>",
                    )
                )
                icicle_chart.update_layout(template=sig.template(NS), height=420, margin=dict(l=10, r=10, t=10, b=10))
                sig.chart(NS, icicle_chart, key=k("icicle_chart"))
                st.caption(
                    "Deep splits that produce tiny boxes are a warning sign: statistically neat microsegments "
                    "are rarely usable in a campaign."
                )
                st.markdown("**Merge tree (dendrogram):** groups joined by a low bridge are similar; a tall gap before two groups join suggests genuinely distinct segments.")
                tree = go.Figure()
                for xs, ys in zip(views.dendrogram["icoord"], views.dendrogram["dcoord"]):
                    tree.add_trace(
                        go.Scatter(
                            x=xs, y=ys, mode="lines", line=dict(color=sig.CORE["text"], width=1.4),
                            hoverinfo="skip", showlegend=False,
                        )
                    )
                leaf_positions = [5 + 10 * index for index in range(len(views.dendrogram["leaf_labels"]))]
                tree.update_layout(
                    template=sig.template(NS),
                    height=420,
                    margin=dict(l=10, r=10, t=10, b=10),
                    xaxis=dict(tickvals=leaf_positions, ticktext=views.dendrogram["leaf_labels"], title="Customer groups — (n) = collapsed customers"),
                    yaxis=dict(title="Merge distance (Ward)"),
                )
                sig.chart(NS, tree, key=k("dendrogram_chart"))
    else:
        st.caption("Hierarchy views (split boxes and dendrogram) are available for files up to 5,000 customers.")

    options = [f"{row.method} · {int(row.segments)} segments" for row in diagnostics.itertuples()]
    chosen = st.selectbox("Candidate to carry forward", options, key=k(f"candidate_{_digest(options)}"))
    chosen_row = diagnostics.iloc[options.index(chosen)]
    if st.button("Create this segmentation", type="primary", key=k("create_segmentation")):
        try:
            solution = fit_solution(
                prepared.matrix,
                str(chosen_row["algorithm_key"]),
                int(chosen_row["segments"]),
                seed=st.session_state.get(k("comparison_seed"), 42),
            )
            st.session_state[k("solution")] = solution
            st.session_state[k("chosen_diagnostics")] = chosen_row.to_dict()
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
        custom_method_label = custom_columns[0].selectbox("Method", list(labels_to_keys), key=k("custom_method"))
        custom_k = custom_columns[1].number_input(
            "Number of segments", min_value=2, max_value=int(maximum_k),
            value=int(min(4, maximum_k)), step=1, key=k("custom_k"),
        )
        if st.button("Create custom segmentation", key=k("create_custom")):
            try:
                solution = fit_solution(
                    prepared.matrix,
                    labels_to_keys[custom_method_label],
                    int(custom_k),
                    seed=st.session_state.get(k("comparison_seed"), 42),
                )
                st.session_state[k("solution")] = solution
                st.session_state[k("chosen_diagnostics")] = {
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
    sig.header("Step 3", "Profile, name, and export the chosen segments")
    setup = st.session_state.get(k("setup"))
    solution = st.session_state.get(k("solution"))
    if not setup or solution is None:
        st.info("Run a comparison and create one candidate on page 2 first.")
        return
    seed = st.session_state.get(k("comparison_seed"), 42)
    chosen_info = st.session_state.get(k("chosen_diagnostics")) or {}
    active_note = " · custom fit outside the comparison table" if chosen_info.get("note") else ""
    st.caption(
        f"Active solution: {ALGORITHM_LABELS.get(solution.algorithm, solution.algorithm)} · "
        f"{solution.k} segments{active_note}. Change it any time on page 2."
    )
    frame = setup["frame"]
    profile = profile_segments(frame, solution.segment_labels, setup["basis"], setup["descriptors"])
    sig.note("warn", CAUTION)

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
        key=k(f"segment_names_{solution.algorithm}_{solution.k}"),
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
        projection = projection.sample(5000, random_state=seed)
        st.caption("The map is sampled to 5,000 customers for browser performance; the customer-to-segment export still contains every customer.")
    projection["segment_name"] = projection["segment"].map(names)
    scatter = px.scatter(
        projection, x="PC1", y="PC2", color="segment_name", hover_data={"confidence": ":.2f", "segment": True},
        labels={"segment_name": "Segment", "PC1": "Projection axis 1", "PC2": "Projection axis 2"},
        opacity=0.72,
        render_mode="webgl",
        template=sig.template(NS),
    )
    scatter.update_layout(height=500, legend_title_text="", margin=dict(l=10, r=10, t=20, b=10))
    sig.chart(NS, scatter, key=k("customer_map"))
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
            template=sig.template(NS),
        )
        snake.add_hline(y=0, line_dash="dot", line_color=sig.roles(NS)["zero"])
        snake.update_layout(height=470, legend_title_text="", margin=dict(l=10, r=10, t=20, b=10))
        sig.chart(NS, snake, key=k("snake_chart"))
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

    tabs = st.tabs(["Numeric profiles", "Categorical profiles", "Membership uncertainty", "Explore two variables", "Expert statistics"])
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
                explore = explore.sample(5000, random_state=seed)
                st.caption("Sampled to 5,000 customers for browser performance.")
            axis_columns = st.columns(2)
            x_variable = axis_columns[0].selectbox("Horizontal axis", explore_columns, index=0, key=k("explore_x"))
            y_variable = axis_columns[1].selectbox(
                "Vertical axis", explore_columns, index=min(1, len(explore_columns) - 1), key=k("explore_y")
            )
            pair = px.scatter(
                explore, x=x_variable, y=y_variable, color="segment_name", opacity=0.7,
                labels={"segment_name": "Segment"}, render_mode="webgl", template=sig.template(NS),
            )
            pair.update_layout(height=460, legend_title_text="", margin=dict(l=10, r=10, t=20, b=10))
            sig.chart(NS, pair, key=k("pair_chart"))
            distribution_variable = st.selectbox(
                "Distribution check — one variable across all segments", explore_columns, key=k("explore_box")
            )
            box = px.box(
                explore, x="segment_name", y=distribution_variable, color="segment_name",
                labels={"segment_name": "Segment"}, template=sig.template(NS),
            )
            box.update_layout(height=430, showlegend=False, margin=dict(l=10, r=10, t=20, b=10))
            sig.chart(NS, box, key=k("box_chart"))
            st.caption(
                "Each box covers the middle half of that segment’s customers, the line inside is the typical (median) "
                "customer, and the dots are unusual values. Overlapping boxes mean the segments are not very different "
                "on that variable."
            )
    with tabs[4]:
        st.caption(
            "Statistics in the style of classic SPSS cluster output, for readers who want the numbers behind the profiles."
        )
        numeric_basis_columns = [
            column for column in setup["basis"]
            if column in frame.columns and pd.api.types.is_numeric_dtype(frame[column])
        ]
        if numeric_basis_columns:
            st.markdown("**Variable differences across segments — one-way ANOVA**")
            anova = anova_table(frame, solution.segment_labels, numeric_basis_columns)
            if anova.empty:
                st.info("The ANOVA table could not be computed for these variables.")
            else:
                full_width(
                    st.dataframe,
                    anova.style.format({"F": "{:.1f}", "p_value": "{:.4f}", "eta_squared": "{:.3f}"}),
                    hide_index=True,
                )
                st.caption(
                    "**Read with care:** the segments were constructed to maximize exactly these differences, so the "
                    "F tests and p-values are descriptive, not hypothesis tests (SPSS prints the same warning). "
                    "Eta squared (0–1) shows how much of a variable’s variation the segmentation explains — use it to "
                    "rank which variables separate the groups most."
                )
        else:
            st.info("ANOVA needs at least one numeric basis variable.")
        prepared_state = st.session_state.get(k("prepared"))
        if prepared_state is not None:
            st.markdown("**Distances between final segment centers**")
            distances = centroid_distances(prepared_state.matrix, solution.segment_labels)
            distances = distances.rename(index=names, columns=names)
            full_width(st.dataframe, distances)
            st.caption(
                "Euclidean distances in the standardized model space. Larger numbers mean more different segment "
                "centers; the nearest pair shows where segments blur into each other."
            )

    st.subheader("Export the evidence and customer-to-segment map")
    st.caption(
        "The map records which segment the chosen model placed each customer in. It is not a list of marketing tasks "
        "or actions. **Tip:** join the segment column onto your transaction history and open it in **Worth Signal** "
        "(our customer-value sibling) to compare each segment’s value, retention, and CLV."
    )
    segment_map = build_segment_map(frame, setup["id_column"], solution.segment_labels, solution.confidence, names)
    numeric_export = profile.numeric.copy()
    categorical_export = profile.categorical.copy()
    diagnostics = pd.DataFrame([st.session_state.get(k("chosen_diagnostics"), {})])
    comparison = st.session_state.get(k("comparison"))
    all_candidates = comparison.diagnostics if comparison else diagnostics
    candidate_failures = (
        comparison.failures if comparison is not None else pd.DataFrame(columns=["method", "segments", "reason"])
    )
    fingerprint_columns = list(dict.fromkeys([setup["id_column"]] + setup["basis"]))
    dataset_fingerprint = hashlib.sha256(
        pd.util.hash_pandas_object(frame[fingerprint_columns].astype(str), index=True).values.tobytes()
    ).hexdigest()
    prepared = st.session_state.get(k("prepared"))
    metadata = {
        "product": "Segment Signal", "version": __version__, "source": setup.get("source"), "purpose": setup["goal"],
        "algorithm": solution.algorithm, "segments": solution.k, "random_seed": seed,
        "basis_variables": setup["basis"], "descriptor_variables": setup["descriptors"],
        "preprocessing": prepared.audit if prepared else {},
        "comparison_settings": st.session_state.get(k("comparison_settings"), {}),
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
        key=k("download_excel"),
    )
    full_width(
        downloads[1].download_button,
        "Download customer segment CSV", safe_for_spreadsheet(segment_map).to_csv(index=False).encode("utf-8"),
        "customer_segment_map.csv", "text/csv",
        key=k("download_csv"),
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
        key=k("download_json"),
    )


def methods_page() -> None:
    sig.header("Methods and limits", "Methods, assumptions, and honest limits")
    sig.note("warn", CAUTION)
    st.subheader("The workflow follows segmentation practice, not just clustering software")
    st.write(
        "First define the decision, then distinguish segmentation bases from descriptors. Bases form groups; descriptors help profile and reach them. "
        "The app standardizes numeric scales by default (optional for data already on one shared scale), can tame extreme values and strong skew, one-hot encodes categorical bases, compares several methods, and profiles the selected solution in the original units."
    )
    method_cards = [
        ("K-means", "Fast and transparent for compact groups in scaled numeric space. It gives each customer one segment membership and can miss irregular or overlapping structures."),
        ("Gaussian mixture", "For numeric-only bases, allows overlapping elliptical groups and produces membership probabilities. It is omitted for categorical or binary bases and needs ample observations per dimension."),
        ("Ward hierarchy", "Builds a nested grouping by minimizing added within-group variance. It is useful for smaller datasets and cannot directly assign future customers."),
        ("Spectral (flexible shapes)", f"Scores how similar every pair of customers is and groups customers who stay strongly connected, which can capture stretched or curved patterns the other methods split. It is limited to {SPECTRAL_ROW_LIMIT:,} customers and cannot directly assign future customers."),
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


PAGE_VIEWS = {
    "Welcome": welcome_page,
    "1 · Data & purpose": data_page,
    "2 · Compare solutions": compare_page,
    "3 · Profiles & export": profiles_page,
    "Methods & limits": methods_page,
}


def render() -> None:
    """Draw the whole Segment Signal app on the current page. Never calls st.set_page_config or st.navigation."""
    sig.apply(NS)
    _ensure_state()
    page = _sidebar()
    sig.masthead(NS, MASTHEAD_PROMISES, MASTHEAD_KICKER)
    try:
        PAGE_VIEWS[page]()
    except Exception as exc:
        show_error(exc)
    sig.footer(NS, __version__, FOOTER_LINE)

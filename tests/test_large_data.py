"""Data limits: none locally, demo caps only with SIGNAL_PUBLIC=1, and sampled models still cover every customer.

Every test here is fast: inputs beyond the demo caps are built by lowering a cap, never by building a huge file.
"""

from io import BytesIO
from pathlib import Path
import zipfile

import numpy as np
import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from segmentsignal import limits
from segmentsignal.errors import DataProblem, friendly_message
from segmentsignal.features import build_rfm, latest_date
from segmentsignal.io import load_data, results_to_json
from segmentsignal.limits import Limits
from segmentsignal.modeling import assign_all_customers, compare_solutions, fit_solution, hierarchy_views
from segmentsignal.preprocessing import PreprocessConfig, prepare_features
from segmentsignal.validation import validate_customer_table


ROOT = Path(__file__).parents[1]
BASIS = ("recency_days", "purchase_frequency", "annual_spend", "engagement_score", "discount_share")
# Tiny demo caps, so "beyond the demo caps" stays fast to build.
TINY_DEMO = Limits(
    upload_bytes=1024, json_bytes=32, expanded_workbook_bytes=1024, table_rows=3, total_cells=6,
    customers=40, model_rows=40, hierarchical_rows=40, spectral_rows=40,
)


def _demo() -> pd.DataFrame:
    return load_data(ROOT / "examples" / "demo_customers.csv").tables["customers"]


@pytest.fixture
def tiny_demo_caps(monkeypatch):
    monkeypatch.setattr(limits, "PUBLIC_DEMO", TINY_DEMO)
    return monkeypatch


def _inputs_beyond_tiny_caps():
    csv = b"customer_id,spend\n" + b"".join(b"C%d,%d\n" % (index, index) for index in range(10))
    json_payload = b'[{"customer_id": "A", "spend": 1}, {"customer_id": "B", "spend": 2}]'
    output = BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as workbook:
        workbook.writestr("xl/worksheets/sheet1.xml", "x" * 4096)
    customers = pd.DataFrame({"customer_id": np.arange(60), "spend": np.arange(60) % 13})
    return csv, json_payload, output.getvalue(), customers


def test_local_mode_has_no_built_in_limits(tiny_demo_caps):
    tiny_demo_caps.delenv("SIGNAL_PUBLIC", raising=False)
    assert limits.active() == Limits()
    csv, json_payload, workbook, customers = _inputs_beyond_tiny_caps()
    assert load_data(csv, name="many.csv").tables["customers"].shape == (10, 2)
    assert load_data(json_payload, name="many.json").tables["customers"].shape == (2, 2)
    with pytest.raises(DataProblem, match="could not be read"):  # past the size guard; just not a real workbook
        load_data(workbook, name="large.xlsx")
    validate_customer_table(customers, "customer_id", ["spend"])
    matrix = np.random.default_rng(1).normal(size=(60, 2))
    assert len(compare_solutions(matrix, algorithms=("kmeans",), k_values=(3,), stability_repeats=2).labels) == 1
    assert hierarchy_views(matrix).max_segments == 8
    assert len(fit_solution(matrix, "spectral", 3, seed=1).segment_labels) == 60


def test_public_demo_enforces_its_caps_and_says_so(tiny_demo_caps):
    tiny_demo_caps.setenv("SIGNAL_PUBLIC", "1")
    csv, json_payload, workbook, customers = _inputs_beyond_tiny_caps()
    cases = [
        (lambda: load_data(b"x" * 1025, name="big.csv"), "Uploads are limited"),
        (lambda: load_data(json_payload, name="many.json"), "JSON uploads are limited"),
        (lambda: load_data(workbook, name="large.xlsx"), "expand to at most"),
        (lambda: load_data(csv, name="many.csv"), "more than 3 rows"),
        (lambda: validate_customer_table(customers, "customer_id", ["spend"]), "at most 40 customers"),
        (lambda: compare_solutions(np.zeros((41, 2)), algorithms=("kmeans",), k_values=(3,)), "at most 40 customers"),
        (lambda: fit_solution(np.zeros((41, 2)), "hierarchical", 3, 42), "limited to 40"),
        (lambda: fit_solution(np.zeros((41, 2)), "spectral", 3, 42), "limited to 40"),
        (lambda: hierarchy_views(np.zeros((41, 2))), "limited to 40"),
    ]
    for call, pattern in cases:
        with pytest.raises(DataProblem, match=pattern) as caught:
            call()
        assert limits.DEMO_NOTE in str(caught.value)


def test_real_demo_caps_follow_the_previous_release_limits():
    assert limits.PUBLIC_DEMO.upload_bytes == 200 * 1024 * 1024
    assert limits.PUBLIC_DEMO.table_rows == 1_000_000
    assert limits.PUBLIC_DEMO.customers == 25_000


def test_running_out_of_memory_is_a_plain_message(monkeypatch):
    assert "not enough memory" in friendly_message(MemoryError())

    def exhausted(*args, **kwargs):
        raise MemoryError

    monkeypatch.setattr("segmentsignal.io.pd.read_csv", exhausted)
    with pytest.raises(DataProblem, match="not enough memory for this file"):
        load_data(b"a,b\n1,2\n", name="huge.csv")


def test_a_csv_above_the_old_one_million_row_cap_loads():
    raw = b"customer_id;spend\n" + b"".join(b"C%d;%d\n" % (index, index % 97) for index in range(1_000_050))
    frame = load_data(raw, name="many_rows.csv").tables["customers"]
    assert frame.shape == (1_000_050, 2)
    assert frame["spend"].dtype.kind == "i"


def test_large_json_exports_keep_every_row(monkeypatch):
    monkeypatch.setattr("segmentsignal.io.JSON_COMPACT_ROWS", 2)
    frame = pd.DataFrame({"customer_id": ["A", "B", "C"], "segment": ["Segment 1"] * 3})
    import json

    payload = json.loads(results_to_json({"map": frame, "small": frame.head(1)}, {"seed": 1}))
    assert payload["map"] == frame.to_dict(orient="records")
    assert payload["small"] == frame.head(1).to_dict(orient="records")
    assert payload["analysis_metadata"] == {"seed": 1}


def test_large_tables_fit_on_a_sample_and_assign_every_customer():
    frame = _demo()
    config = PreprocessConfig(BASIS, ("preferred_channel",))
    full = prepare_features(frame, config)
    sampled = prepare_features(frame, config, model_rows=200, seed=7)

    assert full.sample_positions is None and full.matrix.shape[0] == len(frame)
    assert sampled.matrix.shape == (200, full.matrix.shape[1])
    assert "seeded random sample of 200 customers" in sampled.audit["model_sample"]["note"]
    # Statistics come from every customer, so the sampled rows are exactly the full rows at those positions.
    np.testing.assert_array_equal(sampled.matrix, full.matrix[sampled.sample_positions])
    np.testing.assert_allclose(sampled.transform.transform(frame), full.matrix)

    for algorithm in ("kmeans", "hierarchical", "gmm"):
        if algorithm == "gmm":
            numeric = PreprocessConfig(BASIS)
            prepared = prepare_features(frame, numeric, model_rows=400, seed=7)
        else:
            prepared = sampled
        solution = fit_solution(prepared.matrix, algorithm, 3, seed=42)
        extended = assign_all_customers(solution, prepared, frame)
        assert len(extended.segment_labels) == len(frame)
        assert set(extended.segment_labels) == set(solution.segment_labels)
        np.testing.assert_array_equal(extended.segment_labels[prepared.sample_positions], solution.segment_labels)
        np.testing.assert_array_equal(extended.fit_positions, prepared.sample_positions)
        assert np.all((extended.confidence >= 0) & (extended.confidence <= 1))


def test_assignment_is_a_no_op_when_every_customer_was_modelled():
    frame = _demo()
    prepared = prepare_features(frame, PreprocessConfig(BASIS))
    solution = fit_solution(prepared.matrix, "kmeans", 3, seed=42)
    assert assign_all_customers(solution, prepared, frame) is solution


def test_non_date_column_in_a_large_purchase_log_fails_fast(monkeypatch):
    log = pd.DataFrame({"cid": ["A", "B", "C"], "when": ["x1", "x2", "x3"], "amount": [1, 2, 3]})
    monkeypatch.setattr("segmentsignal.features.DATE_CHECK_ROWS", 2)
    with pytest.raises(DataProblem, match="does not look like dates"):
        build_rfm(log, "cid", "when", "amount")
    assert latest_date(log["when"]) is None
    assert latest_date(pd.Series(["2026-01-01", "2026-03-02"])) == pd.Timestamp("2026-03-02")


SAMPLED_APP = """
import segmentsignal.ui.app as segment_app

segment_app.MODEL_SAMPLE_ROWS = 200
segment_app.EXCEL_SHEET_ROWS = 100
segment_app.render()
"""


def test_sampled_workflow_reaches_profiles_with_every_customer_assigned():
    app = AppTest.from_string(SAMPLED_APP, default_timeout=120)
    app.run()
    app.sidebar.radio[0].set_value("1 · Data & purpose").run()
    next(button for button in app.button if button.label == "Save this analysis setup").click().run()
    app.sidebar.radio[0].set_value("2 · Compare solutions").run()
    assert any("random sample of 200" in str(element.value) for element in app.markdown)
    next(button for button in app.button if button.label == "Run the comparison").click().run()
    assert not app.exception, [error.value for error in app.exception]
    next(button for button in app.button if button.label == "Create this segmentation").click().run()
    assert not app.exception, [error.value for error in app.exception]
    assert app.sidebar.radio[0].value == "3 · Profiles & export"
    solution = app.session_state["segment:solution"]
    assert len(solution.segment_labels) == 600 and len(solution.fit_positions) == 200
    assert any("more than an Excel sheet holds" in str(element.value) for element in app.caption)


def test_streamed_dataset_fingerprint_matches_the_whole_table_formula():
    import hashlib

    from segmentsignal.io import dataset_fingerprint

    frame = _demo()
    columns = ["customer_id", *BASIS]
    expected = hashlib.sha256(
        pd.util.hash_pandas_object(frame[columns].astype(str), index=True).values.tobytes()
    ).hexdigest()
    assert dataset_fingerprint(frame, columns) == expected

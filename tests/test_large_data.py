"""Large-data limits: the old caps no longer block, the new caps explain themselves, and sampled models cover everyone.

Every test here is fast: large inputs are simulated by lowering a limit, never by building a huge file.
"""

from io import BytesIO
from pathlib import Path
import zipfile

import numpy as np
import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from segmentsignal import io as segment_io
from segmentsignal.errors import DataProblem
from segmentsignal.features import build_rfm, latest_date
from segmentsignal.io import load_data
from segmentsignal.modeling import assign_all_customers, compare_solutions, fit_solution
from segmentsignal.preprocessing import MODEL_SAMPLE_ROWS, PreprocessConfig, prepare_features
from segmentsignal.validation import validate_customer_table


ROOT = Path(__file__).parents[1]
BASIS = ("recency_days", "purchase_frequency", "annual_spend", "engagement_score", "discount_share")


def _demo() -> pd.DataFrame:
    return load_data(ROOT / "examples" / "demo_customers.csv").tables["customers"]


def test_default_limits_match_the_1000_mb_upload_cap():
    assert segment_io.MAX_UPLOAD_MB == 1000
    assert segment_io.MAX_UPLOAD_BYTES == 1000 * 1024 * 1024
    assert segment_io.MAX_UNCOMPRESSED_EXCEL_BYTES >= segment_io.MAX_UPLOAD_BYTES
    assert segment_io.MAX_TABLE_ROWS >= 5_000_000
    assert not hasattr(segment_io, "MAX_JSON_BYTES"), "JSON shares the one upload limit"


def test_launcher_variable_sets_the_in_code_cap(monkeypatch):
    monkeypatch.setenv("SEGMENTSIGNAL_MAX_UPLOAD_MB", "250")
    assert segment_io._configured_upload_mb() == 250
    monkeypatch.setenv("SEGMENTSIGNAL_MAX_UPLOAD_MB", "not-a-number")
    assert segment_io._configured_upload_mb() == 1000
    monkeypatch.setenv("SEGMENTSIGNAL_MAX_UPLOAD_MB", "0")
    assert segment_io._configured_upload_mb() == 1


def test_a_csv_above_the_old_one_million_row_cap_loads():
    raw = b"customer_id;spend\n" + b"".join(b"C%d;%d\n" % (index, index % 97) for index in range(1_000_050))
    frame = load_data(raw, name="many_rows.csv").tables["customers"]
    assert frame.shape == (1_000_050, 2)
    assert frame["spend"].dtype.kind == "i"


def test_json_above_the_old_separate_cap_is_accepted(monkeypatch):
    payload = b'[{"customer_id": "A", "spend": 1}, {"customer_id": "B", "spend": 2}]'
    # The former 50 MB JSON-only limit is gone: JSON is bounded only by the shared upload cap.
    monkeypatch.setattr(segment_io, "MAX_UPLOAD_BYTES", len(payload))
    assert load_data(payload, name="customers.json").tables["customers"].shape == (2, 2)
    monkeypatch.setattr(segment_io, "MAX_UPLOAD_BYTES", len(payload) - 1)
    with pytest.raises(DataProblem, match="larger than the configured"):
        load_data(payload, name="customers.json")


def test_cell_and_workbook_limits_explain_themselves(monkeypatch):
    monkeypatch.setattr(segment_io, "MAX_TOTAL_CELLS", 5)
    with pytest.raises(DataProblem, match="5 cells"):
        load_data(b"a,b\n1,2\n3,4\n5,6\n", name="wide.csv")

    output = BytesIO()
    with zipfile.ZipFile(output, "w") as workbook:
        workbook.writestr("xl/worksheets/sheet1.xml", "x" * 4096)
    monkeypatch.setattr(segment_io, "MAX_UNCOMPRESSED_EXCEL_BYTES", 1024)
    with pytest.raises(DataProblem, match="expands beyond"):
        load_data(output.getvalue(), name="bomb.xlsx")


def test_more_than_the_old_25000_customers_pass_validation(monkeypatch):
    frame = pd.DataFrame({"customer_id": np.arange(30_000), "spend": np.arange(30_000) % 13})
    validate_customer_table(frame, "customer_id", ["spend"])
    monkeypatch.setattr("segmentsignal.validation.MAX_TABLE_ROWS", 29_999)
    with pytest.raises(DataProblem, match="at most 29,999 customers"):
        validate_customer_table(frame, "customer_id", ["spend"])


def test_comparison_keeps_its_sample_sized_limit_with_a_clear_message():
    with pytest.raises(DataProblem, match=f"limited to {MODEL_SAMPLE_ROWS:,} rows"):
        compare_solutions(np.zeros((MODEL_SAMPLE_ROWS + 1, 2)), algorithms=("kmeans",), k_values=(3,))


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
segment_app.WORKBOOK_MAP_ROWS = 100
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
    assert any("Excel and JSON packs carry a note" in str(element.value) for element in app.caption)


def test_streamed_dataset_fingerprint_matches_the_whole_table_formula():
    import hashlib

    from segmentsignal.io import dataset_fingerprint

    frame = _demo()
    columns = ["customer_id", *BASIS]
    expected = hashlib.sha256(
        pd.util.hash_pandas_object(frame[columns].astype(str), index=True).values.tobytes()
    ).hexdigest()
    assert dataset_fingerprint(frame, columns) == expected

import numpy as np
import pandas as pd
import pytest

from segmentsignal.errors import DataProblem
from segmentsignal.features import build_rfm
from segmentsignal.preprocessing import PreprocessConfig, infer_feature_types, prepare_features


def test_rfm_aggregation_uses_reference_date_and_unique_orders():
    transactions = pd.DataFrame(
        {
            "cid": ["A", "A", "A", "B"],
            "order": ["1", "1", "2", "3"],
            "date": ["2026-01-01", "2026-01-01", "2026-01-10", "2026-01-05"],
            "amount": [10, 5, 20, 8],
        }
    )
    result = build_rfm(transactions, "cid", "date", "amount", "order", "2026-01-11")
    a = result[result["customer_id"] == "A"].iloc[0]
    assert a["recency_days"] == 1
    assert a["frequency"] == 2
    assert a["monetary_value"] == 35
    assert a["average_order_value"] == 17.5
    assert a["customer_tenure_days"] == 9


def test_mixed_preprocessing_preserves_rows_and_is_finite():
    frame = pd.DataFrame(
        {
            "spend": [1.0, 2.0, np.nan, 1000.0, 5.0, 6.0],
            "engagement": [1, 2, 3, 4, 5, 6],
            "channel": ["Email", "Store", None, "Email", "Social", "Email"],
        }
    )
    prepared = prepare_features(
        frame,
        PreprocessConfig(("spend", "engagement"), ("channel",), clip_outliers=True, log_skewed=True),
    )
    assert prepared.matrix.shape[0] == len(frame)
    assert prepared.matrix.shape[1] >= 4
    assert np.isfinite(prepared.matrix).all()
    assert prepared.audit["missing_values_imputed"] == 2


def test_constant_columns_are_removed_with_warning():
    frame = pd.DataFrame({"constant": [1] * 40, "varies": list(range(40))})
    prepared = prepare_features(frame, PreprocessConfig(("constant", "varies")))
    assert prepared.matrix.shape == (40, 1)
    assert any("Constant" in warning for warning in prepared.warnings)


def test_all_missing_numeric_column_before_valid_column_is_removed():
    frame = pd.DataFrame({"empty": [np.nan] * 40, "varies": list(range(40))})
    prepared = prepare_features(frame, PreprocessConfig(("empty", "varies")))
    assert prepared.matrix.shape == (40, 1)
    assert np.isfinite(prepared.matrix).all()


def test_mixed_customer_id_types_preserve_input_group_order():
    frame = pd.DataFrame(
        {"cid": ["A", 2, "A"], "date": ["2026-01-01", "2026-01-02", "2026-01-03"], "amount": [1, 2, 3]}
    )
    result = build_rfm(frame, "cid", "date", "amount", reference_date="2026-01-04")
    assert result["customer_id"].tolist() == ["A", 2]


def test_blank_selected_order_ids_are_rejected():
    frame = pd.DataFrame(
        {"cid": ["A", "B"], "order": ["1", None], "date": ["2026-01-01", "2026-01-02"], "amount": [1, 2]}
    )
    with pytest.raises(DataProblem, match="order ID contains blank"):
        build_rfm(frame, "cid", "date", "amount", "order", "2026-01-04")


def test_numeric_looking_text_is_audited_when_coercion_is_needed():
    values = [str(value) for value in range(38)] + ["bad", ""]
    frame = pd.DataFrame({"survey_score": values})
    numeric, categorical = infer_feature_types(frame, ["survey_score"])
    assert numeric == ["survey_score"] and categorical == []
    prepared = prepare_features(frame, PreprocessConfig(("survey_score",)))
    assert prepared.audit["numeric_parse_failures"] == {"survey_score": 2}
    assert any("Non-numeric" in warning for warning in prepared.warnings)


def test_boolean_is_inferred_as_categorical():
    frame = pd.DataFrame({"member": [True, False] * 20})
    assert infer_feature_types(frame, ["member"]) == ([], ["member"])


def test_categorical_block_collapsed_by_rare_grouping_fails_clearly():
    frame = pd.DataFrame({"unique_category": [f"value_{index}" for index in range(40)]})
    with pytest.raises(DataProblem, match="no usable variation"):
        prepare_features(frame, PreprocessConfig((), ("unique_category",)))

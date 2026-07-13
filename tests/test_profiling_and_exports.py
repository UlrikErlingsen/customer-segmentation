from pathlib import Path

import numpy as np
import pandas as pd

from segmentsignal.io import load_data, results_to_excel
from segmentsignal.modeling import fit_solution
from segmentsignal.preprocessing import PreprocessConfig, prepare_features
from segmentsignal.profiling import build_segment_map, profile_segments


ROOT = Path(__file__).parents[1]


def test_profiles_and_assignments_cover_every_customer():
    frame = load_data(ROOT / "examples" / "demo_customers.csv").tables["customers"]
    basis = ["recency_days", "purchase_frequency", "annual_spend", "discount_share"]
    prepared = prepare_features(frame, PreprocessConfig(tuple(basis)))
    solution = fit_solution(prepared.matrix, "kmeans", 4, 42)
    profiles = profile_segments(frame, solution.segment_labels, basis, ["region", "preferred_channel", "age"])

    assert profiles.summary["customers"].sum() == len(frame)
    assert set(profiles.summary["segment"]) == set(solution.segment_labels)
    assert set(profiles.numeric["role"]) == {"basis", "descriptor"}
    assert not profiles.categorical.empty
    assert profiles.cards["suggested_name"].str.len().min() > 2

    names = dict(zip(profiles.cards["segment"], profiles.cards["suggested_name"]))
    assignments = build_segment_map(frame, "customer_id", solution.segment_labels, solution.confidence, names)
    assert len(assignments) == len(frame)
    assert assignments["customer_id"].equals(frame["customer_id"])
    assert assignments["segment_name"].notna().all()
    assert results_to_excel({"Assignments": assignments})[:2] == b"PK"


def test_reserved_source_id_name_is_not_overwritten():
    frame = load_data(ROOT / "examples" / "demo_customers.csv").tables["customers"].head(3).copy()
    frame = frame.rename(columns={"customer_id": "segment"})
    labels = np.array(["Segment 1", "Segment 2", "Segment 1"])
    assignments = build_segment_map(frame, "segment", labels, np.array([0.8, 0.7, 0.9]))
    assert assignments.columns.tolist()[:2] == ["customer_segment", "segment"]
    assert assignments["customer_segment"].equals(frame["segment"])


def test_source_basis_named_segment_is_profiled_without_collision():
    frame = pd.DataFrame({"segment": [1.0, 2.0, 10.0, 11.0]})
    labels = np.array(["Segment 1", "Segment 1", "Segment 2", "Segment 2"])
    profiles = profile_segments(frame, labels, ["segment"])
    assert profiles.numeric["feature"].eq("segment").all()
    assert profiles.numeric["mean"].tolist() == [1.5, 10.5]


def test_categorical_only_profiles_name_overrepresented_levels():
    frame = pd.DataFrame({"channel": ["A"] * 6 + ["B"] * 4 + ["A"] * 2 + ["B"] * 8})
    labels = np.array(["Segment 1"] * 10 + ["Segment 2"] * 10)
    profiles = profile_segments(frame, labels, ["channel"])
    names = dict(zip(profiles.cards["segment"], profiles.cards["suggested_name"]))
    assert names["Segment 2"].startswith("channel: B")
    assert not profiles.cards["suggested_name"].eq("Broad middle").all()


def test_zero_difference_second_trait_is_not_named():
    frame = pd.DataFrame({"strong": [0.0] * 10 + [10.0] * 10, "constant": [1.0] * 20})
    labels = np.array(["Segment 1"] * 10 + ["Segment 2"] * 10)
    profiles = profile_segments(frame, labels, ["strong", "constant"])
    assert not profiles.cards["suggested_name"].str.contains("constant").any()


def test_numeric_looking_survey_text_is_profiled_numerically():
    frame = pd.DataFrame({"survey_score": [str(value) for value in range(20)]})
    labels = np.array(["Segment 1"] * 10 + ["Segment 2"] * 10)
    profiles = profile_segments(frame, labels, ["survey_score"])
    assert profiles.numeric["feature"].eq("survey_score").all()
    assert profiles.categorical.empty


def test_mixed_basis_card_can_surface_numeric_and_categorical_traits():
    frame = pd.DataFrame(
        {
            "attitude_score": [1.0] * 10 + [9.0] * 10,
            "preferred_format": ["Simple"] * 8 + ["Detailed"] * 2 + ["Simple"] * 2 + ["Detailed"] * 8,
        }
    )
    labels = np.array(["Segment 1"] * 10 + ["Segment 2"] * 10)
    profiles = profile_segments(frame, labels, ["attitude_score", "preferred_format"])
    second = profiles.cards.loc[profiles.cards["segment"] == "Segment 2", "suggested_name"].iloc[0]
    assert "Higher attitude score" in second
    assert "preferred format: Detailed" in second

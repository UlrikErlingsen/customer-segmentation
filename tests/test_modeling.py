from pathlib import Path

import numpy as np
import pytest
from sklearn.metrics import adjusted_rand_score
from sklearn.exceptions import ConvergenceWarning

from segmentsignal.errors import DataProblem
from segmentsignal.io import load_data
from segmentsignal.modeling import compare_solutions, fit_solution
from segmentsignal.preprocessing import PreprocessConfig, prepare_features


ROOT = Path(__file__).parents[1]
BASIS = (
    "recency_days",
    "purchase_frequency",
    "annual_spend",
    "engagement_score",
    "discount_share",
    "return_rate",
    "satisfaction_score",
)


def test_demo_structure_is_recovered_and_deterministic():
    frame = load_data(ROOT / "examples" / "demo_customers.csv").tables["customers"]
    prepared = prepare_features(frame, PreprocessConfig(BASIS))
    first = compare_solutions(prepared.matrix, ("kmeans", "gmm", "hierarchical"), (3, 4, 5), 4, 42)
    second = compare_solutions(prepared.matrix, ("kmeans", "gmm", "hierarchical"), (3, 4, 5), 4, 42)
    assert first.diagnostics.iloc[0]["segments"] == 4
    assert first.diagnostics.iloc[0]["quality"] in {"Promising", "Strong"}
    assert np.allclose(first.diagnostics["recommendation_score"], second.diagnostics["recommendation_score"])

    solution = fit_solution(prepared.matrix, "kmeans", 4, seed=42)
    assert adjusted_rand_score(frame["demo_truth"], solution.raw_labels) > 0.90
    assert len(solution.segment_labels) == len(frame)
    assert solution.confidence.min() >= 0.5
    assert solution.projection.shape == (len(frame), 4)


def test_unstructured_noise_is_not_called_strong():
    rng = np.random.default_rng(7)
    noise = rng.normal(size=(300, 7))
    comparison = compare_solutions(noise, ("kmeans", "hierarchical"), (3, 4, 5), 3, 42)
    assert comparison.diagnostics.iloc[0]["quality"] not in {"Strong", "Promising"}


def test_metrics_have_expected_direction_and_ranges():
    rng = np.random.default_rng(4)
    matrix = np.vstack([rng.normal(-3, 0.3, (80, 3)), rng.normal(3, 0.3, (80, 3))])
    result = compare_solutions(matrix, ("kmeans",), (2, 3), 3, 10).diagnostics
    two = result[result["segments"] == 2].iloc[0]
    assert two["silhouette"] > 0.8
    assert 0 <= two["stability"] <= 1
    assert two["smallest_segment_%"] == 50


def test_collapsed_solution_is_not_reported_as_requested_k():
    with pytest.warns(ConvergenceWarning):
        with pytest.raises(DataProblem, match="instead of the requested 3"):
            fit_solution(np.zeros((40, 2)), "kmeans", 3, 42)


def test_small_sample_cannot_receive_strong_or_promising_label():
    rng = np.random.default_rng(8)
    matrix = np.vstack([rng.normal(index * 10, 0.01, (4, 2)) for index in range(8)])
    result = compare_solutions(matrix, ("kmeans",), (8,), 4, 42).diagnostics.iloc[0]
    assert result["quality"] not in {"Strong", "Promising"}


def test_spectral_recovers_well_separated_groups():
    rng = np.random.default_rng(5)
    matrix = np.vstack(
        [rng.normal(-4, 0.4, (60, 3)), rng.normal(0, 0.4, (60, 3)), rng.normal(4, 0.4, (60, 3))]
    )
    truth = np.repeat([0, 1, 2], 60)
    solution = fit_solution(matrix, "spectral", 3, seed=42)
    assert adjusted_rand_score(truth, solution.raw_labels) > 0.9
    assert len(np.unique(solution.raw_labels)) == 3
    assert np.all((solution.confidence >= 0) & (solution.confidence <= 1))


def test_spectral_row_limit_is_enforced():
    with pytest.raises(DataProblem, match="2,500"):
        fit_solution(np.zeros((2600, 2)), "spectral", 3, 42)


def test_comparison_can_include_spectral_candidates():
    rng = np.random.default_rng(6)
    matrix = np.vstack([rng.normal(-3, 0.3, (60, 2)), rng.normal(3, 0.3, (60, 2))])
    result = compare_solutions(matrix, ("kmeans", "spectral"), (2,), 4, 42)
    assert (result.diagnostics["method"] == "Spectral (flexible shapes)").any()
    spectral_row = result.diagnostics[result.diagnostics["method"] == "Spectral (flexible shapes)"].iloc[0]
    assert spectral_row["silhouette"] > 0.8


def test_underdetermined_full_gmm_is_reported_as_failure():
    rng = np.random.default_rng(9)
    matrix = rng.normal(size=(100, 20))
    result = compare_solutions(matrix, ("kmeans", "gmm"), (4,), 4, 42)
    assert "Gaussian mixture" in result.failures["method"].tolist()
    assert not ((result.diagnostics["method"] == "Gaussian mixture") & (result.diagnostics["segments"] == 4)).any()

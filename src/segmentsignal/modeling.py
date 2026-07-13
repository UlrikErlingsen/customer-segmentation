"""Clustering, multi-signal validation, and reproducible solution fitting."""

from __future__ import annotations

from dataclasses import dataclass
from math import log

import numpy as np
import pandas as pd
from scipy.cluster.hierarchy import dendrogram as _scipy_dendrogram
from scipy.cluster.hierarchy import linkage as _scipy_linkage
from sklearn.cluster import AgglomerativeClustering, KMeans, SpectralClustering
from sklearn.decomposition import PCA
from sklearn.metrics import (
    adjusted_rand_score,
    calinski_harabasz_score,
    davies_bouldin_score,
    silhouette_score,
)
from sklearn.mixture import GaussianMixture

from .errors import DataProblem


ALGORITHM_LABELS = {
    "kmeans": "K-means",
    "gmm": "Gaussian mixture",
    "hierarchical": "Hierarchical (Ward)",
    "spectral": "Spectral (flexible shapes)",
}

SPECTRAL_ROW_LIMIT = 2500


@dataclass
class ComparisonResult:
    """Candidate diagnostics and their row labels for agreement checks."""

    diagnostics: pd.DataFrame
    labels: dict[tuple[str, int], np.ndarray]
    failures: pd.DataFrame


@dataclass
class HierarchyViews:
    """Nested Ward splits for an icicle chart plus truncated dendrogram coordinates."""

    icicle: pd.DataFrame
    dendrogram: dict
    max_segments: int


@dataclass
class SegmentSolution:
    """A fitted segmentation with display labels and a 2-D projection."""

    algorithm: str
    k: int
    raw_labels: np.ndarray
    segment_labels: np.ndarray
    confidence: np.ndarray
    projection: pd.DataFrame
    explained_variance: float


def _fit_labels(matrix: np.ndarray, algorithm: str, k: int, seed: int) -> tuple[np.ndarray, object]:
    if k < 2 or k >= len(matrix):
        raise DataProblem("The number of segments must be at least 2 and smaller than the number of customers.")
    if algorithm == "kmeans":
        model = KMeans(n_clusters=k, n_init=20, random_state=seed, max_iter=500)
        labels = model.fit_predict(matrix)
    elif algorithm == "gmm":
        minimum_required = k * max(30, 5 * matrix.shape[1])
        if len(matrix) < minimum_required:
            raise DataProblem(
                f"A full-covariance Gaussian mixture with {k} groups and {matrix.shape[1]} model columns "
                f"requires at least {minimum_required} customers in this app."
            )
        model = GaussianMixture(
            n_components=k,
            covariance_type="full",
            n_init=5,
            reg_covar=1e-6,
            random_state=seed,
            max_iter=500,
        )
        labels = model.fit_predict(matrix)
        if not model.converged_:
            raise DataProblem("The Gaussian mixture did not converge for this candidate.")
    elif algorithm == "hierarchical":
        if len(matrix) > 5000:
            raise DataProblem("Hierarchical clustering is limited to 5,000 customers. Use K-means for larger files.")
        model = AgglomerativeClustering(n_clusters=k, linkage="ward")
        labels = model.fit_predict(matrix)
    elif algorithm == "spectral":
        if len(matrix) > SPECTRAL_ROW_LIMIT:
            raise DataProblem(
                f"Spectral clustering is limited to {SPECTRAL_ROW_LIMIT:,} customers in this app. Use K-means for larger files."
            )
        model = SpectralClustering(
            n_clusters=k,
            affinity="rbf",
            gamma=1.0 / matrix.shape[1],
            assign_labels="kmeans",
            n_init=10,
            random_state=seed,
        )
        labels = model.fit_predict(matrix)
    else:
        raise DataProblem(f"Unknown clustering method: {algorithm}.")
    realized = len(np.unique(labels))
    if realized != k:
        raise DataProblem(
            f"This candidate produced {realized} distinct groups instead of the requested {k} and cannot be evaluated."
        )
    return labels.astype(int), model


def _balance_score(labels: np.ndarray) -> float:
    shares = np.bincount(labels) / len(labels)
    entropy = -float(np.sum(shares * np.log(shares + 1e-12)))
    return float(entropy / max(log(len(shares)), 1e-12))


def _subsample_stability(
    matrix: np.ndarray,
    full_labels: np.ndarray,
    algorithm: str,
    k: int,
    repeats: int,
    seed: int,
) -> tuple[float, float, int]:
    rng = np.random.default_rng(seed)
    sample_size = max(k + 1, int(round(len(matrix) * 0.8)))
    sample_size = min(sample_size, len(matrix) - 1)
    scores: list[float] = []
    successful = 0
    for repeat in range(max(2, repeats)):
        indices = np.sort(rng.choice(len(matrix), size=sample_size, replace=False))
        try:
            subsample_labels, _ = _fit_labels(matrix[indices], algorithm, k, seed + repeat + 1)
            scores.append(adjusted_rand_score(full_labels[indices], subsample_labels))
            successful += 1
        except Exception:
            scores.append(0.0)
    return float(np.mean(scores)), float(np.std(scores, ddof=1)) if len(scores) > 1 else 0.0, successful


def _quality_label(row: pd.Series) -> str:
    silhouette = float(row["silhouette"])
    stability = float(row["stability"])
    minimum_share = float(row["smallest_segment_%"]) / 100
    customers = int(row["customers"])
    minimum_customers = int(row["smallest_segment_customers"])
    enough_repeats = int(row["stability_repeats"]) >= 4 and int(row["stability_successful_repeats"]) >= 4
    if (
        customers >= 300
        and minimum_customers >= 30
        and silhouette >= 0.45
        and stability >= 0.80
        and minimum_share >= 0.05
        and enough_repeats
    ):
        return "Strong"
    if (
        customers >= 100
        and minimum_customers >= 20
        and silhouette >= 0.25
        and stability >= 0.65
        and minimum_share >= 0.03
        and enough_repeats
    ):
        return "Promising"
    if minimum_customers >= 5 and silhouette >= 0.12 and stability >= 0.50 and minimum_share >= 0.02:
        return "Exploratory"
    return "Weak"


def compare_solutions(
    matrix: np.ndarray,
    algorithms: tuple[str, ...] = ("kmeans", "gmm", "hierarchical"),
    k_values: tuple[int, ...] = (3, 4, 5, 6),
    stability_repeats: int = 6,
    seed: int = 42,
) -> ComparisonResult:
    """Compare candidate solutions using separation, size, stability, and agreement."""
    matrix = np.asarray(matrix, dtype=float)
    if matrix.ndim != 2 or len(matrix) < 30:
        raise DataProblem("At least 30 prepared customer rows are required for comparison.")
    if len(matrix) > 25_000 or matrix.shape[1] > 200:
        raise DataProblem("The prepared analysis exceeds the supported limit of 25,000 rows by 200 model columns.")
    if not algorithms or not k_values:
        raise DataProblem("Choose at least one method and one candidate segment count.")

    rows: list[dict[str, object]] = []
    label_cache: dict[tuple[str, int], np.ndarray] = {}
    model_cache: dict[tuple[str, int], object] = {}
    failure_rows: list[dict[str, object]] = []
    for algorithm in algorithms:
        if algorithm not in ALGORITHM_LABELS:
            raise DataProblem(f"Unknown clustering method: {algorithm}.")
        for k in sorted(set(k_values)):
            if k >= len(matrix):
                continue
            try:
                labels, model = _fit_labels(matrix, algorithm, k, seed)
                label_cache[(algorithm, k)] = labels
                model_cache[(algorithm, k)] = model
                counts = np.bincount(labels)
                silhouette = silhouette_score(
                    matrix,
                    labels,
                    sample_size=min(2000, len(matrix)),
                    random_state=seed,
                )
                stability, stability_std, successful_repeats = _subsample_stability(
                    matrix, labels, algorithm, k, stability_repeats, seed
                )
                row: dict[str, object] = {
                    "algorithm_key": algorithm,
                    "method": ALGORITHM_LABELS[algorithm],
                    "segments": k,
                    "customers": len(labels),
                    "silhouette": float(silhouette),
                    "stability": stability,
                    "stability_std": stability_std,
                    "stability_repeats": max(2, stability_repeats),
                    "stability_successful_repeats": successful_repeats,
                    "calinski_harabasz": float(calinski_harabasz_score(matrix, labels)),
                    "davies_bouldin": float(davies_bouldin_score(matrix, labels)),
                    "smallest_segment_%": 100 * float(counts.min() / len(labels)),
                    "smallest_segment_customers": int(counts.min()),
                    "largest_segment_%": 100 * float(counts.max() / len(labels)),
                    "balance": _balance_score(labels),
                    "bic": np.nan,
                    "aic": np.nan,
                }
                if algorithm == "gmm":
                    row["bic"] = float(model.bic(matrix))
                    row["aic"] = float(model.aic(matrix))
                rows.append(row)
            except (DataProblem, ValueError, np.linalg.LinAlgError) as exc:
                failure_rows.append(
                    {
                        "method": ALGORITHM_LABELS.get(algorithm, algorithm),
                        "segments": k,
                        "reason": str(exc) if isinstance(exc, DataProblem) else "Numerical fitting failed for this candidate.",
                    }
                )
                continue

    if not rows:
        raise DataProblem("None of the candidate models could be fitted. Simplify the variables or try fewer segments.")
    diagnostics = pd.DataFrame(rows)

    agreements: list[float] = []
    for row in diagnostics.itertuples(index=False):
        peers = [
            adjusted_rand_score(label_cache[(row.algorithm_key, row.segments)], peer_labels)
            for (peer_algorithm, peer_k), peer_labels in label_cache.items()
            if peer_k == row.segments and peer_algorithm != row.algorithm_key
        ]
        agreements.append(float(np.mean(peers)) if peers else np.nan)
    diagnostics["cross_method_agreement"] = agreements

    silhouette_component = np.clip((diagnostics["silhouette"] + 0.05) / 0.55, 0, 1)
    stability_component = np.clip(diagnostics["stability"], 0, 1)
    minimum_size_component = np.clip(diagnostics["smallest_segment_%"] / 8, 0, 1)
    absolute_size_component = np.clip(diagnostics["smallest_segment_customers"] / 30, 0, 1)
    size_component = (
        0.45 * minimum_size_component
        + 0.25 * diagnostics["balance"].clip(0, 1)
        + 0.30 * absolute_size_component
    )
    agreement_component = diagnostics["cross_method_agreement"].clip(0, 1)
    simplicity_component = np.clip(1 - (diagnostics["segments"] - 2) / 10, 0, 1)
    full_score = 100 * (
        0.35 * silhouette_component
        + 0.30 * stability_component
        + 0.15 * size_component
        + 0.10 * agreement_component
        + 0.10 * simplicity_component
    )
    reduced_score = 100 * (
        0.35 * silhouette_component
        + 0.30 * stability_component
        + 0.15 * size_component
        + 0.10 * simplicity_component
    ) / 0.90
    has_agreement = diagnostics["cross_method_agreement"].notna()
    diagnostics["recommendation_score"] = np.where(has_agreement, full_score, reduced_score)
    diagnostics["agreement_component_source"] = np.where(
        has_agreement, "cross-method agreement", "not available; other weights renormalized"
    )
    diagnostics["quality"] = diagnostics.apply(_quality_label, axis=1)
    diagnostics["recommended"] = False
    eligible = diagnostics.index[diagnostics["quality"] != "Weak"]
    candidate_indices = eligible if len(eligible) else diagnostics.index
    best_index = diagnostics.loc[candidate_indices, "recommendation_score"].idxmax()
    diagnostics.loc[best_index, "recommended"] = True
    diagnostics = diagnostics.sort_values(
        ["recommended", "recommendation_score"], ascending=[False, False], kind="stable"
    ).reset_index(drop=True)
    return ComparisonResult(
        diagnostics=diagnostics,
        labels=label_cache,
        failures=pd.DataFrame(failure_rows, columns=["method", "segments", "reason"]),
    )


def hierarchy_views(matrix: np.ndarray, max_segments: int = 8, dendrogram_leaves: int = 25) -> HierarchyViews:
    """Build Ward-hierarchy views: nested split boxes (icicle) and a truncated dendrogram.

    The icicle frame contains one row per node of the truncated merge tree —
    the whole base at the top, splitting in two at every level until
    ``max_segments`` groups remain.
    """
    matrix = np.asarray(matrix, dtype=float)
    n = len(matrix)
    if n > 5000:
        raise DataProblem("Hierarchy views are limited to 5,000 customers, like Ward clustering itself.")
    if n < 4:
        raise DataProblem("At least 4 customers are required to draw a hierarchy.")
    max_segments = int(min(max_segments, n - 1))
    merge_table = _scipy_linkage(matrix, method="ward")

    def _count(cluster_id: float) -> int:
        cluster = int(cluster_id)
        return 1 if cluster < n else int(merge_table[cluster - n, 3])

    window_start = (n - 1) - (max_segments - 1)
    rows: list[dict[str, object]] = [{"id": str(2 * n - 2), "parent": "", "customers": n}]
    for merge_index in range(n - 2, window_start - 1, -1):
        node_id = str(n + merge_index)
        for child in (merge_table[merge_index, 0], merge_table[merge_index, 1]):
            rows.append({"id": str(int(child)), "parent": node_id, "customers": _count(child)})
    icicle = pd.DataFrame(rows)
    icicle["share_%"] = 100 * icicle["customers"] / n
    icicle["label"] = icicle.apply(
        lambda row: f"{int(row['customers']):,} customers · {row['share_%']:.0f}%", axis=1
    )

    tree = _scipy_dendrogram(
        merge_table, truncate_mode="lastp", p=int(min(dendrogram_leaves, n)), no_plot=True
    )
    return HierarchyViews(
        icicle=icicle,
        dendrogram={
            "icoord": tree["icoord"],
            "dcoord": tree["dcoord"],
            "leaf_labels": tree["ivl"],
        },
        max_segments=max_segments,
    )


def centroid_distances(matrix: np.ndarray, labels: np.ndarray) -> pd.DataFrame:
    """Pairwise Euclidean distances between segment centers in prepared space."""
    matrix = np.asarray(matrix, dtype=float)
    labels = np.asarray(labels)
    unique = sorted({str(label) for label in labels}, key=lambda name: (len(name), name))
    centroids = np.vstack([matrix[labels.astype(str) == label].mean(axis=0) for label in unique])
    distances = np.linalg.norm(centroids[:, None, :] - centroids[None, :, :], axis=2)
    return pd.DataFrame(np.round(distances, 3), index=unique, columns=unique)


def _membership_confidence(matrix: np.ndarray, labels: np.ndarray, model: object, algorithm: str) -> np.ndarray:
    if algorithm == "gmm" and hasattr(model, "predict_proba"):
        return np.asarray(model.predict_proba(matrix)).max(axis=1)
    unique = np.sort(np.unique(labels))
    centroids = np.vstack([matrix[labels == label].mean(axis=0) for label in unique])
    distances = np.linalg.norm(matrix[:, None, :] - centroids[None, :, :], axis=2)
    centroid_positions = {label: index for index, label in enumerate(unique)}
    assigned_positions = np.array([centroid_positions[label] for label in labels])
    assigned_distance = distances[np.arange(len(matrix)), assigned_positions]
    alternatives = distances.copy()
    alternatives[np.arange(len(matrix)), assigned_positions] = np.inf
    alternative_distance = alternatives.min(axis=1)
    return np.clip(alternative_distance / (assigned_distance + alternative_distance + 1e-12), 0.0, 1.0)


def fit_solution(matrix: np.ndarray, algorithm: str, k: int, seed: int = 42) -> SegmentSolution:
    """Fit one chosen candidate and create stable, human-readable segment numbers."""
    matrix = np.asarray(matrix, dtype=float)
    labels, model = _fit_labels(matrix, algorithm, k, seed)
    ordered = sorted(np.unique(labels), key=lambda label: (-int(np.sum(labels == label)), int(label)))
    display_map = {raw: f"Segment {index + 1}" for index, raw in enumerate(ordered)}
    display_labels = np.array([display_map[label] for label in labels], dtype=object)
    confidence = _membership_confidence(matrix, labels, model, algorithm)

    components = min(2, matrix.shape[1], len(matrix))
    pca = PCA(n_components=components, random_state=seed)
    projected = pca.fit_transform(matrix)
    if components == 1:
        projected = np.column_stack([projected[:, 0], np.zeros(len(projected))])
    projection = pd.DataFrame(
        {"PC1": projected[:, 0], "PC2": projected[:, 1], "segment": display_labels, "confidence": confidence}
    )
    return SegmentSolution(
        algorithm=algorithm,
        k=k,
        raw_labels=labels,
        segment_labels=display_labels,
        confidence=confidence,
        projection=projection,
        explained_variance=float(np.sum(pca.explained_variance_ratio_)),
    )

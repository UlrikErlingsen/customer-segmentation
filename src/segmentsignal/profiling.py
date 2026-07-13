"""Segment profiles, cautious labels, and customer-to-segment maps."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy import stats as _scipy_stats

from .preprocessing import infer_feature_types


def anova_table(frame: pd.DataFrame, segment_labels: np.ndarray, numeric_columns: list[str]) -> pd.DataFrame:
    """One-way ANOVA of each numeric basis variable across segments (SPSS-style).

    Because the segments were built to maximize exactly these differences,
    the F statistics and p-values are descriptive only — they rank which
    variables separate the groups most, and are not hypothesis tests.
    """
    labels = pd.Series(np.asarray(segment_labels).astype(str), index=frame.index)
    rows: list[dict[str, object]] = []
    for column in numeric_columns:
        if column not in frame.columns:
            continue
        values = pd.to_numeric(frame[column], errors="coerce")
        valid = values.notna()
        groups = [
            values[valid & (labels == segment)]
            for segment in sorted(labels.unique(), key=lambda name: (len(name), name))
        ]
        groups = [group for group in groups if len(group) >= 2]
        if len(groups) < 2:
            continue
        included = pd.concat(groups)
        grand_mean = float(included.mean())
        ss_between = float(sum(len(group) * (float(group.mean()) - grand_mean) ** 2 for group in groups))
        ss_total = float(((included - grand_mean) ** 2).sum())
        f_statistic, p_value = _scipy_stats.f_oneway(*groups)
        rows.append(
            {
                "variable": column,
                "F": float(f_statistic),
                "df_between": len(groups) - 1,
                "df_within": int(len(included) - len(groups)),
                "p_value": float(p_value),
                "eta_squared": float(ss_between / ss_total) if ss_total > 0 else np.nan,
            }
        )
    table = pd.DataFrame(rows, columns=["variable", "F", "df_between", "df_within", "p_value", "eta_squared"])
    if not table.empty:
        table = table.sort_values("F", ascending=False).reset_index(drop=True)
    return table


@dataclass
class ProfileResult:
    summary: pd.DataFrame
    numeric: pd.DataFrame
    categorical: pd.DataFrame
    cards: pd.DataFrame


def _trait_phrase(feature: str, z_score: float) -> str:
    name = feature.replace("_", " ").strip()
    lower = name.lower()
    high = z_score > 0
    if "recency" in lower:
        return "Recently active" if not high else "Lapsed"
    if any(token in lower for token in ("monetary", "spend", "revenue", "value")):
        return "High spend" if high else "Light spend"
    if any(token in lower for token in ("frequency", "orders", "purchases")):
        return "Frequent buyers" if high else "Occasional buyers"
    if "discount" in lower or "coupon" in lower:
        return "Deal-led" if high else "Full-price leaning"
    if any(token in lower for token in ("engagement", "visits", "sessions", "opens")):
        return "Highly engaged" if high else "Low engagement"
    if "return" in lower or "refund" in lower:
        return "High returns" if high else "Low returns"
    if "satisfaction" in lower or "nps" in lower:
        return "Highly satisfied" if high else "Needs attention"
    if lower == "age" or lower.endswith(" age"):
        return "Older-skewing" if high else "Younger-skewing"
    if "income" in lower:
        return "Higher income" if high else "Lower income"
    if "household" in lower or "family size" in lower:
        return "Larger households" if high else "Smaller households"
    return ("Higher " if high else "Lower ") + name


def profile_segments(
    frame: pd.DataFrame,
    segment_labels: np.ndarray,
    basis_columns: list[str],
    descriptor_columns: list[str] | None = None,
) -> ProfileResult:
    """Profile segments on both formation bases and reachability descriptors."""
    descriptors = descriptor_columns or []
    work = frame.copy()
    label_column = "__segmentsignal_label__"
    while label_column in work.columns:
        label_column = "_" + label_column
    work[label_column] = segment_labels
    ordered_segments = sorted(
        set(segment_labels.tolist()),
        key=lambda label: int(str(label).rsplit(" ", 1)[-1]) if str(label).rsplit(" ", 1)[-1].isdigit() else str(label),
    )

    counts = work[label_column].value_counts().reindex(ordered_segments)
    summary = pd.DataFrame(
        {
            "segment": counts.index,
            "customers": counts.values,
            "share_%": (100 * counts.values / len(work)).round(1),
        }
    )

    selected = list(dict.fromkeys(basis_columns + descriptors))
    numeric_columns, categorical_columns = infer_feature_types(work, selected)

    numeric_rows: list[dict[str, object]] = []
    for column in numeric_columns:
        values = pd.to_numeric(work[column], errors="coerce")
        overall_mean = float(values.mean())
        overall_std = float(values.std(ddof=0))
        for segment in ordered_segments:
            segment_values = values[work[label_column] == segment]
            mean = float(segment_values.mean())
            numeric_rows.append(
                {
                    "segment": segment,
                    "role": "basis" if column in basis_columns else "descriptor",
                    "feature": column,
                    "mean": mean,
                    "median": float(segment_values.median()),
                    "overall_mean": overall_mean,
                    "index_100": 100 * mean / overall_mean if abs(overall_mean) > 1e-12 else np.nan,
                    "z_difference": (mean - overall_mean) / overall_std if overall_std > 1e-12 else 0.0,
                }
            )
    numeric = pd.DataFrame(numeric_rows)

    categorical_rows: list[dict[str, object]] = []
    for column in categorical_columns:
        values = work[column].fillna("Missing").astype(str)
        levels = values.value_counts().head(20).index.tolist()
        for segment in ordered_segments:
            segment_values = values[work[label_column] == segment]
            if segment_values.empty:
                continue
            mode = segment_values.value_counts().index[0]
            for level in levels:
                share = float((segment_values == level).mean())
                overall_share = float((values == level).mean())
                categorical_rows.append(
                    {
                        "segment": segment,
                        "role": "basis" if column in basis_columns else "descriptor",
                        "feature": column,
                        "level": level,
                        "is_segment_mode": level == mode,
                        "segment_share_%": 100 * share,
                        "overall_share_%": 100 * overall_share,
                        "index_100": 100 * share / overall_share if overall_share else np.nan,
                    }
                )
    categorical = pd.DataFrame(categorical_rows)

    card_rows: list[dict[str, object]] = []
    for segment in ordered_segments:
        if numeric.empty:
            numeric_top = pd.DataFrame()
        else:
            numeric_top = (
                numeric[(numeric["segment"] == segment) & (numeric["role"] == "basis")]
                .assign(abs_difference=lambda data: data["z_difference"].abs())
                .loc[lambda data: np.isfinite(data["abs_difference"]) & (data["abs_difference"] >= 0.25)]
                .sort_values("abs_difference", ascending=False)
                .head(2)
            )
        if categorical.empty:
            categorical_top = pd.DataFrame()
        else:
            categorical_top = (
                categorical[(categorical["segment"] == segment) & (categorical["role"] == "basis")]
                .assign(difference_points=lambda data: data["segment_share_%"] - data["overall_share_%"])
                .loc[lambda data: np.isfinite(data["difference_points"]) & (data["difference_points"] >= 10)]
                .sort_values("difference_points", ascending=False)
                .drop_duplicates(subset=["feature"])
                .head(2)
            )

        numeric_traits = [_trait_phrase(str(row.feature), float(row.z_difference)) for row in numeric_top.itertuples()]
        numeric_details = [
                f"{row.feature.replace('_', ' ')} is {'higher' if row.z_difference > 0 else 'lower'} "
                f"than average ({abs(row.z_difference):.1f} standard deviations)"
                for row in numeric_top.itertuples()
        ]
        categorical_traits = [
            f"{str(row.feature).replace('_', ' ')}: {row.level}" for row in categorical_top.itertuples()
        ]
        categorical_details = [
            f"{row.level} {str(row.feature).replace('_', ' ')} is overrepresented "
            f"({row.segment_share_:.0f}% in this segment versus {row.overall_share_:.0f}% overall)"
            for row in categorical_top.rename(
                columns={"segment_share_%": "segment_share_", "overall_share_%": "overall_share_"}
            ).itertuples()
        ]

        if numeric_traits and categorical_traits:
            traits = [numeric_traits[0], categorical_traits[0]]
            details = [numeric_details[0], categorical_details[0]]
        elif numeric_traits:
            traits, details = numeric_traits[:2], numeric_details[:2]
        else:
            traits, details = categorical_traits[:2], categorical_details[:2]
        if traits:
            suggested_name = " · ".join(traits)
            description = "; ".join(details) + "."
        else:
            suggested_name = "Broad middle"
            description = "No single selected basis strongly distinguishes this group from the full customer base."
        card_rows.append({"segment": segment, "suggested_name": suggested_name, "profile": description})
    cards = pd.DataFrame(card_rows)
    return ProfileResult(summary=summary, numeric=numeric, categorical=categorical, cards=cards)


def build_segment_map(
    frame: pd.DataFrame,
    id_column: str,
    segment_labels: np.ndarray,
    confidence: np.ndarray,
    names: dict[str, str] | None = None,
) -> pd.DataFrame:
    """Map every customer to the chosen model segment with an uncertainty signal."""
    reserved = {"segment", "membership_confidence", "segment_name"}
    output_id_column = id_column if id_column not in reserved else f"customer_{id_column}"
    mapping = pd.DataFrame(
        {
            output_id_column: frame[id_column].values,
            "segment": segment_labels,
            "membership_confidence": np.round(confidence, 4),
        }
    )
    if names:
        mapping["segment_name"] = mapping["segment"].map(names).fillna(mapping["segment"])
    return mapping

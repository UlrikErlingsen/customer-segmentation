"""Transparent preprocessing for numeric and categorical segmentation bases."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from sklearn.impute import SimpleImputer
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from .errors import DataProblem


@dataclass(frozen=True)
class PreprocessConfig:
    """Reproducible choices applied before clustering."""

    numeric_columns: tuple[str, ...]
    categorical_columns: tuple[str, ...] = ()
    clip_outliers: bool = True
    log_skewed: bool = True
    categorical_weight: float = 1.0
    max_categories: int = 20


@dataclass
class PreparedData:
    """Model matrix plus an audit trail of transformations."""

    matrix: np.ndarray
    feature_names: list[str]
    source_columns: list[str]
    row_index: pd.Index
    warnings: list[str] = field(default_factory=list)
    audit: dict[str, object] = field(default_factory=dict)


def infer_feature_types(frame: pd.DataFrame, columns: list[str]) -> tuple[list[str], list[str]]:
    """Split selected columns into numeric and categorical inputs."""
    numeric: list[str] = []
    for column in columns:
        if pd.api.types.is_bool_dtype(frame[column]):
            continue
        if pd.api.types.is_numeric_dtype(frame[column]):
            numeric.append(column)
            continue
        original_nonmissing = frame[column].notna()
        if original_nonmissing.any():
            parsed = pd.to_numeric(frame.loc[original_nonmissing, column], errors="coerce")
            if float(parsed.notna().mean()) >= 0.90:
                numeric.append(column)
    categorical = [column for column in columns if column not in numeric]
    return numeric, categorical


def prepare_features(frame: pd.DataFrame, config: PreprocessConfig) -> PreparedData:
    """Impute, optionally tame skew/outliers, standardize, and one-hot encode."""
    selected = list(config.numeric_columns) + list(config.categorical_columns)
    if not selected:
        raise DataProblem("Choose at least one basis variable.")
    missing = [column for column in selected if column not in frame]
    if missing:
        raise DataProblem(f"These selected columns are missing: {', '.join(missing)}.")
    if len(frame) < 3:
        raise DataProblem("Too few rows remain for segmentation.")

    parts: list[np.ndarray] = []
    feature_names: list[str] = []
    warnings: list[str] = []
    audit: dict[str, object] = {"rows": len(frame), "source_features": len(selected)}

    if config.numeric_columns:
        raw_numeric = frame[list(config.numeric_columns)]
        numeric = raw_numeric.apply(pd.to_numeric, errors="coerce").replace(
            [np.inf, -np.inf], np.nan
        )
        parse_failures = {
            column: int((raw_numeric[column].notna() & numeric[column].isna()).sum())
            for column in config.numeric_columns
        }
        parse_failures = {column: count for column, count in parse_failures.items() if count}
        if parse_failures:
            warnings.append(
                "Non-numeric values were treated as missing in: "
                + ", ".join(f"{column} ({count})" for column, count in parse_failures.items())
                + "."
            )
            audit["numeric_parse_failures"] = parse_failures
        audit["preexisting_missing_values"] = int(raw_numeric.isna().sum().sum())
        missing_rates = numeric.isna().mean()
        heavy_missing = missing_rates[missing_rates > 0.4]
        if not heavy_missing.empty:
            warnings.append(
                "More than 40% of values are missing in: " + ", ".join(map(str, heavy_missing.index)) + "."
            )
        imputer = SimpleImputer(strategy="median", keep_empty_features=True)
        values = imputer.fit_transform(numeric)
        audit["numeric_imputation"] = {
            column: float(value) if np.isfinite(value) else None
            for column, value in zip(config.numeric_columns, imputer.statistics_)
        }
        constant_mask = np.nanstd(values, axis=0) < 1e-12
        if constant_mask.any():
            dropped = [column for column, is_constant in zip(config.numeric_columns, constant_mask) if is_constant]
            warnings.append("Constant numeric columns were excluded: " + ", ".join(dropped) + ".")
            audit["dropped_constant_numeric"] = dropped
            values = values[:, ~constant_mask]
            numeric_names = [column for column, is_constant in zip(config.numeric_columns, constant_mask) if not is_constant]
        else:
            numeric_names = list(config.numeric_columns)

        if values.shape[1]:
            if config.clip_outliers:
                lower = np.quantile(values, 0.01, axis=0)
                upper = np.quantile(values, 0.99, axis=0)
                values = np.clip(values, lower, upper)
                audit["outlier_clipping"] = "1st and 99th percentiles"
                audit["clipping_bounds"] = {
                    column: {"lower": float(low), "upper": float(high)}
                    for column, low, high in zip(numeric_names, lower, upper)
                }
            logged: list[str] = []
            if config.log_skewed:
                for index, column in enumerate(numeric_names):
                    series = values[:, index]
                    if np.min(series) >= 0 and pd.Series(series).skew() > 1:
                        values[:, index] = np.log1p(series)
                        logged.append(column)
            if logged:
                audit["log1p_columns"] = logged
            scaler = StandardScaler()
            values = scaler.fit_transform(values)
            audit["scaler"] = {
                column: {"mean": float(mean), "scale": float(scale)}
                for column, mean, scale in zip(numeric_names, scaler.mean_, scaler.scale_)
            }
            parts.append(values)
            feature_names.extend(numeric_names)

    if config.categorical_columns:
        categorical = frame[list(config.categorical_columns)].astype("object")
        for column in categorical.columns:
            categorical[column] = categorical[column].where(categorical[column].notna(), "Missing").astype(str)
            if categorical[column].nunique() > config.max_categories * 2:
                warnings.append(
                    f"{column} has many categories; infrequent values were grouped and the result may be harder to interpret."
                )
        categorical_parts: list[np.ndarray] = []
        dropped_categorical: list[str] = []
        categorical_encoding: dict[str, object] = {}
        for column in config.categorical_columns:
            encoder = OneHotEncoder(
                handle_unknown="ignore",
                min_frequency=max(2, int(round(len(frame) * 0.01))),
                max_categories=config.max_categories,
                sparse_output=False,
            )
            encoded = encoder.fit_transform(categorical[[column]])
            variable_mask = np.std(encoded, axis=0) > 1e-12
            if not variable_mask.any():
                dropped_categorical.append(column)
                continue
            encoded = encoded[:, variable_mask]
            encoded_names = np.asarray(encoder.get_feature_names_out([column]))[variable_mask].tolist()
            categorical_encoding[column] = {
                "observed_levels": [str(value) for value in encoder.categories_[0]],
                "model_columns": encoded_names,
                "minimum_frequency": max(2, int(round(len(frame) * 0.01))),
            }
            encoded *= config.categorical_weight
            categorical_parts.append(encoded)
            feature_names.extend(encoded_names)
        if categorical_parts:
            parts.append(np.column_stack(categorical_parts))
        if dropped_categorical:
            warnings.append(
                "Categorical columns with no usable encoded variation were excluded: "
                + ", ".join(dropped_categorical)
                + "."
            )
            audit["dropped_constant_categorical"] = dropped_categorical
        audit["categorical_encoding"] = categorical_encoding

    if not parts:
        raise DataProblem("The selected basis variables contain no usable variation.")
    matrix = np.column_stack(parts).astype(float)
    if matrix.shape[1] < 1 or not np.isfinite(matrix).all():
        raise DataProblem("The prepared feature matrix contains unusable values.")
    if matrix.shape[1] > 200:
        raise DataProblem(
            "Preparation created more than 200 model columns. Remove high-cardinality or repetitive basis variables."
        )
    if matrix.shape[1] > max(50, len(frame) // 3):
        warnings.append("There are many model columns relative to customers; simplify the basis variables if results are weak.")
    audit["model_features"] = matrix.shape[1]
    audit["missing_values_imputed"] = int(frame[selected].isna().sum().sum()) + int(
        sum(audit.get("numeric_parse_failures", {}).values())
    )
    audit["numeric_columns"] = list(config.numeric_columns)
    audit["categorical_columns"] = list(config.categorical_columns)
    audit["clip_outliers"] = config.clip_outliers
    audit["log_skewed"] = config.log_skewed
    audit["categorical_weight"] = config.categorical_weight
    audit["max_categories"] = config.max_categories
    audit["feature_names"] = feature_names
    audit["warnings"] = warnings
    return PreparedData(matrix, feature_names, selected, frame.index.copy(), warnings, audit)

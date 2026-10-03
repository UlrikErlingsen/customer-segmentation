"""Transparent preprocessing for numeric and categorical segmentation bases."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from .errors import DataProblem


@dataclass(frozen=True)
class PreprocessConfig:
    """Reproducible choices applied before clustering."""

    numeric_columns: tuple[str, ...]
    categorical_columns: tuple[str, ...] = ()
    clip_outliers: bool = True
    log_skewed: bool = True
    standardize: bool = True
    categorical_weight: float = 1.0
    max_categories: int = 20


# Above this many customers, comparison and model fitting use a seeded random sample of this size; every customer
# is still prepared with the same fitted transformations and assigned to a segment afterwards.
MODEL_SAMPLE_ROWS = 25_000
TRANSFORM_CHUNK_ROWS = 250_000


@dataclass
class FeatureTransform:
    """Fitted preparation steps that turn any rows of the customer table into model-matrix rows."""

    numeric_columns: list[str]
    medians: np.ndarray
    clip_lower: np.ndarray | None
    clip_upper: np.ndarray | None
    log_mask: np.ndarray
    scalers: list[StandardScaler] | None
    categorical: list[tuple[str, OneHotEncoder, np.ndarray, float]]

    def _numeric_block(self, frame: pd.DataFrame) -> np.ndarray:
        block = np.empty((len(frame), len(self.numeric_columns)), dtype=float)
        for index, column in enumerate(self.numeric_columns):
            values = _numeric_values(frame[column])
            values[np.isnan(values)] = self.medians[index]
            if self.clip_lower is not None and self.clip_upper is not None:
                np.clip(values, self.clip_lower[index], self.clip_upper[index], out=values)
            if self.log_mask[index]:
                values = np.log1p(values)
            if self.scalers is not None:
                values = self.scalers[index].transform(values.reshape(-1, 1))[:, 0]
            block[:, index] = values
        return block

    def transform(self, frame: pd.DataFrame) -> np.ndarray:
        """Prepare rows exactly as the fitted model rows were prepared."""
        parts: list[np.ndarray] = []
        if self.numeric_columns:
            parts.append(self._numeric_block(frame))
        for column, encoder, variable_mask, weight in self.categorical:
            encoded = encoder.transform(_categorical_values(frame[column]).to_frame()).toarray()
            parts.append(encoded[:, variable_mask] * weight)
        return np.column_stack(parts).astype(float)

    def transform_in_chunks(self, frame: pd.DataFrame, chunk_rows: int = TRANSFORM_CHUNK_ROWS):
        """Yield (start position, prepared rows) so a large table is never prepared as one dense matrix."""
        for start in range(0, len(frame), chunk_rows):
            yield start, self.transform(frame.iloc[start : start + chunk_rows])


@dataclass
class PreparedData:
    """Model matrix plus an audit trail of transformations.

    ``matrix`` holds the rows used to compare and fit models: every customer, or a seeded random sample of
    ``MODEL_SAMPLE_ROWS`` for larger tables. ``sample_positions`` gives those rows' positions in the source table
    (``None`` when every customer is in the matrix) and ``transform`` prepares any other rows the same way.
    """

    matrix: np.ndarray
    feature_names: list[str]
    source_columns: list[str]
    row_index: pd.Index
    warnings: list[str] = field(default_factory=list)
    audit: dict[str, object] = field(default_factory=dict)
    transform: FeatureTransform | None = None
    sample_positions: np.ndarray | None = None
    total_rows: int = 0


def _numeric_values(series: pd.Series) -> np.ndarray:
    values = pd.to_numeric(series, errors="coerce")
    if isinstance(values, pd.Series):
        values = values.to_numpy(dtype=float, na_value=np.nan)
    values = np.array(values, dtype=float, copy=True)
    values[~np.isfinite(values)] = np.nan
    return values


def _categorical_values(series: pd.Series) -> pd.Series:
    values = series.astype("object")
    return values.where(values.notna(), "Missing").astype(str)


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


def prepare_features(
    frame: pd.DataFrame,
    config: PreprocessConfig,
    model_rows: int | None = MODEL_SAMPLE_ROWS,
    seed: int = 42,
) -> PreparedData:
    """Impute, optionally tame skew/outliers, standardize, and one-hot encode.

    Every statistic (medians, percentile limits, skew, scaling, category levels) is fitted on all customers. When the
    table has more than ``model_rows`` customers, only a seeded random sample of that size is materialized as the
    model matrix; ``PreparedData.transform`` prepares the remaining customers identically for assignment.
    """
    selected = list(config.numeric_columns) + list(config.categorical_columns)
    if not selected:
        raise DataProblem("Choose at least one basis variable.")
    missing = [column for column in selected if column not in frame]
    if missing:
        raise DataProblem(f"These selected columns are missing: {', '.join(missing)}.")
    if len(frame) < 3:
        raise DataProblem("Too few rows remain for segmentation.")

    total_rows = len(frame)
    sample_positions: np.ndarray | None = None
    if model_rows is not None and total_rows > model_rows:
        rng = np.random.default_rng(seed)
        sample_positions = np.sort(rng.choice(total_rows, size=int(model_rows), replace=False))
    take = slice(None) if sample_positions is None else sample_positions
    model_row_count = total_rows if sample_positions is None else len(sample_positions)

    parts: list[np.ndarray] = []
    feature_names: list[str] = []
    warnings: list[str] = []
    audit: dict[str, object] = {"rows": total_rows, "source_features": len(selected)}
    numeric_names: list[str] = []
    medians = np.empty(0)
    clip_lower: np.ndarray | None = None
    clip_upper: np.ndarray | None = None
    log_mask = np.zeros(0, dtype=bool)
    scalers: list[StandardScaler] | None = None

    if config.numeric_columns:
        parse_failures: dict[str, int] = {}
        missing_rates: dict[str, float] = {}
        imputation: dict[str, float | None] = {}
        preexisting_missing = 0
        kept_columns: list[str] = []
        kept_medians: list[float] = []
        dropped: list[str] = []
        lower_bounds: list[float] = []
        upper_bounds: list[float] = []
        logged: list[str] = []
        log_flags: list[bool] = []
        fitted_scalers: list[StandardScaler] = []
        block_columns: list[np.ndarray] = []
        # One column at a time, so a large table never needs a full dense copy of every numeric basis.
        for column in config.numeric_columns:
            raw = frame[column]
            raw_missing = raw.isna().to_numpy()
            preexisting_missing += int(raw_missing.sum())
            values = _numeric_values(raw)
            missing_mask = np.isnan(values)
            failures = int((~raw_missing & missing_mask).sum())
            if failures:
                parse_failures[column] = failures
            missing_rates[column] = float(missing_mask.mean())
            # Matches SimpleImputer(strategy="median", keep_empty_features=True): all-missing columns become 0.
            median = float(np.median(values[~missing_mask])) if (~missing_mask).any() else 0.0
            imputation[column] = median
            values[missing_mask] = median
            del missing_mask, raw_missing
            if np.std(values) < 1e-12:
                dropped.append(column)
                continue
            kept_columns.append(column)
            kept_medians.append(median)
            if config.clip_outliers:
                low, high = np.quantile(values, [0.01, 0.99])
                np.clip(values, low, high, out=values)
                lower_bounds.append(float(low))
                upper_bounds.append(float(high))
            use_log = bool(config.log_skewed and np.min(values) >= 0 and pd.Series(values).skew() > 1)
            log_flags.append(use_log)
            if use_log:
                values = np.log1p(values)
                logged.append(column)
            if config.standardize:
                scaler = StandardScaler()
                values = scaler.fit_transform(values.reshape(-1, 1))[:, 0]
                fitted_scalers.append(scaler)
            block_columns.append(values[take] if sample_positions is not None else values)
            del values
        if parse_failures:
            warnings.append(
                "Non-numeric values were treated as missing in: "
                + ", ".join(f"{column} ({count})" for column, count in parse_failures.items())
                + "."
            )
            audit["numeric_parse_failures"] = parse_failures
        audit["preexisting_missing_values"] = preexisting_missing
        heavy_missing = [column for column, rate in missing_rates.items() if rate > 0.4]
        if heavy_missing:
            warnings.append("More than 40% of values are missing in: " + ", ".join(map(str, heavy_missing)) + ".")
        audit["numeric_imputation"] = imputation
        if dropped:
            warnings.append("Constant numeric columns were excluded: " + ", ".join(dropped) + ".")
            audit["dropped_constant_numeric"] = dropped

        if kept_columns:
            numeric_names = kept_columns
            medians = np.array(kept_medians)
            if config.clip_outliers:
                clip_lower, clip_upper = np.array(lower_bounds), np.array(upper_bounds)
                audit["outlier_clipping"] = "1st and 99th percentiles"
                audit["clipping_bounds"] = {
                    column: {"lower": low, "upper": high}
                    for column, low, high in zip(numeric_names, lower_bounds, upper_bounds)
                }
            log_mask = np.array(log_flags, dtype=bool)
            if logged:
                audit["log1p_columns"] = logged
            if config.standardize:
                scalers = fitted_scalers
                audit["scaler"] = {
                    column: {"mean": float(scaler.mean_[0]), "scale": float(scaler.scale_[0])}
                    for column, scaler in zip(numeric_names, fitted_scalers)
                }
            else:
                audit["scaler"] = "disabled — numeric bases kept on their original shared scale"
            parts.append(np.column_stack(block_columns) if len(block_columns) > 1 else block_columns[0][:, None])
            block_columns.clear()
            feature_names.extend(numeric_names)

    categorical_steps: list[tuple[str, OneHotEncoder, np.ndarray, float]] = []
    if config.categorical_columns:
        categorical_parts: list[np.ndarray] = []
        dropped_categorical: list[str] = []
        categorical_encoding: dict[str, object] = {}
        minimum_frequency = max(2, int(round(total_rows * 0.01)))
        for column in config.categorical_columns:
            values = _categorical_values(frame[column]).to_frame()
            if values[column].nunique() > config.max_categories * 2:
                warnings.append(
                    f"{column} has many categories; infrequent values were grouped and the result may be harder to interpret."
                )
            encoder = OneHotEncoder(
                handle_unknown="ignore",
                min_frequency=minimum_frequency,
                max_categories=config.max_categories,
                sparse_output=True,
            )
            encoded_all = encoder.fit_transform(values).tocsr()
            del values
            # A one-hot column varies exactly when its level is neither absent nor present for every customer.
            counts = np.asarray(encoded_all.sum(axis=0)).ravel()
            variable_mask = (counts > 0) & (counts < total_rows)
            if not variable_mask.any():
                dropped_categorical.append(column)
                continue
            encoded = (encoded_all[take] if sample_positions is not None else encoded_all).toarray()
            del encoded_all
            encoded = encoded[:, variable_mask]
            encoded_names = np.asarray(encoder.get_feature_names_out([column]))[variable_mask].tolist()
            categorical_encoding[column] = {
                "observed_levels": [str(value) for value in encoder.categories_[0]],
                "model_columns": encoded_names,
                "minimum_frequency": minimum_frequency,
            }
            encoded *= config.categorical_weight
            categorical_parts.append(encoded)
            categorical_steps.append((column, encoder, variable_mask, config.categorical_weight))
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
    if matrix.shape[1] > max(50, total_rows // 3):
        warnings.append("There are many model columns relative to customers; simplify the basis variables if results are weak.")
    if sample_positions is not None:
        audit["model_sample"] = {
            "customers": total_rows,
            "model_rows": model_row_count,
            "random_seed": int(seed),
            "note": model_sample_note(total_rows, model_row_count),
        }
    audit["model_features"] = matrix.shape[1]
    audit["missing_values_imputed"] = int(frame[selected].isna().sum().sum()) + int(
        sum(audit.get("numeric_parse_failures", {}).values())
    )
    audit["numeric_columns"] = list(config.numeric_columns)
    audit["categorical_columns"] = list(config.categorical_columns)
    audit["clip_outliers"] = config.clip_outliers
    audit["log_skewed"] = config.log_skewed
    audit["standardize"] = config.standardize
    audit["categorical_weight"] = config.categorical_weight
    audit["max_categories"] = config.max_categories
    audit["feature_names"] = feature_names
    audit["warnings"] = warnings
    transform = FeatureTransform(
        numeric_columns=numeric_names,
        medians=medians,
        clip_lower=clip_lower,
        clip_upper=clip_upper,
        log_mask=log_mask,
        scalers=scalers,
        categorical=categorical_steps,
    )
    row_index = frame.index.copy() if sample_positions is None else frame.index[sample_positions]
    return PreparedData(
        matrix, feature_names, selected, row_index, warnings, audit, transform, sample_positions, total_rows
    )


def model_sample_note(total_rows: int, model_rows: int) -> str:
    """The visible, exported explanation of the model sample used for large tables."""
    return (
        f"Preparation statistics use all {total_rows:,} customers. Candidate comparison, stability checks and the "
        f"final model fit use a seeded random sample of {model_rows:,} customers; every other customer is then "
        "assigned to the nearest segment."
    )

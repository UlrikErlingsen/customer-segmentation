"""Dataset checks and privacy-aware schema hints."""

from __future__ import annotations

import re

import numpy as np
import pandas as pd

from .errors import DataProblem


PII_PATTERNS = {
    "email": re.compile(r"(^|[_\s-])e?mail($|[_\s-])", re.I),
    "phone": re.compile(r"phone|mobile|telephone|cell", re.I),
    "name": re.compile(r"(^|[_\s-])(full_?)?name($|[_\s-])|first.?name|last.?name", re.I),
    "address": re.compile(r"address|street|postcode|zip.?code", re.I),
}
SENSITIVE_PATTERNS = re.compile(
    r"gender|sex|ethnic|race|religion|disab|health|diagnos|politic|sexual|pregnan|nationality", re.I
)
ID_PATTERNS = re.compile(r"(^id$|_id$|^id_|customer.?id|account.?id|user.?id|uuid)", re.I)
ID_NAME_HINTS = re.compile(r"customer|client|account|user|member|respondent|contact|record|code|key", re.I)
DESCRIPTOR_PATTERNS = re.compile(
    r"(^age$|birth|income|gender|sex|region|country|city|postal|postcode|zip|education|occupation|marital|household)",
    re.I,
)
BEHAVIOR_BASIS_PATTERNS = re.compile(
    r"recen|frequen|purchase|order|spend|revenue|monetary|engage|visit|session|usage|use_|needs?|benefit|"
    r"preference|satisf|loyal|discount|coupon|return|refund|attitude|importance|rating|score|value|"
    r"sensitiv|comfort|interest",
    re.I,
)
PROFILE_BASIS_PATTERNS = re.compile(
    r"age|income|region|country|city|education|occupation|household|family|lifestage|tenure|membership|"
    r"device|language|segment|tier|category|industry|size|channel|source|acquisition|media",
    re.I,
)
RAW_DATE_PATTERNS = re.compile(r"date|timestamp|datetime|created_at|updated_at", re.I)


def likely_pii_columns(frame: pd.DataFrame) -> dict[str, str]:
    """Flag likely direct identifiers using names and a small value sample."""
    flagged: dict[str, str] = {}
    for column in frame.columns:
        name = str(column)
        for kind, pattern in PII_PATTERNS.items():
            if pattern.search(name):
                flagged[name] = kind
                break
        if name in flagged:
            continue
        sample = frame[column].dropna().astype(str).head(100)
        if not sample.empty and sample.str.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$").mean() > 0.7:
            flagged[name] = "email"
    return flagged


def likely_sensitive_columns(frame: pd.DataFrame) -> list[str]:
    """Return columns whose names suggest protected or sensitive attributes."""
    return [str(column) for column in frame.columns if SENSITIVE_PATTERNS.search(str(column))]


def likely_id_columns(frame: pd.DataFrame) -> list[str]:
    """Suggest identifier columns without treating every unique numeric field as an ID."""
    named = [str(column) for column in frame.columns if ID_PATTERNS.search(str(column))]
    unique_text = [
        str(column)
        for column in frame.columns
        if frame[column].dtype == "object"
        and frame[column].nunique(dropna=True) == len(frame)
        and ID_NAME_HINTS.search(str(column))
    ]
    return list(dict.fromkeys(named + unique_text))


def default_basis_columns(frame: pd.DataFrame, id_column: str | None = None) -> list[str]:
    """Choose conservative numeric defaults, excluding likely identifiers."""
    blocked = (
        set(likely_pii_columns(frame))
        | set(likely_id_columns(frame))
        | set(likely_sensitive_columns(frame))
        | {str(column) for column in frame.columns if DESCRIPTOR_PATTERNS.search(str(column))}
        | {"demo_truth"}
    )
    if id_column:
        blocked.add(id_column)
    return [
        str(column)
        for column in frame.select_dtypes(include=[np.number, "bool"]).columns
        if str(column) not in blocked and frame[column].nunique(dropna=True) > 1
    ][:12]


def usable_basis_columns(frame: pd.DataFrame, id_column: str | None = None) -> list[str]:
    """Return non-sensitive, non-identifier columns suitable for guided clustering."""
    blocked = set(likely_pii_columns(frame)) | set(likely_sensitive_columns(frame)) | set(likely_id_columns(frame))
    blocked.add("demo_truth")
    if id_column:
        blocked.add(id_column)
    usable: list[str] = []
    for column in frame.columns:
        name = str(column)
        series = frame[column]
        unique = int(series.nunique(dropna=True))
        if name in blocked or unique <= 1 or RAW_DATE_PATTERNS.search(name):
            continue
        nonmissing = series.dropna()
        numeric_like = bool(
            len(nonmissing)
            and pd.to_numeric(nonmissing, errors="coerce").notna().mean() >= 0.90
        )
        if pd.api.types.is_numeric_dtype(series) or pd.api.types.is_bool_dtype(series) or numeric_like or unique <= 30:
            usable.append(name)
    return usable


def suggest_basis_columns(frame: pd.DataFrame, id_column: str | None, recipe: str = "auto") -> list[str]:
    """Suggest bases for behavioral, profile-only, or mixed customer tables."""
    usable = usable_basis_columns(frame, id_column)
    behavior = [column for column in usable if BEHAVIOR_BASIS_PATTERNS.search(column)]
    profile = [column for column in usable if PROFILE_BASIS_PATTERNS.search(column)]
    if recipe == "behavior":
        chosen = behavior
    elif recipe == "profile":
        chosen = profile
    elif recipe == "manual":
        chosen = []
    else:
        chosen = behavior if len(behavior) >= 2 else usable
    return chosen[:12]


def validate_customer_table(frame: pd.DataFrame, id_column: str, basis_columns: list[str]) -> None:
    """Enforce the one-row-per-customer analysis contract."""
    if id_column not in frame:
        raise DataProblem("Choose the column that uniquely identifies each customer.")
    if frame[id_column].isna().any() or frame[id_column].astype(str).str.strip().eq("").any():
        raise DataProblem("The customer ID column contains blank values. Fill or remove them before continuing.")
    if frame[id_column].duplicated().any():
        duplicates = int(frame[id_column].duplicated(keep=False).sum())
        raise DataProblem(
            f"The customer ID repeats on {duplicates} rows. If this is a transaction log, choose that data type instead."
        )
    if len(frame) < 30:
        raise DataProblem("At least 30 customers are required. More customers usually produce more stable segments.")
    if len(frame) > 25_000:
        raise DataProblem(
            "This release analyzes at most 25,000 customers at once. Use a representative sample or aggregate first."
        )
    if not basis_columns:
        raise DataProblem("Choose at least one segmentation basis variable.")
    missing = [column for column in basis_columns if column not in frame]
    if missing:
        raise DataProblem(f"These selected columns are missing: {', '.join(missing)}.")
    if len(basis_columns) > 30:
        raise DataProblem("Use at most 30 basis variables. Remove weak or repetitive measures before clustering.")
    usable = [column for column in basis_columns if frame[column].nunique(dropna=True) > 1]
    if not usable:
        raise DataProblem("The selected basis variables do not vary between customers.")


def data_quality_report(frame: pd.DataFrame) -> pd.DataFrame:
    """Create a compact column-level audit table."""
    rows: list[dict[str, object]] = []
    pii = likely_pii_columns(frame)
    sensitive = set(likely_sensitive_columns(frame))
    ids = set(likely_id_columns(frame))
    for column in frame.columns:
        series = frame[column]
        rows.append(
            {
                "column": str(column),
                "type": str(series.dtype),
                "missing_%": round(100 * float(series.isna().mean()), 1),
                "unique": int(series.nunique(dropna=True)),
                "constant": bool(series.nunique(dropna=True) <= 1),
                "privacy_note": pii.get(str(column), "sensitive" if str(column) in sensitive else ""),
                "likely_id": str(column) in ids,
            }
        )
    return pd.DataFrame(rows)

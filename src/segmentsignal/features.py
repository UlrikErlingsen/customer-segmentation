"""Feature recipes for customer-level and transaction-level data."""

from __future__ import annotations

import pandas as pd

from .errors import DataProblem


# Above this many rows, a date column is first checked on a small sample: parsing millions of values that are not
# dates falls back to slow value-by-value parsing, so the user gets a clear message instead of a long wait.
DATE_CHECK_ROWS = 100_000
DATE_SAMPLE_VALUES = 1_000


def _looks_like_dates(series: pd.Series) -> bool:
    sample = series.dropna().head(DATE_SAMPLE_VALUES)
    return bool(len(sample)) and float(pd.to_datetime(sample, errors="coerce", utc=True).notna().mean()) >= 0.5


def latest_date(series: pd.Series) -> pd.Timestamp | None:
    """The latest parseable date in a column, or None when the column does not look like dates."""
    if not _looks_like_dates(series):
        return None
    parsed = pd.to_datetime(series, errors="coerce")
    return pd.Timestamp(parsed.max()) if parsed.notna().any() else None


def build_rfm(
    frame: pd.DataFrame,
    customer_column: str,
    date_column: str,
    amount_column: str,
    order_column: str | None = None,
    reference_date: str | pd.Timestamp | None = None,
) -> pd.DataFrame:
    """Aggregate a transaction log to one row per customer with RFM features."""
    required = [customer_column, date_column, amount_column]
    if len(set(required)) != len(required):
        raise DataProblem("Customer ID, purchase date, and purchase amount must be different columns.")
    if order_column and order_column in required:
        raise DataProblem("Order ID must be different from customer ID, date, and amount.")
    missing = [column for column in required if column not in frame]
    if missing:
        raise DataProblem(f"These transaction columns are missing: {', '.join(missing)}.")

    work = frame[required + ([order_column] if order_column else [])].copy()
    if len(work) > DATE_CHECK_ROWS and not _looks_like_dates(work[date_column]):
        raise DataProblem(
            f"The purchase date column ‘{date_column}’ does not look like dates. Choose the column that holds the "
            "purchase date."
        )
    work[date_column] = pd.to_datetime(work[date_column], errors="coerce", utc=True)
    work[amount_column] = pd.to_numeric(work[amount_column], errors="coerce").replace(
        [float("inf"), float("-inf")], pd.NA
    )
    work = work.dropna(subset=[customer_column, date_column, amount_column])
    if work.empty:
        raise DataProblem("No rows contain a usable customer ID, date, and amount together.")
    latest = work[date_column].max()
    reference = pd.Timestamp(reference_date) if reference_date is not None else latest + pd.Timedelta(days=1)
    if reference.tzinfo is None:
        reference = reference.tz_localize("UTC")
    if reference < latest:
        raise DataProblem("The reference date cannot be before the latest transaction date.")

    if order_column and (
        work[order_column].isna().any() or work[order_column].astype(str).str.strip().eq("").any()
    ):
        raise DataProblem(
            "The selected order ID contains blank values. Fill them, or choose ‘count rows’ so each row is treated as an order."
        )

    # Group on integer codes (first-appearance order) rather than the raw IDs: factorizing a text ID once is far
    # cheaper than letting every aggregation hash millions of strings again.
    customer_codes, customer_values = pd.factorize(work[customer_column], sort=False)
    customer_key = pd.Series(customer_codes, index=work.index, name="__customer__")
    grouped = work.groupby(customer_key, sort=False)
    if order_column:
        order_codes, _ = pd.factorize(work[order_column], sort=False)
        order_key = pd.Series(order_codes, index=work.index, name="__order__")
        order_values = work.groupby([customer_key, order_key], sort=False)[amount_column].sum()
        order_grouped = order_values.groupby(level=0, sort=False)
        frequency = order_grouped.size()
        average_order_value = order_grouped.mean()
    else:
        frequency = grouped.size()
        average_order_value = grouped[amount_column].mean()
    latest_purchase = grouped[date_column].max().reindex(frequency.index)
    first_purchase = grouped[date_column].min().reindex(frequency.index)
    result = pd.DataFrame(
        {
            "customer_id": customer_values[frequency.index.to_numpy()],
            "recency_days": (reference - latest_purchase).dt.total_seconds().div(86400).round(2).values,
            "frequency": frequency.values,
            "monetary_value": grouped[amount_column].sum().reindex(frequency.index).values,
            "average_order_value": average_order_value.reindex(frequency.index).values,
            "customer_tenure_days": (latest_purchase - first_purchase).dt.total_seconds().div(86400).round(2).values,
        }
    )
    return result.reset_index(drop=True)

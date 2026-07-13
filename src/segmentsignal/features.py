"""Feature recipes for customer-level and transaction-level data."""

from __future__ import annotations

import pandas as pd

from .errors import DataProblem


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

    grouped = work.groupby(customer_column, dropna=False, sort=False)
    if order_column:
        orders = (
            work.groupby([customer_column, order_column], dropna=False, sort=False, as_index=False)
            .agg(order_date=(date_column, "max"), order_value=(amount_column, "sum"))
        )
        order_grouped = orders.groupby(customer_column, dropna=False, sort=False)
        frequency = order_grouped.size()
        average_order_value = order_grouped["order_value"].mean()
    else:
        frequency = grouped.size()
        average_order_value = grouped[amount_column].mean()
    result = pd.DataFrame(
        {
            "customer_id": frequency.index,
            "recency_days": (reference - grouped[date_column].max()).dt.total_seconds().div(86400).round(2).values,
            "frequency": frequency.values,
            "monetary_value": grouped[amount_column].sum().values,
            "average_order_value": average_order_value.values,
            "customer_tenure_days": (
                grouped[date_column].max() - grouped[date_column].min()
            ).dt.total_seconds().div(86400).round(2).values,
        }
    )
    return result.reset_index(drop=True)

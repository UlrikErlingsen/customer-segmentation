"""Data limits: none on your own computer, hard caps only in a public demo.

Run locally (standalone, a local Signal Hub or an internal company deployment), Segment Signal imposes no limit on
file size, rows, cells or customers; the computer's memory and processor are the limit. A public demo sets
``SIGNAL_PUBLIC=1`` and then every cap below applies, to protect a shared server. Every limit lives in this module.
"""

from __future__ import annotations

from dataclasses import dataclass
import os


@dataclass(frozen=True)
class Limits:
    """Caps in force; ``None`` means unlimited."""

    upload_bytes: int | None = None
    json_bytes: int | None = None
    expanded_workbook_bytes: int | None = None
    table_rows: int | None = None
    total_cells: int | None = None
    customers: int | None = None
    model_rows: int | None = None
    hierarchical_rows: int | None = None
    spectral_rows: int | None = None
    basis_variables: int | None = None
    model_columns: int | None = None


LOCAL = Limits()
PUBLIC_DEMO = Limits(
    upload_bytes=200 * 1024 * 1024,
    json_bytes=50 * 1024 * 1024,
    expanded_workbook_bytes=400 * 1024 * 1024,
    table_rows=1_000_000,
    total_cells=10_000_000,
    customers=25_000,
    model_rows=25_000,
    hierarchical_rows=5_000,
    spectral_rows=2_500,
    basis_variables=30,
    model_columns=200,
)
DEMO_NOTE = "This is a limit of the public demo; the downloaded app has none."


def is_public() -> bool:
    """True in a public demo (``SIGNAL_PUBLIC=1``), read at call time."""
    return os.environ.get("SIGNAL_PUBLIC") == "1"


def active() -> Limits:
    return PUBLIC_DEMO if is_public() else LOCAL


def demo_limit(message: str) -> str:
    """A capped message that says it is a demo limit and that the downloaded app has none."""
    return f"{message} {DEMO_NOTE}"

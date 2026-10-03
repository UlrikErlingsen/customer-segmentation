"""Safe tabular input and portable result exports."""

from __future__ import annotations

import csv
from dataclasses import dataclass
import hashlib
from io import BytesIO
from itertools import chain
import json
from pathlib import Path
import re
from typing import BinaryIO
import zipfile

import numpy as np
import pandas as pd

from .errors import DataProblem, out_of_memory_message
from .limits import active, demo_limit


SUPPORTED_EXTENSIONS = {".csv", ".xlsx", ".xls", ".xlsm", ".json"}
# Size, row and cell caps exist only in a public demo (SIGNAL_PUBLIC=1); see limits.py.
CSV_CHUNK_ROWS = 250_000
# Tables above this many rows are embedded in JSON exports without re-parsing (compact rather than indented).
JSON_COMPACT_ROWS = 100_000
CSV_DELIMITERS = ",;	|"
ILLEGAL_XML_CHARACTERS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


@dataclass(frozen=True)
class LoadedData:
    """One or more named tables read from a single file."""

    tables: dict[str, pd.DataFrame]
    source_name: str


def _unique_column_names(columns: list[object]) -> list[str]:
    """Trim headers and preserve every column by adding readable suffixes."""
    result: list[str] = []
    used: set[str] = set()
    for index, column in enumerate(columns):
        base = str(column).strip() or f"column_{index + 1}"
        candidate = base
        suffix = 2
        while candidate in used:
            candidate = f"{base}__{suffix}"
            suffix += 1
        used.add(candidate)
        result.append(candidate)
    return result


def _source_bytes(source: str | Path | bytes | BinaryIO) -> tuple[bytes, str]:
    if isinstance(source, (str, Path)):
        path = Path(source)
        return path.read_bytes(), path.name
    if isinstance(source, bytes):
        return source, "uploaded.csv"
    name = Path(getattr(source, "name", "uploaded.csv")).name
    if hasattr(source, "seek"):
        source.seek(0)
    return source.read(), name


def _sniff_delimiter(raw: bytes) -> str:
    """Detect the delimiter from the header line (comma, semicolon, tab or pipe), defaulting to a comma."""
    head = raw[:65536].decode("utf-8-sig", errors="replace")
    first_line = head.splitlines()[0] if head else ""
    try:
        return csv.Sniffer().sniff(first_line, delimiters=CSV_DELIMITERS).delimiter
    except csv.Error:
        return ","


def _check_table_size(limits, rows: int, cells: int, subject: str) -> None:
    if limits.table_rows is not None and rows > limits.table_rows:
        raise DataProblem(demo_limit(f"{subject} has more than {limits.table_rows:,} rows."))
    if limits.total_cells is not None and cells > limits.total_cells:
        raise DataProblem(demo_limit(f"{subject} has more than {limits.total_cells:,} cells."))


def load_data(source: str | Path | bytes | BinaryIO, name: str | None = None) -> LoadedData:
    """Load CSV, Excel, or JSON without executing user content."""
    raw, detected_name = _source_bytes(source)
    source_name = name or detected_name
    extension = Path(source_name).suffix.lower()
    if extension not in SUPPORTED_EXTENSIONS:
        allowed = ", ".join(sorted(SUPPORTED_EXTENSIONS))
        raise DataProblem(f"Please use one of these file types: {allowed}.")
    limits = active()
    if limits.upload_bytes is not None and len(raw) > limits.upload_bytes:
        raise DataProblem(
            demo_limit(f"Uploads are limited to {limits.upload_bytes // (1024 * 1024):,} MB in this demo.")
        )
    if extension == ".json" and limits.json_bytes is not None and len(raw) > limits.json_bytes:
        raise DataProblem(demo_limit(f"JSON uploads are limited to {limits.json_bytes // (1024 * 1024):,} MB."))
    if not raw:
        raise DataProblem("This file is empty.")

    try:
        if extension == ".csv":
            chunks: list[pd.DataFrame] = []
            row_count = 0
            cell_count = 0
            reader = pd.read_csv(BytesIO(raw), sep=_sniff_delimiter(raw), chunksize=CSV_CHUNK_ROWS)
            for chunk in reader:
                row_count += len(chunk)
                cell_count += int(chunk.shape[0] * chunk.shape[1])
                _check_table_size(limits, row_count, cell_count, "This CSV")
                chunks.append(chunk)
            if len(chunks) == 1:
                frame = chunks[0]
            else:
                frame = pd.concat(chunks, ignore_index=True) if chunks else pd.DataFrame()
            del chunks
            tables = {"customers": frame}
        elif extension in {".xlsx", ".xls", ".xlsm"}:
            if extension in {".xlsx", ".xlsm"} and limits.expanded_workbook_bytes is not None:
                with zipfile.ZipFile(BytesIO(raw)) as workbook:
                    uncompressed_size = sum(member.file_size for member in workbook.infolist())
                if uncompressed_size > limits.expanded_workbook_bytes:
                    raise DataProblem(
                        demo_limit(
                            f"Workbooks may expand to at most {limits.expanded_workbook_bytes // (1024 * 1024):,} MB."
                        )
                    )
            tables = pd.read_excel(BytesIO(raw), sheet_name=None)
        else:
            payload = json.loads(raw.decode("utf-8-sig"))
            if isinstance(payload, list):
                tables = {"customers": pd.DataFrame(payload)}
            elif (
                isinstance(payload, dict)
                and all(isinstance(value, list) for value in payload.values())
                and all(not value or isinstance(value[0], dict) for value in payload.values())
            ):
                tables = {str(key): pd.DataFrame(value) for key, value in payload.items()}
            else:
                tables = {"customers": pd.DataFrame(payload)}
            # Release the parsed Python objects now that the table holds the values.
            del payload
    except DataProblem:
        raise
    except MemoryError as exc:
        raise DataProblem(out_of_memory_message("this file")) from exc
    except Exception as exc:
        raise DataProblem(
            "The file could not be read. Check that it opens normally and that the first row contains column names."
        ) from exc

    clean: dict[str, pd.DataFrame] = {}
    total_cells = 0
    for table_name, frame in tables.items():
        if frame is None or (frame.empty and len(frame.columns) == 0):
            continue
        # Rename in place rather than copying: a large table must not exist twice in memory.
        copy = frame
        copy.columns = _unique_column_names(list(copy.columns))
        total_cells += int(copy.shape[0] * copy.shape[1])
        _check_table_size(limits, len(copy), total_cells, f"The table ‘{table_name}’")
        clean[str(table_name)] = copy
    if not clean:
        raise DataProblem("No usable tables were found in this file.")
    return LoadedData(tables=clean, source_name=source_name)


def dataset_fingerprint(frame: pd.DataFrame, columns: list[str]) -> str:
    """SHA-256 of the selected columns (as text) and the row index.

    Equal to ``sha256(hash_pandas_object(frame[columns].astype(str), index=True))``, but converts one column at a
    time, so millions of rows never need every selected column as Python strings at once.
    """
    from pandas.core.util.hashing import combine_hash_arrays

    column_hashes = (
        pd.util.hash_pandas_object(frame[column].astype(str), index=False).to_numpy() for column in columns
    )
    index_hash = (pd.util.hash_pandas_object(frame.index, index=False).to_numpy() for _ in [None])
    combined = combine_hash_arrays(chain(column_hashes, index_hash), len(columns) + 1)
    return hashlib.sha256(np.asarray(combined, dtype="uint64").tobytes()).hexdigest()


def safe_for_spreadsheet(frame: pd.DataFrame) -> pd.DataFrame:
    """Neutralize strings (cell values and column headers) that spreadsheet programs could interpret as formulas."""
    safe = frame.copy()

    def neutralize(value: object) -> object:
        if not isinstance(value, str):
            return value
        cleaned = ILLEGAL_XML_CHARACTERS.sub("", value)
        return "'" + cleaned if cleaned.lstrip(" \t\r\n").startswith(("=", "+", "-", "@")) else cleaned

    safe.columns = _unique_column_names([neutralize(str(column)) for column in safe.columns])
    for column in safe.columns:
        series = safe[column].astype(object) if isinstance(safe[column].dtype, pd.CategoricalDtype) else safe[column]
        safe[column] = series.map(neutralize)
    return safe


def results_to_excel(tables: dict[str, pd.DataFrame]) -> bytes:
    """Create an in-memory workbook with readable column widths."""
    output = BytesIO()
    used_names: set[str] = set()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        for raw_name, frame in tables.items():
            base = re.sub(r"[\\/*?:\[\]]", "-", str(raw_name))[:31] or "Results"
            sheet_name = base
            suffix = 2
            while sheet_name in used_names:
                tail = f"_{suffix}"
                sheet_name = base[: 31 - len(tail)] + tail
                suffix += 1
            used_names.add(sheet_name)
            safe = safe_for_spreadsheet(frame)
            safe.to_excel(writer, sheet_name=sheet_name, index=False)
            sheet = writer.sheets[sheet_name]
            sheet.freeze_panes = "A2"
            sheet.auto_filter.ref = sheet.dimensions
            for cells in sheet.columns:
                values = [len(str(cell.value)) if cell.value is not None else 0 for cell in cells[:2000]]
                sheet.column_dimensions[cells[0].column_letter].width = min(max(values, default=8) + 2, 42)
    return output.getvalue()


def results_to_json(tables: dict[str, pd.DataFrame], metadata: dict | None = None) -> bytes:
    """Export records and reproducibility metadata as UTF-8 JSON."""
    # Large tables are embedded as pandas' compact JSON text: re-parsing millions of records into Python objects
    # would need several times the export's size in memory. Every row is still exported.
    payload: dict[str, object] = {}
    compact: dict[str, str] = {}
    for name, frame in tables.items():
        if len(frame) > JSON_COMPACT_ROWS:
            marker = f"__segmentsignal_table_{len(compact)}__"
            compact[f'"{marker}"'] = frame.to_json(orient="records", date_format="iso")
            payload[name] = marker
        else:
            payload[name] = json.loads(frame.to_json(orient="records", date_format="iso"))
    if metadata:
        payload["analysis_metadata"] = metadata
    text = json.dumps(payload, indent=2, default=str, allow_nan=False)
    for marker, records in compact.items():
        text = text.replace(marker, records, 1)
    return text.encode("utf-8")

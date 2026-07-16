"""Safe tabular input and portable result exports."""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
import json
import os
from pathlib import Path
import re
from typing import BinaryIO
import zipfile

import pandas as pd

from .errors import DataProblem


SUPPORTED_EXTENSIONS = {".csv", ".xlsx", ".xls", ".xlsm", ".json"}
MAX_UPLOAD_MB = max(1, min(int(os.getenv("SEGMENTSIGNAL_MAX_UPLOAD_MB", "200")), 1000))
MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024
MAX_JSON_BYTES = 50 * 1024 * 1024
MAX_UNCOMPRESSED_EXCEL_BYTES = 400 * 1024 * 1024
MAX_TABLE_ROWS = 1_000_000
MAX_TOTAL_CELLS = 10_000_000
CSV_CHUNK_ROWS = 25_000
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


def load_data(source: str | Path | bytes | BinaryIO, name: str | None = None) -> LoadedData:
    """Load CSV, Excel, or JSON without executing user content."""
    raw, detected_name = _source_bytes(source)
    source_name = name or detected_name
    extension = Path(source_name).suffix.lower()
    if extension not in SUPPORTED_EXTENSIONS:
        allowed = ", ".join(sorted(SUPPORTED_EXTENSIONS))
        raise DataProblem(f"Please use one of these file types: {allowed}.")
    if len(raw) > MAX_UPLOAD_BYTES:
        raise DataProblem(
            f"This file is larger than the configured {MAX_UPLOAD_MB} MB limit. "
            "Reduce it to the customer and feature columns you need."
        )
    if extension == ".json" and len(raw) > MAX_JSON_BYTES:
        raise DataProblem("JSON uploads are limited to 50 MB because they must be expanded in memory before validation.")
    if not raw:
        raise DataProblem("This file is empty.")

    try:
        if extension == ".csv":
            chunks: list[pd.DataFrame] = []
            row_count = 0
            cell_count = 0
            for chunk in pd.read_csv(BytesIO(raw), sep=None, engine="python", chunksize=CSV_CHUNK_ROWS):
                row_count += len(chunk)
                cell_count += int(chunk.shape[0] * chunk.shape[1])
                if row_count > MAX_TABLE_ROWS or cell_count > MAX_TOTAL_CELLS:
                    raise DataProblem(
                        f"This CSV exceeds the safety limit of {MAX_TABLE_ROWS:,} rows or {MAX_TOTAL_CELLS:,} cells. "
                        "Aggregate the purchase log or keep fewer columns before upload."
                    )
                chunks.append(chunk)
            frame = pd.concat(chunks, ignore_index=True) if chunks else pd.DataFrame()
            tables = {"customers": frame}
        elif extension in {".xlsx", ".xls", ".xlsm"}:
            if extension in {".xlsx", ".xlsm"}:
                with zipfile.ZipFile(BytesIO(raw)) as workbook:
                    uncompressed_size = sum(member.file_size for member in workbook.infolist())
                if uncompressed_size > MAX_UNCOMPRESSED_EXCEL_BYTES:
                    raise DataProblem(
                        "This workbook expands beyond 400 MB. Keep only the sheets and columns needed for segmentation."
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
    except DataProblem:
        raise
    except Exception as exc:
        raise DataProblem(
            "The file could not be read. Check that it opens normally and that the first row contains column names."
        ) from exc

    clean: dict[str, pd.DataFrame] = {}
    total_cells = 0
    for table_name, frame in tables.items():
        if frame is None or (frame.empty and len(frame.columns) == 0):
            continue
        copy = frame.copy()
        copy.columns = _unique_column_names(list(copy.columns))
        if len(copy) > MAX_TABLE_ROWS:
            raise DataProblem(
                f"The table ‘{table_name}’ has more than {MAX_TABLE_ROWS:,} rows. Aggregate or sample it before upload."
            )
        total_cells += int(copy.shape[0] * copy.shape[1])
        if total_cells > MAX_TOTAL_CELLS:
            raise DataProblem(
                f"The workbook contains more than {MAX_TOTAL_CELLS:,} cells. Keep only the tables and columns needed."
            )
        clean[str(table_name)] = copy
    if not clean:
        raise DataProblem("No usable tables were found in this file.")
    return LoadedData(tables=clean, source_name=source_name)


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
    payload: dict[str, object] = {
        name: json.loads(frame.to_json(orient="records", date_format="iso")) for name, frame in tables.items()
    }
    if metadata:
        payload["analysis_metadata"] = metadata
    return json.dumps(payload, indent=2, default=str, allow_nan=False).encode("utf-8")

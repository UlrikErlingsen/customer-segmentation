from io import BytesIO
from pathlib import Path

import pandas as pd
import pytest

from segmentsignal.errors import DataProblem
from segmentsignal.io import load_data, results_to_excel, results_to_json, safe_for_spreadsheet
from segmentsignal.validation import likely_pii_columns, suggest_basis_columns, usable_basis_columns, validate_customer_table


def test_csv_excel_json_round_trip(tmp_path: Path):
    frame = pd.DataFrame({"customer_id": ["A", "B"], "spend": [10.0, float("nan")]})
    csv = tmp_path / "test.csv"
    frame.to_csv(csv, index=False)
    assert list(load_data(csv).tables["customers"].columns) == ["customer_id", "spend"]

    excel_bytes = results_to_excel({"Assignments": frame})
    assert excel_bytes[:2] == b"PK"
    loaded_excel = load_data(BytesIO(excel_bytes), name="result.xlsx")
    assert "Assignments" in loaded_excel.tables

    json_bytes = results_to_json({"Assignments": frame}, {"seed": 42})
    assert b'"analysis_metadata"' in json_bytes
    assert b'"seed": 42' in json_bytes

    column_json = b'{"customer_id":["A","B"],"spend":[1,2]}'
    loaded_json = load_data(column_json, name="columns.json")
    assert loaded_json.tables["customers"].shape == (2, 2)

    duplicate_headers = load_data(b"a, a,a__2\n1,2,3\n", name="duplicate.csv").tables["customers"]
    assert duplicate_headers.columns.tolist() == ["a", "a__2", "a__2__2"]


def test_file_type_and_size_are_guarded(monkeypatch):
    with pytest.raises(DataProblem, match="file types"):
        load_data(b"hello", name="unsafe.pkl")
    monkeypatch.setattr("segmentsignal.io.MAX_UPLOAD_BYTES", 8)
    with pytest.raises(DataProblem, match="configured 200 MB"):
        load_data(b"x" * 9, name="large.csv")


def test_csv_row_limit_is_enforced_while_reading_chunks(monkeypatch):
    monkeypatch.setattr("segmentsignal.io.MAX_TABLE_ROWS", 2)
    with pytest.raises(DataProblem, match="CSV exceeds"):
        load_data(b"customer_id,value\nA,1\nB,2\nC,3\n", name="too_many.csv")


def test_pii_detection_and_unique_customer_contract():
    frame = pd.DataFrame({"customer_id": ["A", "A"], "email_address": ["a@x.no", "a@x.no"], "spend": [1, 2]})
    assert likely_pii_columns(frame)["email_address"] == "email"
    with pytest.raises(DataProblem, match="repeats"):
        validate_customer_table(frame, "customer_id", ["spend"])


def test_spreadsheet_formula_strings_are_neutralized():
    frame = pd.DataFrame(
        {
            "customer_id": [" =2+2", "\t+cmd", "ordinary"],
            "category": pd.Categorical(["@sum", "safe", "-run"]),
            "value": [-2, 3, 4],
        }
    )
    safe = safe_for_spreadsheet(frame)
    assert safe["customer_id"].tolist() == ["' =2+2", "'\t+cmd", "ordinary"]
    assert safe["category"].tolist() == ["'@sum", "safe", "'-run"]
    assert safe["value"].tolist() == [-2, 3, 4]


def test_illegal_excel_control_characters_are_removed():
    safe = safe_for_spreadsheet(pd.DataFrame({"id": ["A\x00B", "normal"]}))
    assert safe["id"].tolist() == ["AB", "normal"]


def test_basis_suggestions_support_non_rfm_profile_data():
    frame = pd.DataFrame(
        {
            "customer_id": [f"C{index}" for index in range(40)],
            "age": list(range(20, 60)),
            "income_band": (["Low", "Middle", "High", "Middle"] * 10),
            "region": (["North", "South"] * 20),
            "email": [f"person{index}@example.com" for index in range(40)],
        }
    )
    assert suggest_basis_columns(frame, "customer_id", "profile") == ["age", "income_band", "region"]
    assert "email" not in usable_basis_columns(frame, "customer_id")

    survey = pd.DataFrame({"respondent_id": [f"R{i}" for i in range(40)], "survey_score": [str(i) for i in range(40)]})
    assert "survey_score" in usable_basis_columns(survey, "respondent_id")

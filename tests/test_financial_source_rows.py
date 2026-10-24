"""Complete-source contract from the October 2026 NSBU/IFRS specification."""
from io import BytesIO

import pandas as pd

from collectors.openinfo.workbooks import _parse_excel_workbook
from financial_ingestion import statements


def test_workbook_retains_every_physical_row_cell_and_literal_label():
    label = "Долгосрочная дебиторская задолженность " + "полное наименование " * 20
    rows = [["Наименование", "Код", "На начало", "На конец"],
            [label, "110", None, "—"], ["Реальный ноль", "120", 0, 0]]
    rows += [[f"Расшифровка {i}", str(1000 + i), "", "-"] for i in range(400)]
    stream = BytesIO()
    with pd.ExcelWriter(stream, engine="openpyxl") as writer:
        pd.DataFrame(rows).to_excel(writer, index=False, header=False, sheet_name="Форма №1")
    parsed = _parse_excel_workbook(stream.getvalue())
    source = parsed["sheets"][0]["source_rows"]
    assert len(source) == len(rows)
    assert source[1] == {"row": 2, "cells": [label, "110", None, "—"]}
    assert source[2]["cells"][2:] == [0, 0]
    assert source[-1]["row"] == len(rows)
    assert parsed["source_coverage"]["complete"] is True


def test_explicit_import_limits_report_incomplete_coverage():
    stream = BytesIO()
    with pd.ExcelWriter(stream, engine="openpyxl") as writer:
        pd.DataFrame([["Строка", i, 0] for i in range(30)]).to_excel(writer, index=False, header=False)
    parsed = _parse_excel_workbook(stream.getvalue(), max_rows_per_sheet=10)
    assert parsed["source_coverage"]["complete"] is False
    assert "ROW_LIMIT:Sheet1" in parsed["source_coverage"]["issues"]


def test_ifrs_dash_does_not_become_zero_or_a_calculation_input():
    pages = {1: "IFRS financial statements", 2: """Consolidated statement of profit or loss
(in thousands of UZS)
Year ended 31 December 2024       31 December 2023
Revenue                          1,000          900
Operating expenses               (500)          (400)
Profit before tax                400            300
Income tax expense               —              0
Profit for the year              400            300"""}
    current, prior = statements.proposals(pages, {"page_count": 2})
    assert statements.numeric("—") is None
    assert statements.cells("—    0", 2) == [None, "0"]
    assert current["income_reconciliation"] == {}
    assert prior["income_reconciliation"]["tax"]["raw_value"] == "0"

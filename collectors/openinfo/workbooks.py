"""Openinfo workbooks operations with explicit dependencies."""
from __future__ import annotations
from typing import Any

from io import BytesIO
import collectors.openinfo.cells as collectors_openinfo_cells
import collectors.openinfo.settings as collectors_openinfo_settings


EXCEL_FINANCIAL_KEYWORDS = (
    "выруч", "реализац", "себесто", "валов", "прибыл", "убыт", "доход", "расход",
    "актив", "капитал", "обязательств", "долг", "заем", "денеж", "дебитор", "кредитор",
    "запас", "налог", "процент", "амортиза", "дивиденд", "revenue", "sales", "profit",
    "loss", "income", "expense", "asset", "liabil", "equity", "cash", "debt", "tax",
    "daromad", "foyda", "xarajat", "aktiv", "kapital", "majburiyat", "qarz", "pul",
)


def _row_matches_financial_context(values: list[Any]) -> bool:
    text = " ".join(str(value).lower() for value in values if value not in (None, ""))
    if any(keyword in text for keyword in EXCEL_FINANCIAL_KEYWORDS):
        return True
    numeric_count = sum(1 for value in values if collectors_openinfo_cells._safe_report_number(value) is not None)
    string_count = sum(1 for value in values if isinstance(value, str) and value.strip())
    return numeric_count >= 2 and string_count >= 1


def _excel_row_label(values: list[Any]) -> str:
    parts: list[str] = []
    for value in values[:6]:
        if not isinstance(value, str):
            continue
        text = value.strip()
        if not text:
            continue
        if collectors_openinfo_cells._safe_report_number(text) is not None:
            continue
        parts.append(text)
    if parts:
        return " | ".join(parts)[:260]
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()[:260]
    return str(values[0])[:260] if values else ""


def _classify_excel_row(label: str, sheet_name: str) -> str:
    text = f"{sheet_name} {label}".lower()
    if any(token in text for token in ("финансов", "прибыл", "убыт", "доход", "расход", "income", "profit", "loss")):
        return "income_statement"
    if any(token in text for token in ("пассив", "обязатель", "капитал", "депозит", "устав", "equity", "liabil")):
        return "liabilities_equity"
    if any(token in text for token in ("актив", "касс", "цбру", "к получению", "инвести", "кредит", "лизинг", "asset")):
        return "assets"
    return "financial_row"


def _parse_excel_workbook(
    content: bytes,
    *,
    max_sheets: int = 12,
    max_rows_per_sheet: int = 360,
    max_matched_rows_per_sheet: int = 24,
) -> dict[str, Any]:
    import pandas as pd

    workbook = pd.ExcelFile(BytesIO(content))
    sheets: list[dict[str, Any]] = []
    facts_count = 0
    warnings: list[str] = []

    for sheet_name in workbook.sheet_names[:max_sheets]:
        try:
            frame = workbook.parse(sheet_name, header=None, nrows=max_rows_per_sheet)
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"{sheet_name}: {exc}")
            continue

        frame = frame.dropna(how="all").dropna(axis=1, how="all")
        matched_rows: list[dict[str, Any]] = []
        table_rows: list[dict[str, Any]] = []
        max_table_rows = max(0, min(collectors_openinfo_settings.EXCEL_MAX_TABLE_ROWS_PER_SHEET, max_rows_per_sheet))

        for index, row in frame.iterrows():
            raw_values = [collectors_openinfo_cells._compact_cell(value) for value in row.tolist()]
            values = [value for value in raw_values if value not in ("", None)]
            if not values:
                continue

            label = _excel_row_label(values)
            numeric_cells = []
            for col_index, value in enumerate(values[:18]):
                number = collectors_openinfo_cells._safe_report_number(value)
                if number is not None:
                    numeric_cells.append({"index": col_index, "value": round(number, 4)})
            numeric_values = [cell["value"] for cell in numeric_cells][:14]

            if label and numeric_cells and len(table_rows) < max_table_rows:
                table_rows.append({
                    "row": int(index) + 1,
                    "source_cells": raw_values[:18],
                    "label": label,
                    "values": values[:18],
                    "numeric_values": numeric_values,
                    "numeric_cells": numeric_cells[:14],
                    "kind": _classify_excel_row(label, str(sheet_name)),
                })

            if _row_matches_financial_context(values) and len(matched_rows) < max_matched_rows_per_sheet:
                matched_rows.append({
                    "row": int(index) + 1,
                    "label": label,
                    "values": values[:12],
                    "numeric_values": numeric_values,
                })
                facts_count += 1

        if matched_rows or table_rows:
            sheets.append({
                "sheet": str(sheet_name),
                "rows_scanned": int(len(frame)),
                "matched_rows": matched_rows,
                "table_rows": table_rows,
            })

    return {
        "parser_version": collectors_openinfo_settings.EXCEL_PARSER_VERSION,
        "sheet_count": len(workbook.sheet_names),
        "sheets_read": len(sheets),
        "facts_count": facts_count,
        "sheets": sheets,
        "warnings": warnings[:5],
    }

"""Sector inputs. Pure deterministic rules."""
from __future__ import annotations

import financial_analysis.sector_numbers as financial_analysis_sector_numbers
import re


FORM1 = {"c400": "total_assets", "c480": "total_equity", "c770": "total_liabilities",
         "c390": "current_assets", "c320": "cash", "c370": "short_term_investments",
         "c210": "receivables", "c140": "inventories", "c600": "current_liabilities",
         "c490": "long_term_liabilities", "c130": "non_current_assets", "c012": "fixed_assets", "c100": "construction_in_progress",
         "c030": "long_term_investments", "c410": "share_capital", "c420": "additional_capital",
         "c430": "reserve_capital", "c440": "treasury_shares", "c450": "retained_earnings",
         "c460": "target_receipts", "c470": "future_expense_reserves"}


FORM2 = {"c010": "revenue", "c020": "cost_of_sales", "c030": "gross_profit",
         "c040": "period_expenses", "c090": "other_operating_income", "c100": "operating_income",
         "c110": "financial_income", "c150": "fx_income", "c170": "financial_expenses",
         "c180": "interest_expenses", "c200": "fx_expenses", "c240": "profit_before_tax", "c270": "net_income"}


EXPENSE_LINES = {"c020", "c040", "c170", "c180", "c200"}


def statement_rows(sheet, form):
    rows = sheet.get("table_rows") or []
    start = next((i for i, row in enumerate(rows) if re.search(
        r"^чистая выручка от реализации|^доходы от оказания страховых услуг|^31\.\s*итого обязательств и собственного капитала",
        str(row.get("label") or ""), re.I)), None)
    if start is not None:
        bank_end = str(rows[start].get("label") or "").startswith("31.")
        boundary = start + 1 if bank_end else start
        rows = rows[boundary:] if form == "form2" else rows[:boundary]
    return [row for row in rows if not re.search(r"^(мфо|кфс|оконх|окпо|соато|период квартала|номер расчетного|присвоенные)", str(row.get("label") or ""), re.I)]


def source_line_pairs(workbook, form, known_codes=None):
    """Read explicit positions; never compress blanks or copy opening into end.

    In the parser's numeric_cells representation the original column indexes
    retain holes. The numeric_values fallback is accepted only for complete,
    unambiguous 3/5-cell exported layouts.
    """
    result = {}
    for sheet in (workbook or {}).get("sheets") or []:
        for row in statement_rows(sheet, form):
            cells = row.get("numeric_cells") or []
            raw = list(row.get("numeric_values") or [])
            if row.get("source_cells"):
                original = row["source_cells"]
                known_codes = known_codes or (set(FORM2) if form == "form2" else set(FORM1) | {"c570", "c580"})
                code_index = next((i for i, v in enumerate(original) if financial_analysis_sector_numbers.decimal(v) is not None), None)
                if code_index is not None:
                    candidate = financial_analysis_sector_numbers.decimal(original[code_index])
                    if candidate != int(candidate) or f"c{int(candidate):03d}" not in known_codes:
                        continue
                    count = 4 if form == "form2" else 2
                    raw = original[code_index:code_index + count + 1]
                    raw += [None] * (count + 1 - len(raw))
            elif cells:
                columns = [c.get("column_index", c.get("index")) for c in cells]
                if all(isinstance(c, int) for c in columns):
                    cell_map = dict(zip(columns, [c.get("value") for c in cells]))
                    raw = [cell_map.get(c) for c in range(min(columns), max(columns) + 1)]
            if len(raw) not in (3, 5):
                continue
            code_number = financial_analysis_sector_numbers.decimal(raw[0])
            if code_number is None or code_number != int(code_number) or not 0 < code_number < 2000:
                continue
            code = f"c{int(code_number):03d}"
            if len(raw) == 3:
                previous, current = financial_analysis_sector_numbers.decimal(raw[1]), financial_analysis_sector_numbers.decimal(raw[2])
            elif form == "form2":
                # Crossed-out cells are structurally inapplicable; a blank
                # amount cell remains missing. Only explicit X is a zero side.
                pair = lambda a, b: financial_analysis_sector_numbers.difference(0 if str(a).strip().lower() in {"x", "х"} else a,
                                                0 if str(b).strip().lower() in {"x", "х"} else b)
                previous, current = pair(raw[1], raw[2]), pair(raw[3], raw[4])
                if code in EXPENSE_LINES:
                    previous = abs(previous) if previous is not None else None
                    current = abs(current) if current is not None else None
            else:
                continue
            if code in result:
                # A duplicated code in another statement cannot overwrite one.
                if result[code]["current"] != financial_analysis_sector_numbers.number(current):
                    result[code]["conflict"] = True
                continue
            result[code] = {"current": financial_analysis_sector_numbers.number(current), "previous": financial_analysis_sector_numbers.number(previous),
                            "raw_current": str(current) if current is not None else None,
                            "raw_previous": str(previous) if previous is not None else None,
                            "source_line_id": f"{form}:{code}", "label": row.get("label"),
                            "source_url": workbook.get("source_url"),
                            "sheet": sheet.get("sheet", sheet.get("name")), "row": row.get("row", row.get("row_index"))}
    return result


def prepare_inputs(snapshot, workbook=None):
    """Add exact form lines without changing the independent comparison API."""
    values = dict(snapshot.get("current_values") or {})
    previous = dict(snapshot.get("previous_values") or {})
    opening = dict(snapshot.get("opening_values") or {})
    lines = dict(snapshot.get("source_lines") or {})
    reviewed = {str(field) for field in snapshot.get("reviewed_correction_fields") or []}
    org = snapshot.get("organization_type")
    if workbook and org == "non_financial" and not snapshot.get("control_lines_prepared"):
        for form, table in (("form1", workbook.get("balance")), ("form2", workbook.get("income"))):
            lines.update({f"{form}:{key}": row for key, row in source_line_pairs(table, form).items()})
    for form, mapping in (("form1", FORM1), ("form2", FORM2)):
        for code, key in mapping.items():
            row = lines.get(f"{form}:{code}")
            if row is not None and org == "non_financial":
                # A confirmed catalogue correction is the authority over the
                # parsed workbook line.  Without this guard the analysis
                # recheck would see the original bad number and reject a
                # correction that the public financial data already uses.
                if key not in reviewed:
                    values[key] = row.get("raw_current", row.get("current"))
                if form == "form1" or key not in reviewed:
                    (opening if form == "form1" else previous)[key] = row.get("raw_previous", row.get("previous"))
    return values, previous, opening, lines

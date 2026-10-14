"""Sector inputs. Pure deterministic rules."""
from __future__ import annotations

from decimal import Decimal

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


def blank_column(values):
    """Whether a statement column carries no amounts.

    A column in which every mapped amount is zero, or none is filled, is how
    a filing leaves its comparison (or, after a parser miss, its current)
    column empty.  Reading it as a set of real zeros produced «снизился на
    100%» and «−100%» for whole balance sheets, so such a column is treated as
    absent and the comparison comes from the issuer's other filings.
    """
    amounts = [financial_analysis_sector_numbers.decimal(value) for value in values]
    amounts = [amount for amount in amounts if amount is not None]
    return not amounts or all(amount == 0 for amount in amounts)


def prior_column_blank(lines, form):
    mapping = FORM1 if form == "form1" else FORM2
    rows = [lines.get(f"{form}:{code}") for code in mapping]
    return blank_column(row.get("raw_previous", row.get("previous")) for row in rows if row is not None)


# A comparison column whose assets differ from equity plus liabilities by
# more than this share is not a balance sheet of one date.  On the 2026
# filings the gaps are either nil, a typo of 0.013% (TKDM, kept) or material:
# AGBA 2026Q1 0.9%, DORI 1.9%, MCBA 2026Q2 11%, BECM 2025Q3 over 100%.
COMPARISON_BALANCE_TOLERANCE = Decimal("0.005")

# Lines a template reads beyond Form №1's general set.  An exchange holds its
# trading participants' money in «Прочие кредиторские задолженности» (c760):
# URTS carries 6.83 of its 6.85 trn of liabilities there.
TEMPLATE_FORM1 = {"commodity_exchange": {"c760": "settlement_liabilities"}}


def column_unbalanced(assets, equity, liabilities):
    """Whether a comparison column's totals contradict each other materially."""
    a, e, l = (financial_analysis_sector_numbers.decimal(item) for item in (assets, equity, liabilities))
    if None in (a, e, l) or a <= 0:
        return False
    return abs(a - e - l) > a * COMPARISON_BALANCE_TOLERANCE


def prior_column_unbalanced(lines):
    rows = [lines.get(f"form1:{code}") or {} for code in ("c400", "c480", "c770")]
    return column_unbalanced(*(row.get("raw_previous", row.get("previous")) for row in rows))


EQUITY_COMPONENTS = (("share_capital", 1), ("additional_capital", 1), ("reserve_capital", 1), ("treasury_shares", -1),
                     ("retained_earnings", 1), ("target_receipts", 1), ("future_expense_reserves", 1))


def equity_components_gap(column):
    """Equity total less the sum Form №1 defines it by (стр.410+420+430−440+450+460+470)."""
    parts = [financial_analysis_sector_numbers.decimal(column.get(key)) for key, _ in EQUITY_COMPONENTS]
    total = financial_analysis_sector_numbers.decimal(column.get("total_equity"))
    if total is None or any(part is None for part in parts):
        return None
    return total - sum(part * sign for part, (_, sign) in zip(parts, EQUITY_COMPONENTS))


def sign_retained_earnings(column):
    """Read the sign of «нераспределённая прибыль (непокрытый убыток)» from line 480.

    An accumulated deficit typed without its minus (DORI 2026Q2: 17.8 bn
    where the equity total needs −17.8 bn) is the only reading under which
    the form's own sum holds; the sign is taken from that sum, never guessed.
    """
    gap = equity_components_gap(column)
    retained = financial_analysis_sector_numbers.decimal(column.get("retained_earnings"))
    if gap is None or retained is None or retained == 0 or abs(gap) <= 1:
        return
    if abs(gap + 2 * retained) <= 1:
        column["retained_earnings"] = financial_analysis_sector_numbers.number(-retained)


def prepare_inputs(snapshot, workbook=None):
    """Add exact form lines without changing the independent comparison API."""
    values = dict(snapshot.get("current_values") or {})
    previous = dict(snapshot.get("previous_values") or {})
    opening = dict(snapshot.get("opening_values") or {})
    lines = dict(snapshot.get("source_lines") or {})
    reviewed = {str(field) for field in snapshot.get("reviewed_correction_fields") or []}
    org = snapshot.get("organization_type")
    template = (snapshot.get("template_resolution") or {}).get("selected_template")
    extra = TEMPLATE_FORM1.get(template, {})
    if workbook and org == "non_financial" and not snapshot.get("control_lines_prepared"):
        for form, table in (("form1", workbook.get("balance")), ("form2", workbook.get("income"))):
            known = (set(FORM1) | {"c570", "c580"} | set(extra)) if form == "form1" else None
            lines.update({f"{form}:{key}": row for key, row in source_line_pairs(table, form, known).items()})
    for form, mapping in (("form1", {**FORM1, **extra}), ("form2", FORM2)):
        # A blank comparison column leaves the catalogue's comparison (the
        # issuer's previous filings) in place instead of replacing it by zeros;
        # so does a balance column that does not balance.
        prior_blank = prior_column_blank(lines, form) or (form == "form1" and prior_column_unbalanced(lines))
        for code, key in mapping.items():
            row = lines.get(f"{form}:{code}")
            if row is not None and org == "non_financial":
                # A confirmed catalogue correction is the authority over the
                # parsed workbook line.  Without this guard the analysis
                # recheck would see the original bad number and reject a
                # correction that the public financial data already uses.
                if key not in reviewed:
                    values[key] = row.get("raw_current", row.get("current"))
                prior = row.get("raw_previous", row.get("previous"))
                if (form == "form1" or key not in reviewed) and not prior_blank and prior is not None:
                    (opening if form == "form1" else previous)[key] = prior
    if org == "non_financial":
        for column in (values, opening):
            sign_retained_earnings(column)
    return values, previous, opening, lines

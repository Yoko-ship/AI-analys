"""Hold Form №1 subtotals to the arithmetic the form itself prints.

A commercial balance states every section total twice: once as a cell and once
as its own formula — «Текущие обязательства, всего (стр.610+630+…+760)» — and
the total is again a part of a larger one («Итого по разделу II (стр.490+600)»).
A filer who copies a closing cell from the opening column, or drops a digit,
breaks the equalities that line takes part in and no other (MIQE 2026Q2: line
600 repeats its opening 5 417 547 while 601, 610…760 and 770 − 490 all give
27 299 593), and the coefficients read off that cell are then a multiple of
the truth.  The balance identity does not see it: 400, 480 and 770 are right.

Each subtotal is therefore checked against its witnesses — the sum of its own
parts, and its value implied by every printed formula it is a part of:

* the filed cell agrees with a witness             → ``consistent`` (kept);
* it agrees with none, but two witnesses agree     → ``repaired`` (their value);
* it misses a witness by less than ``IMMATERIAL``  → ``immaterial`` (kept);
* no agreement either way                          → ``conflict`` (withheld);
* nothing to check it against                      → ``unverified`` (kept).

Formulas are parsed from the row labels, so a form version with other line
numbers carries its own arithmetic and no line number is assumed.  A breakdown
left at nought under a filled total is not a witness: an issuer who filed only
the total has skipped the detail, not contradicted it.

Measured on the 508 Form №1 workbooks the board's issuers filed for 2024–2026
(2026-10-15): of about 5 000 line-columns checked, every consistent one is
within 2 thousand UZS of a witness; 9 filings carry a line two witnesses
repair (a copied opening cell, a dropped or doubled digit, a nought total), 5
carry one nothing confirms, and one is kept as immaterial.
"""
from __future__ import annotations

from decimal import Decimal
import re

import financial_analysis.sector_numbers as financial_analysis_sector_numbers


# The lines the liquidity coefficients are built from.
LIQUIDITY_LINES = ("c140", "c210", "c320", "c390", "c600")

COLUMNS = ("current", "previous")

# Amounts are whole thousands of UZS; a total and its parts may differ by the
# rounding of each part, one unit per part at most.
PART_ROUNDING = Decimal("1")

# A filed total no two witnesses confirm, but within this share of one of
# them, is kept: the coefficients are published to two decimals, and a 0.1%
# error moves a ratio below 5 by at most half a hundredth (UZTL 2024Q3
# opening stocks: 769 007 516 filed, 769 004 516 and 769 005 516 implied).
IMMATERIAL = Decimal("0.001")

_FORMULA = re.compile(r"\(\s*стр\.?\s*([0-9\s+\-−–стр.]+?)\)", re.I)
_TERM = re.compile(r"([+\-−–]?)\s*(?:стр\.?\s*)?(\d{3})")
# Every line number a form can print, for reading the parts beside the totals.
ALL_CODES = frozenset(f"c{n:03d}" for n in range(1, 1000))


def label_formula(label):
    """``((+1, 'c610'), (+1, 'c630'), …)`` from «… (стр.610+630+…)», or None."""
    match = _FORMULA.search(str(label or ""))
    if not match:
        return None
    terms = tuple((-1 if sign in "-−–" and sign else 1, f"c{code}") for sign, code in _TERM.findall(match.group(1)))
    return terms if len(terms) >= 2 else None


def _amount(row, column):
    if row is None:
        return None
    return financial_analysis_sector_numbers.decimal(row.get(f"raw_{column}", row.get(column)))


def _sum(terms, rows, column, skip=None):
    total, filled = Decimal(0), False
    for sign, code in terms:
        if code == skip:
            continue
        value = _amount(rows.get(code), column)
        if value is None:
            return None, False
        total += sign * value
        filled = filled or value != 0
    return total, filled


def witnesses(code, rows, formulas, column):
    """Independent values of ``code`` implied by the form's printed formulas."""
    found = []
    filed = _amount(rows.get(code), column)
    own = formulas.get(code)
    if own:
        total, filled = _sum(own, rows, column)
        # A nought breakdown under a filled total is a skipped detail.
        if total is not None and (filled or not filed):
            found.append(("parts", total, len(own)))
    for parent, terms in formulas.items():
        signs = [sign for sign, part in terms if part == code]
        parent_value = _amount(rows.get(parent), column)
        # So is a nought total over filled parts (UZAL 2025Q3 leaves its
        # «Всего по активу» at 0 under two filled sections).
        if parent == code or len(signs) != 1 or not parent_value:
            continue
        others, _ = _sum(terms, rows, column, skip=code)
        if others is not None:
            found.append((parent, (parent_value - others) * signs[0], len(terms)))
    return found


def _agree(a, b, parts):
    return abs(a - b) <= PART_ROUNDING * max(parts, 1)


def _resolve(code, rows, formulas, column):
    filed = _amount(rows[code], column)
    found = witnesses(code, rows, formulas, column)
    resolution = {"filed": filed, "value": filed, "witnesses": {name: value for name, value, _ in found}}
    if not found:
        resolution["status"] = "unverified" if filed is not None else "missing"
    elif filed is not None and any(_agree(filed, value, parts) for _, value, parts in found):
        resolution["status"] = "consistent"
    else:
        agreed = next((a for i, (_, a, pa) in enumerate(found) for _, b, pb in found[i + 1:]
                       if _agree(a, b, max(pa, pb))), None)
        if agreed is not None:
            resolution.update(status="repaired", value=agreed)
        elif filed is not None and any(abs(filed - value) <= abs(value) * IMMATERIAL for _, value, _ in found):
            resolution["status"] = "immaterial"
        else:
            resolution.update(status="conflict" if filed is not None else "missing", value=None)
    return resolution


def reconcile(rows, targets=LIQUIDITY_LINES):
    """``{code: {column: resolution}}`` for each target line the form states.

    A repaired line is a part of the next one's witnesses: QZSM 2024Q1 left
    receivables (210) at nought, and only once 210 is repaired does 390 − the
    other parts confirm the stocks (140) it filed. Repairs are carried until
    none is added; a withheld line is never fed back as a number.
    """
    formulas = {code: terms for code, row in rows.items() if (terms := label_formula(row.get("label")))}
    present = [code for code in targets if code in rows]
    working, repaired = dict(rows), {}
    for _ in range(len(present) * len(COLUMNS) + 1):
        added = False
        for code in present:
            for column in COLUMNS:
                resolution = _resolve(code, working, formulas, column)
                if resolution["status"] == "repaired" and (code, column) not in repaired:
                    repaired[(code, column)] = resolution
                    working[code] = {**working[code], f"raw_{column}": str(resolution["value"])}
                    added = True
        if not added:
            break
    out = {}
    for code in present:
        for column in COLUMNS:
            final = _resolve(code, working, formulas, column)
            if (code, column) in repaired:
                # Still confirmed once every other repair is in place.
                final = ({**repaired[(code, column)], "witnesses": final["witnesses"]} if final["status"] == "consistent"
                         else {**final, "status": "conflict", "value": None})
            out.setdefault(code, {})[column] = {**final, "filed": _amount(rows[code], column)}
    return out


def apply(lines, resolutions, form="form1"):
    """Write repaired or withheld amounts into ``lines`` (``form1:cNNN`` rows).

    The filed amount stays on the row as ``filed_<column>`` with the outcome
    under ``reconciliation``, so the calculation trace shows what the form
    printed beside what was used.
    """
    changed = []
    for code, columns in resolutions.items():
        row = lines.get(f"{form}:{code}")
        if row is None:
            continue
        row = dict(row)
        touched = False
        for column, resolution in columns.items():
            if resolution["status"] not in {"repaired", "conflict"}:
                continue
            value = resolution["value"]
            row[f"filed_{column}"] = row.get(f"raw_{column}", row.get(column))
            row[f"raw_{column}"] = str(value) if value is not None else None
            row[column] = financial_analysis_sector_numbers.number(value)
            row.setdefault("reconciliation", {})[column] = {
                "status": resolution["status"],
                "witnesses": {name: str(value) for name, value in resolution["witnesses"].items()}}
            touched = True
            changed.append((code, column, resolution["status"]))
        if touched:
            lines[f"{form}:{code}"] = row
    return changed

"""Openinfo cells operations with explicit dependencies."""
from __future__ import annotations
from typing import Any

from numeric_parse import parse_decimal
import re


def _safe_float(value: Any) -> float | None:
    if value is None or value == "-":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_report_number(value: Any) -> float | None:
    """One report cell as a number, or None if the cell is not an amount.

    Delegates to the shared parser (see ``numeric_parse``): report cells group
    thousands with commas or spaces, so the old blanket ``replace(",", ".")`` read
    "1,234,567" as 1234.567 and served every derived figure ~1000x low.
    Strict about non-numeric tokens on purpose — a spreadsheet cell containing
    words is a label or a line code, and reading 180 out of "стр. 180" is the
    junk-row failure the plausibility floors exist to catch.
    """
    return parse_decimal(value, group_sep=",", strip_non_numeric=False)


def _compact_cell(value: Any) -> Any:
    if value is None:
        return ""
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:
            pass
    parsed = _safe_report_number(value)
    if parsed is not None:
        return round(parsed, 4)
    text = str(value).strip()
    return re.sub(r"\s+", " ", text)[:180]

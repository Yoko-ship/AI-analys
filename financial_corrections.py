"""Verified OpenInfo corrections for financial-organization balance sheets.

The source register is a reviewed, addressable list: one ticker, period and
field per row.  Values in the register are full UZS, while the financials
catalog stores NSBU statement amounts in thousands of UZS.  This module owns
that conversion and exposes a small read-only overlay used by every financial
read path.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from functools import lru_cache
from pathlib import Path
from typing import Any


CORRECTIONS_PATH = Path(__file__).with_name("financial-organizations-corrections-v3.csv")
EXPECTED_CORRECTION_COUNT = 457

FIELD_NAMES = {
    "Денежные средства": "cash",
    "Итого активов": "total_assets",
    "Итого обязательств": "total_liabilities",
    "Итого капитала": "total_equity",
}

_REQUIRED_COLUMNS = {
    "Тикер",
    "Период",
    "Показатель",
    "Статус",
    "Как должно быть",
    "Строка OpenInfo",
    "Ссылка OpenInfo",
}


@dataclass(frozen=True)
class FinancialCorrection:
    ticker: str
    period: str
    field: str
    value_thousands_uzs: float
    status: str
    openinfo_row: str
    source_url: str


def _parse_full_uzs(raw: Any) -> float:
    text = str(raw or "").strip().replace("−", "-")
    for separator in (" ", "\u00a0", "\u202f"):
        text = text.replace(separator, "")
    text = text.replace(",", ".")
    try:
        value = Decimal(text)
    except InvalidOperation as exc:
        raise ValueError(f"invalid full-UZS correction value: {raw!r}") from exc
    if not value.is_finite():
        raise ValueError(f"non-finite full-UZS correction value: {raw!r}")
    return float(value / Decimal(1000))


@lru_cache(maxsize=1)
def financial_corrections() -> tuple[FinancialCorrection, ...]:
    """Load and validate the bundled v3 register once per process."""
    with CORRECTIONS_PATH.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, delimiter=";")
        missing = _REQUIRED_COLUMNS - set(reader.fieldnames or ())
        if missing:
            raise ValueError(f"financial corrections register misses columns: {sorted(missing)}")

        records: list[FinancialCorrection] = []
        seen: set[tuple[str, str, str]] = set()
        for line_number, row in enumerate(reader, start=2):
            ticker = str(row.get("Тикер") or "").strip().upper()
            period = str(row.get("Период") or "").strip().upper()
            metric = str(row.get("Показатель") or "").strip()
            field = FIELD_NAMES.get(metric)
            if not ticker or not period[:4].isdigit() or len(period) != 6 or period[4] != "Q" or period[5] not in "1234":
                raise ValueError(f"invalid correction key at line {line_number}: {ticker!r} {period!r}")
            if field is None:
                raise ValueError(f"unsupported correction metric at line {line_number}: {metric!r}")
            key = (ticker, period, field)
            if key in seen:
                raise ValueError(f"duplicate financial correction at line {line_number}: {key}")
            seen.add(key)
            records.append(FinancialCorrection(
                ticker=ticker,
                period=period,
                field=field,
                value_thousands_uzs=_parse_full_uzs(row.get("Как должно быть")),
                status=str(row.get("Статус") or "").strip(),
                openinfo_row=str(row.get("Строка OpenInfo") or "").strip(),
                source_url=str(row.get("Ссылка OpenInfo") or "").strip(),
            ))

    if len(records) != EXPECTED_CORRECTION_COUNT:
        raise ValueError(
            f"financial corrections v3 has {len(records)} rows; "
            f"expected {EXPECTED_CORRECTION_COUNT}"
        )
    return tuple(records)


@lru_cache(maxsize=1)
def _correction_index() -> dict[tuple[str, str], dict[str, FinancialCorrection]]:
    index: dict[tuple[str, str], dict[str, FinancialCorrection]] = {}
    for record in financial_corrections():
        index.setdefault((record.ticker, record.period), {})[record.field] = record
    return index


def corrections_for(ticker: str, period: str) -> dict[str, FinancialCorrection]:
    """Corrections for one exact ticker/period, keyed by catalog field name."""
    key = (str(ticker or "").strip().upper(), str(period or "").strip().upper())
    return dict(_correction_index().get(key, {}))


def correction_periods_for(ticker: str) -> dict[str, dict[str, FinancialCorrection]]:
    """Every registered period for a ticker, including correction-only periods."""
    wanted = str(ticker or "").strip().upper()
    return {
        period: dict(fields)
        for (record_ticker, period), fields in _correction_index().items()
        if record_ticker == wanted
    }

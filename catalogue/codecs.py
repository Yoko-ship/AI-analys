"""Encode financial values, period companions, and balance provenance."""
from __future__ import annotations
from typing import Any

import catalogue.periods as catalogue_periods
import catalogue.settings as catalogue_settings
import json


def _financials_num(v: Any) -> float | None:
    try:
        return None if v is None else float(v)
    except (TypeError, ValueError):
        return None


def _financials_period(row: dict) -> tuple[int, int] | None:
    """(year, quarter) for an incoming row, or None if it must not be stored.

    Rejects periods that have not ended yet. This is the входная проверка the
    "2026 Q4" rows needed: QZSM and UQEQ reached the served cache labelled with a
    quarter of the current year that is still months away, because openinfo signed
    their annual reports with a future year-end and nothing downstream questioned
    it. A period is a claim about a closed accounting interval — if the interval
    is open, the row is not a report and is dropped rather than re-dated.
    """
    try:
        year = int(row.get("year") or 0)
        quarter = int(row.get("quarter") or 0)
    except (TypeError, ValueError):
        return None
    if catalogue_periods._is_future_period(year, quarter):
        catalogue_settings.logger.warning("financials: rejected %s %s Q%s — period has not ended",
                       row.get("ticker"), year, quarter)
        return None
    return year, quarter


def _decode_field_periods(raw: Any) -> dict[str, str]:
    """Parse the stored ``field_periods`` JSON, tolerating legacy NULL rows."""
    if not raw:
        return {}
    if isinstance(raw, dict):
        return {str(k): str(v) for k, v in raw.items() if v}
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    if not isinstance(parsed, dict):
        return {}
    return {str(k): str(v) for k, v in parsed.items() if v}


def _encode_field_periods(value: Any) -> str | None:
    """Serialize ``field_periods`` for storage; None when there is nothing to say."""
    decoded = _decode_field_periods(value)
    return json.dumps(decoded, ensure_ascii=False, sort_keys=True) if decoded else None


_PRIOR_KEYS = ("revenue", "gross_profit", "net_income", "operating_income")


def _decode_prior_period(raw: Any) -> dict[str, Any] | None:
    """Parse the stored comparative period, tolerating rows written before it."""
    if not raw:
        return None
    parsed = raw if isinstance(raw, dict) else None
    if parsed is None:
        try:
            parsed = json.loads(raw)
        except (TypeError, ValueError):
            return None
    if not isinstance(parsed, dict) or parsed.get("year") is None:
        return None
    out: dict[str, Any] = {"year": int(parsed["year"]), "quarter": int(parsed.get("quarter") or 0)}
    out["is_ytd"] = bool(out["quarter"])
    out["period_months"] = catalogue_periods._period_months(out["year"], out["quarter"])
    for key in _PRIOR_KEYS:
        out[key] = _financials_num(parsed.get(key))
    return out


def _encode_prior_period(value: Any) -> str | None:
    """Serialize the comparative period for storage; None when it says nothing."""
    if not isinstance(value, dict) or value.get("year") is None:
        return None
    payload = {"year": int(value["year"]), "quarter": int(value.get("quarter") or 0)}
    for key in _PRIOR_KEYS:
        payload[key] = _financials_num(value.get(key))
    if all(payload[key] is None for key in _PRIOR_KEYS):
        return None
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


_BALANCE_BASE_KEYS = ("equity_start", "equity_end", "assets_start", "assets_end")


_BALANCE_INSURANCE_KEYS = (
    # Insurance form №1 keeps technical reserves between equity and ordinary
    # liabilities.  Retaining the three disclosed amounts in the filed-balance
    # block prevents a later read path from collapsing them into either capital
    # or zero and makes the economic balance independently auditable.
    "gross_insurance_reserves", "reinsurer_share_in_reserves",
    "net_insurance_reserves", "other_liabilities",
)


_BALANCE_KEYS = _BALANCE_BASE_KEYS + _BALANCE_INSURANCE_KEYS


def _decode_balance_period(raw: Any) -> dict[str, Any] | None:
    """Parse the stored filed-balance block, tolerating rows written before it."""
    if not raw:
        return None
    parsed = raw if isinstance(raw, dict) else None
    if parsed is None:
        try:
            parsed = json.loads(raw)
        except (TypeError, ValueError):
            return None
    if not isinstance(parsed, dict):
        return None
    out = {key: _financials_num(parsed.get(key)) for key in _BALANCE_BASE_KEYS}
    for key in _BALANCE_INSURANCE_KEYS:
        value = _financials_num(parsed.get(key))
        if value is not None:
            out[key] = value
    return out if any(v is not None for v in out.values()) else None


def _encode_balance_period(value: Any) -> str | None:
    """Serialize the filed-balance block; None when it says nothing."""
    if not isinstance(value, dict):
        return None
    payload = {key: _financials_num(value.get(key)) for key in _BALANCE_BASE_KEYS}
    for key in _BALANCE_INSURANCE_KEYS:
        field_value = _financials_num(value.get(key))
        if field_value is not None:
            payload[key] = field_value
    if all(v is None for v in payload.values()):
        return None
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def _balance_total_fallback(row: dict, field: str, balance_key: str) -> float | None:
    """A pushed row's balance total, from its own field or its filed-balance block.

    The reconcile pushes carried assets/equity inside `balance` (…_end) long
    before catalog_financials had columns for them; a row that names neither
    stays None rather than inventing a figure.
    """
    v = _financials_num(row.get(field))
    if v is not None:
        return v
    balance = row.get("balance")
    return _financials_num(balance.get(balance_key)) if isinstance(balance, dict) else None

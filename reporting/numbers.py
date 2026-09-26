"""Numeric conversions for report inputs; field units remain explicit."""

from __future__ import annotations
import math


def _safe_float(value):
    if value is None:
        return None
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)):
        if isinstance(value, float) and math.isnan(value):
            return None
        return float(value)
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(parsed):
        return None
    return parsed


def _pct_from_percent(value, digits: int = 2):
    """Field already expressed in percent — parse and round only."""
    parsed = _safe_float(value)
    return None if parsed is None else round(parsed, digits)


def _pct_from_fraction(value, digits: int = 2):
    """Field expressed as a fraction (0.17) — scale to percent."""
    parsed = _safe_float(value)
    return None if parsed is None else round(parsed * 100, digits)


def _latest_item(items: list) -> dict:
    if not items:
        return {}
    for item in reversed(items):
        if isinstance(item, dict):
            return item
    return {}


def _growth_pct(current, previous):
    curr = _safe_float(current)
    prev = _safe_float(previous)
    if curr is None or prev in (None, 0):
        return None
    return round((curr - prev) / abs(prev) * 100, 2)

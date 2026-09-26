"""Sector numbers. Pure deterministic rules."""
from __future__ import annotations

from decimal import Decimal
from decimal import InvalidOperation
from decimal import localcontext
import hashlib
import json


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()


def decimal(value):
    if value is None or isinstance(value, bool):
        return None
    text = str(value).strip().replace("\u00a0", "").replace("\u202f", "").replace(" ", "")
    if not text or "#" in text or text in {"-", "—", "–"}:
        return None
    if text.startswith("(") and text.endswith(")"):
        text = "-" + text[1:-1]
    if "," in text and "." in text:
        text = text.replace(",", "") if text.rfind(".") > text.rfind(",") else text.replace(".", "").replace(",", ".")
    elif text.count(",") > 1:
        text = text.replace(",", "")
    else:
        text = text.replace(",", ".")
    try:
        number = Decimal(text)
        return number if number.is_finite() else None
    except InvalidOperation:
        return None


def number(value):
    value = decimal(value)
    return float(value) if value is not None else None


def total(*values):
    values = [decimal(v) for v in values]
    return sum(values, Decimal(0)) if values and all(v is not None for v in values) else None


def difference(current, previous):
    current, previous = decimal(current), decimal(previous)
    return current - previous if current is not None and previous is not None else None


def ratio(numerator, denominator, percent=False):
    numerator, denominator = decimal(numerator), decimal(denominator)
    if numerator is None or denominator is None or denominator <= 0:
        return None
    with localcontext() as context:
        context.prec = 38
        return numerator / denominator * (100 if percent else 1)


def change(current, previous):
    current, previous = decimal(current), decimal(previous)
    delta = difference(current, previous)
    pct = ratio(delta, abs(previous), True) if previous is not None else None
    sign_change = current is not None and previous is not None and current * previous < 0
    base_effect = previous is not None and current is not None and (previous == 0 or sign_change or (pct is not None and abs(pct) >= 500))
    return {"current": number(current), "previous": number(previous), "change_value": number(delta),
            "change_pct": number(pct), "base_effect": base_effect, "sign_change": sign_change}

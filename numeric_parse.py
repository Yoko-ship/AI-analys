"""The one numeric parser for figures scraped from Uzbek financial sources.

Every source in the pipeline (openinfo report Excel/PDF cells, uzse.uz board
HTML, openinfo JSON) publishes amounts in a mix of conventions:

    "1 234 567,89"   space-grouped, comma decimal   (Russian/Uzbek locale)
    "1,234,567.89"   comma-grouped, dot decimal     (English locale)
    "1.234.567"      dot-grouped, no decimal
    "1,5"            comma decimal, no grouping
    "(1 234)"        accounting negative
    "12,5%"          percent

Parsing these with a blanket ``replace(",", ".")`` is not a rounding error, it is
a ~1000x error: "1,234,567" becomes "1234.567", which then flows into every
served cell and multiplier (a P/E off by three orders of magnitude looks entirely
plausible on screen). This module exists so that logic lives in exactly one
place with exactly one test suite behind it — two independently-evolved copies is
how the bug survived in the openinfo path after being fixed in the uzse path.

Separator disambiguation, in order:
  1. Both separators present -> the RIGHTMOST is the decimal point, every other
     separator is grouping. Unambiguous: no locale groups with two characters.
  2. One separator appearing more than once -> grouping ("1.234.567").
  3. One separator appearing once -> grouping only for the shape
     ``<1-3 digits><sep><exactly 3 digits>``, and only for the separator the
     caller declares as its source's thousands mark (``group_sep``).

Rule 3 is the only genuinely ambiguous shape: "1,234" is 1234 under English
grouping and 1.234 under a Russian decimal comma, and nothing in the token
settles it. Callers therefore declare their source's convention instead of the
parser guessing per token. Both current callers group with commas and take the
dot as a decimal point, which is what their sources actually emit.
"""
from __future__ import annotations

import re
from typing import Any, Literal

__all__ = ["parse_decimal", "MAX_ABS"]

# Anything at or beyond this is a parse artifact, not a published figure (the
# largest real balance-sheet lines on this exchange are ~1e12 thousand UZS).
MAX_ABS = 1e30

_NON_NUMERIC = re.compile(r"[^\d.,\-]")
_NUMERIC_TOKEN = re.compile(r"^[\d.,()%+\-]*$")
_TRAILING_MINUS = re.compile(r"^(\d[\d.,]*)-$")
_DASHES = {"-", "—", "–", "‒", "―", "", "n/a", "N/A", "н/д"}

GroupSep = Literal[",", ".", ""]


def parse_decimal(
    value: Any,
    *,
    group_sep: GroupSep = ",",
    strip_non_numeric: bool = False,
    percent_strip: bool = True,
) -> float | None:
    """Parse one published amount to a float, or ``None`` if it is not a number.

    ``group_sep`` is the character this source uses as a thousands separator, and
    resolves rule 3 above. Pass ``""`` to always read a lone separator as a
    decimal point.

    ``strip_non_numeric`` drops letters and currency marks before parsing — right
    for HTML cells that carry a suffix ("1 234 UZS"), wrong for spreadsheet cells
    where a token containing words ("стр. 180") is a *label* and must not be read
    as the number 180. Default off, i.e. strict.

    ``percent_strip`` drops a trailing ``%`` and returns the bare number (12.5 for
    "12,5%") — callers store percents as published, not as fractions.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        parsed = float(value)
        return parsed if abs(parsed) < MAX_ABS else None

    text = str(value).strip()
    if not text:
        return None
    # NBSP / narrow-NBSP / thin-space grouping, then the dash family sources use
    # to mean "no value".
    text = text.replace("\xa0", " ").replace(" ", " ").replace(" ", " ")
    if text.strip() in _DASHES:
        return None
    if percent_strip:
        text = text.replace("%", "")

    if strip_non_numeric:
        text = _NON_NUMERIC.sub("", text.replace("(", "-").replace(")", ""))
    elif not _NUMERIC_TOKEN.match(text.replace(" ", "")):
        # A label, a line code with words, a date range — not an amount.
        return None

    text = text.replace(" ", "")
    negative = text.startswith("(") and text.endswith(")")
    if negative:
        text = text[1:-1]
    trailing = _TRAILING_MINUS.match(text)
    if trailing:  # "1 234-" — some exported cells put the sign last
        text = trailing.group(1)
        negative = True
    text = text.lstrip("+")
    while text.startswith("-"):
        text = text[1:]
        negative = not negative
    if not text or not any(ch.isdigit() for ch in text):
        return None
    if "-" in text:
        return None  # interior dash: a range or a code, never one amount

    cleaned = _regroup(text, group_sep)
    if cleaned is None:
        return None
    try:
        parsed = float(cleaned)
    except ValueError:
        return None
    if abs(parsed) >= MAX_ABS:
        return None
    return -parsed if negative else parsed


def _regroup(text: str, group_sep: str) -> str | None:
    """Normalize separators in a sign-free digit/separator string to ``123.45``."""
    has_comma = "," in text
    has_dot = "." in text

    if has_comma and has_dot:
        # Rule 1: the rightmost separator is the decimal point.
        split_at = max(text.rfind(","), text.rfind("."))
        head = re.sub(r"[.,]", "", text[:split_at])
        tail = re.sub(r"[.,]", "", text[split_at + 1:])
        return f"{head}.{tail}" if tail else (head or None)

    sep = "," if has_comma else "." if has_dot else ""
    if not sep:
        return text

    parts = text.split(sep)
    if len(parts) > 2:
        # Rule 2: a repeated separator is grouping.
        if all(len(p) == 3 for p in parts[1:]) and 1 <= len(parts[0]) <= 3:
            return "".join(parts)
        # Malformed grouping: fall back to reading the last separator as the
        # decimal point, so a lossy read still beats discarding the figure.
        return "".join(parts[:-1]) + "." + parts[-1]

    head, tail = parts
    if not head:  # ",5" -> 0.5
        return f"0.{tail}" if tail else None
    if not tail:  # "1234," -> 1234
        return head
    if sep == group_sep and len(tail) == 3 and len(head) <= 3:
        return head + tail  # rule 3, resolved by the caller's declared convention
    return f"{head}.{tail}"

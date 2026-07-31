"""Does the board agree with the exchange? Asked by the machine, every session.

Every time the board has disagreed with the exchange's own bulletin, the failure
had the same two properties: it produced a plausible number rather than an error,
and it was found by a human comparing two screens. The registry's week-old trade
price divides just as happily as the previous close does; a feed that carries 78
of 122 securities returns HTTP 200; a page whose markup changed parses to None and
is skipped in silence. Nothing anywhere asserted that the securities we serve are
the securities that traded, or that a row's numbers come from one session.

These are those assertions. Each one is a statement the exchange itself would
recognise, checked against data we already hold:

  * every security that traded has a quote for that session, and a board row;
  * the session turnover the exchange publishes on a security's page equals the
    sum of the executions it publishes in the trade feed — two independent
    derivations of one number, so a drift in either path shows up here;
  * a traded security's row can actually produce a change % (a price and a
    positive previous close).

They are cheap because they compare stored data, and they fail loudly: the
collector exits non-zero, which is the difference between "the board is wrong for
a week" and "Saturday's run went red".
"""
from __future__ import annotations

from typing import Any, Iterable

# The two paths to a session's turnover round differently (the page prints a
# rounded total, the feed sums exact executions), so agreement is proportional.
TOLERANCE = 0.005
ABS_TOLERANCE = 1.0


def _num(value: Any) -> float | None:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def _day(value: Any) -> str:
    """Any of the three date shapes in this pipeline as YYYYMMDD."""
    s = str(value or "").strip()
    if len(s) == 10 and s[2] == "." and s[5] == ".":
        return f"{s[6:]}{s[3:5]}{s[:2]}"
    s = s.replace("-", "")
    return s if len(s) == 8 and s.isdigit() else ""


def _agree(a: float | None, b: float | None) -> bool:
    if a is None or b is None:
        return False
    if abs(a - b) <= ABS_TOLERANCE:
        return True
    scale = max(abs(a), abs(b))
    return scale > 0 and abs(a - b) / scale <= TOLERANCE


def _check(name: str, ok: bool, detail: str, offenders: Iterable[str] = ()) -> dict[str, Any]:
    listed = sorted(offenders)
    return {"name": name, "ok": bool(ok), "detail": detail,
            "offenders": listed[:20], "offender_count": len(listed)}


def audit_session(stats: dict[str, dict], quotes: dict[str, dict], board: list[dict],
                  denylist: Iterable[str] = ()) -> dict[str, Any]:
    """Audit the latest session the execution feed knows about.

    ``stats``: per-ISIN execution statistics; ``quotes``: per-ISIN exchange quotes;
    ``board``: the merged market rows as served. Returns a verdict with one entry
    per check; ``ok`` is false when any check fails.
    """
    suppressed = {str(t).upper() for t in denylist or ()}
    day = max((str(s.get("trade_date") or "") for s in stats.values()), default="")
    traded = {
        isin.upper(): s for isin, s in stats.items()
        if day and str(s.get("trade_date") or "") == day
        and (_num(s.get("total_qty")) or 0) > 0
    }

    rows: dict[str, dict] = {}
    for row in board or []:
        isin = str(row.get("isin") or "").upper()
        if isin:
            rows.setdefault(isin, row)
    # A suppressed ticker is absent from the board on purpose; auditing it would
    # report a gap the site is choosing to have.
    expected = {isin: s for isin, s in traded.items()
                if str((rows.get(isin) or {}).get("ticker") or "").upper() not in suppressed}

    def _label(isin: str) -> str:
        return str((rows.get(isin) or quotes.get(isin) or {}).get("ticker") or isin)

    checks: list[dict[str, Any]] = []

    missing_quotes = {_label(i) for i in expected
                      if str((quotes.get(i) or {}).get("trade_date") or "") != day}
    checks.append(_check(
        "quotes_cover_the_session", not missing_quotes,
        f"{len(expected) - len(missing_quotes)}/{len(expected)} traded securities have "
        f"the exchange's quote for {day or '—'}", missing_quotes))

    missing_rows = {_label(i) for i in expected
                    if i not in rows or _day(rows[i].get("last_trade_date")) != day}
    checks.append(_check(
        "board_carries_the_session", not missing_rows,
        f"{len(expected) - len(missing_rows)}/{len(expected)} traded securities are on "
        "the board with that session's date", missing_rows))

    turnover_off, quantity_off = set(), set()
    for isin, stat in expected.items():
        quote = quotes.get(isin) or {}
        if str(quote.get("trade_date") or "") != day:
            continue  # already reported as a missing quote
        if not _agree(_num(quote.get("turnover")), _num(stat.get("total_value"))):
            turnover_off.add(_label(isin))
        if not _agree(_num(quote.get("quantity")), _num(stat.get("total_qty"))):
            quantity_off.add(_label(isin))
    checks.append(_check(
        "turnover_agrees_with_the_executions", not turnover_off,
        "the session turnover on each security's page equals the sum of its "
        "executions in the trade feed", turnover_off))
    checks.append(_check(
        "quantity_agrees_with_the_executions", not quantity_off,
        "the securities traded on each page equal the quantity summed from its "
        "executions", quantity_off))

    uncomputable = set()
    for isin in expected:
        row = rows.get(isin)
        if not row:
            continue  # already reported as a missing row
        last, close = _num(row.get("last_price")), _num(row.get("close_price"))
        if last is None or close is None or close <= 0:
            uncomputable.add(_label(isin))
    checks.append(_check(
        "every_traded_row_states_a_change", not uncomputable,
        "each traded security's row carries a price and a positive previous close, "
        "so the board can state the exchange's move", uncomputable))

    return {
        "ok": all(c["ok"] for c in checks),
        "trade_date": day or None,
        "traded": len(traded),
        "audited": len(expected),
        "quoted": sum(1 for i in expected
                      if str((quotes.get(i) or {}).get("trade_date") or "") == day),
        "on_board": sum(1 for i in expected if i in rows),
        "board_rows": len(rows),
        "checks": checks,
    }


def format_verdict(verdict: dict[str, Any]) -> str:
    """One log line per check — what a collector run prints when it disagrees."""
    lines = [f"market audit {'OK' if verdict.get('ok') else 'FAILED'} "
             f"for {verdict.get('trade_date')}: {verdict.get('audited')} traded securities, "
             f"{verdict.get('quoted')} quoted, {verdict.get('on_board')} on the board"]
    for check in verdict.get("checks") or []:
        mark = "ok  " if check.get("ok") else "FAIL"
        lines.append(f"  [{mark}] {check['name']}: {check['detail']}"
                     + (f" — {', '.join(check['offenders'])}"
                        f"{' …' if check['offender_count'] > len(check['offenders']) else ''}"
                        if check.get("offenders") else ""))
    return "\n".join(lines)

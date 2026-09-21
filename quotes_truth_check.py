"""Does the board show what the exchange shows? Measured, not asserted.

The site's quote columns have one job: report what UZSE published. This fetches
BOTH — the deployment on one side, uzse.uz's own per-security page on the other —
and compares them field by field, for every security the board serves.

uzse.uz is the authority here, not a second opinion. It is where the exchange
states the closing price, the previous close it measured the change against, the
session's quantity and turnover, and the date of the session that produced them.
If our board disagrees with that page, our board is wrong, whatever it was
computed from.

**Compare against the session the exchange calls that security's last one**, not
against the session its page happens to be showing. A page's *current* session is
empty for most securities most of the time — before the day's first execution,
and all day every day for a quiet one — and reading a quote off that empty row
produces prev == close, change 0 %, which is the exchange saying "no session" and
not "no movement". Reading it as a quote is what made the earlier version of this
script report ten disagreements that were its own artefacts. The page's daily
history prints the settled row for each of the last ~21 sessions; that row is the
comparison. Past that window the page cannot date the security at all, and
openinfo's execution archive answers instead (`--archive`).

Read-only against both.

    python quotes_truth_check.py               # every board row
    LIMIT=10 python quotes_truth_check.py      # the first ten
"""
from __future__ import annotations

import json
import os
import sys
import time

import requests

from uzse_quotes import _session, fetch_issue_detail, fetch_quote, settled_quote

APP = os.environ.get("APP_URL", "https://uzstock.uz").rstrip("/")
LIMIT = int(os.environ.get("LIMIT", "0"))
PACE = float(os.environ.get("PACE", "0.35"))
OUT = os.environ.get("OUT", "quotes_disagreements.json")

# The page prints rounded totals; the board carries what was pushed to it.
REL_TOLERANCE = 1e-6
TURNOVER_ABS_TOLERANCE = 1.0
PERCENT_TOLERANCE = 0.011


def _num(value):
    try:
        return None if value is None or value == "" else float(value)
    except (TypeError, ValueError):
        return None


def close_enough(ours, theirs, *, rel=REL_TOLERANCE, abs_tol=0.0) -> bool:
    a, b = _num(ours), _num(theirs)
    if a is None or b is None:
        return a is None and b is None
    if abs(a - b) <= abs_tol:
        return True
    scale = max(abs(a), abs(b))
    return scale == 0 or abs(a - b) / scale <= rel


def _day(value) -> str:
    """Any of the three date shapes in this pipeline as YYYYMMDD."""
    s = str(value or "").strip()
    if len(s) == 10 and s[2] == "." and s[5] == ".":
        return f"{s[6:]}{s[3:5]}{s[:2]}"
    return s.replace("-", "")


def board() -> list[dict]:
    rows: list[dict] = []
    for kind in ("stock", "bond"):
        data = requests.get(f"{APP}/api/market/stocks", params={"type": kind},
                            timeout=120).json()
        for row in data.get("stocks") or []:
            row["_market"] = "BND" if kind == "bond" else "STK"
            rows.append(row)
    return rows


def exchange_view(isin: str, market: str, session) -> dict | None:
    """What uzse.uz says about this security's latest session, settled."""
    page = fetch_quote(isin, market=market, session=session)
    if not page:
        return None
    return page if page.get("traded") and page.get("trade_date") else settled_quote(page)


def compare(row: dict, truth: dict, detail: dict) -> dict[str, dict]:
    diffs: dict[str, dict] = {}

    def check(field, ours, theirs, **kw) -> None:
        # A field the exchange does not publish for this session is not a
        # disagreement — only a different answer is.
        if theirs is None or close_enough(ours, theirs, **kw):
            return
        diffs[field] = {"ours": ours, "uzse": theirs}

    check("price", row.get("last_price") or row.get("close_price"), truth.get("close_price"))
    check("previous_close", row.get("close_price"), truth.get("prev_close"))
    check("quantity", row.get("quantity"), truth.get("quantity"))
    check("turnover", row.get("volume"), truth.get("turnover"), abs_tol=TURNOVER_ABS_TOLERANCE)
    check("shares_outstanding", row.get("shares_outstanding"), detail.get("shares_outstanding"))

    shares, price = detail.get("shares_outstanding"), truth.get("close_price")
    if shares and price:
        check("market_cap", row.get("market_cap"), shares * price, rel=1e-4)

    ours_day, their_day = _day(row.get("last_trade_date")), _day(truth.get("trade_date"))
    if their_day and ours_day and ours_day != their_day:
        diffs["trade_date"] = {"ours": row.get("last_trade_date"), "uzse": their_day}

    ours_last, ours_prev = _num(row.get("last_price")), _num(row.get("close_price"))
    ours_change = ((ours_last - ours_prev) / abs(ours_prev) * 100
                   if (ours_last is not None and ours_prev) else None)
    theirs_change = truth.get("change_percent")
    if theirs_change is not None and ours_change is not None:
        if abs(ours_change - theirs_change) > PERCENT_TOLERANCE:
            diffs["change_percent"] = {"ours": round(ours_change, 4), "uzse": theirs_change}
    return diffs


def main() -> int:
    rows = [r for r in board() if r.get("isin")]
    if LIMIT:
        rows = rows[:LIMIT]
    print(f"comparing {len(rows)} securities against uzse.uz\n")

    session = _session()
    matched = unreachable = 0
    undated: list[str] = []
    problems: list[dict] = []

    for i, row in enumerate(rows, 1):
        ticker = str(row.get("ticker") or "").upper()
        isin = str(row.get("isin") or "").upper()
        truth = exchange_view(isin, row["_market"], session)
        time.sleep(PACE)
        if truth is None:
            # Either the page could not be read, or the exchange cannot date this
            # security at all (its last trade predates the page's history).
            undated.append(ticker or isin)
            unreachable += 1
            continue
        detail = fetch_issue_detail(isin, session=session) or {}
        time.sleep(PACE)

        diffs = compare(row, truth, detail)
        if diffs:
            problems.append({"ticker": ticker, "isin": isin, "type": row.get("type"),
                             "uzse_session": truth.get("trade_date"),
                             "settled": bool(truth.get("settled")), "diffs": diffs})
        else:
            matched += 1
        if i % 20 == 0:
            print(f"  ...{i}/{len(rows)}  disagreeing so far: {len(problems)}")

    print(f"\nmatched            {matched}")
    print(f"disagreeing        {len(problems)}")
    print(f"no page / no date  {unreachable} {undated[:12]}")

    if problems:
        fields: dict[str, int] = {}
        for p in problems:
            for field in p["diffs"]:
                fields[field] = fields.get(field, 0) + 1
        print("\nfields that disagree:")
        for field, count in sorted(fields.items(), key=lambda kv: -kv[1]):
            print(f"  {field:20s} {count}")
        print("\nDISAGREEMENTS:")
        for p in sorted(problems, key=lambda p: p["ticker"]):
            detail = "; ".join(f"{f} ours={v['ours']} uzse={v['uzse']}"
                               for f, v in sorted(p["diffs"].items()))
            print(f"  {p['ticker']:9s} {p['uzse_session']} {detail}")
        with open(OUT, "w", encoding="utf-8") as fh:
            json.dump(problems, fh, ensure_ascii=False, indent=1)
        print(f"\nwritten: {OUT}")
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main())

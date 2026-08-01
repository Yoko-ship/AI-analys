"""Is the board's quote arithmetically the last session's true move?

Comparing against uzse.uz's live page fails on a non-trading day: the exchange
carries the last close forward, so its page reads prev == close, change 0 %.
That is the exchange saying "no session today", not "the price did not move" —
and a check that took it literally would report every correct row as wrong.

So this verifies the arithmetic against an INDEPENDENT source instead: the
openinfo trade archive, which lists the sessions that actually happened. For
each security:

    last_price  must equal the close of the most recent session
    close_price must equal the close of the session BEFORE it
    change %    must equal (last - prev) / prev * 100 on those two closes

That holds on any day of the week, and it is what the column claims to show.
"""
from __future__ import annotations

import json
import os
import sys
import time

import requests

from openinfo_collector import fetch_price_history

APP = os.environ.get("APP_URL", "https://ai-analys-production.up.railway.app").rstrip("/")
LIMIT = int(os.environ.get("LIMIT", "0"))
# A three-month window has fewer than two sessions for the thinnest
# securities, which made 18 of them UNVERIFIABLE rather than wrong.
# Widening it does not fix anything — it completes the measurement.
MONTHS = int(os.environ.get("MONTHS", "60"))
TOL = 1e-6


def board() -> list[dict]:
    rows: list[dict] = []
    for kind in ("stock", "bond"):
        data = requests.get(f"{APP}/api/market/stocks", params={"type": kind},
                            timeout=120).json()
        rows.extend(data.get("stocks") or [])
    return rows


def near(a, b) -> bool:
    if a is None or b is None:
        return a is None and b is None
    scale = max(abs(a), abs(b))
    return scale == 0 or abs(a - b) / scale <= TOL


def main() -> int:
    rows = [r for r in board() if r.get("isin")]
    if LIMIT:
        rows = rows[:LIMIT]
    print(f"verifying {len(rows)} securities against the openinfo trade archive\n")

    ok = price_wrong = prev_wrong = no_history = no_price = 0
    problems: list[dict] = []

    for i, row in enumerate(rows, 1):
        ticker = str(row.get("ticker") or "").upper()
        isin = str(row.get("isin") or "").upper()
        try:
            points = (fetch_price_history(isin, None, MONTHS) or {}).get("points") or []
        except Exception:
            no_history += 1
            continue
        sessions = sorted(
            [p for p in points if p.get("close") and float(p["close"]) > 0],
            key=lambda p: str(p["date"]))
        if len(sessions) < 2:
            no_history += 1
            continue
        last, prev = sessions[-1], sessions[-2]
        true_last, true_prev = float(last["close"]), float(prev["close"])
        true_change = (true_last - true_prev) / true_prev * 100.0

        ours_last = row.get("last_price")
        ours_prev = row.get("close_price")
        if ours_last is None:
            no_price += 1
            problems.append({"ticker": ticker, "issue": "board has no last price",
                             "archive_last": true_last, "archive_date": last["date"]})
            continue

        ours_change = ((ours_last - ours_prev) / ours_prev * 100.0
                       if ours_prev else None)
        last_ok, prev_ok = near(ours_last, true_last), near(ours_prev, true_prev)
        if last_ok and prev_ok:
            ok += 1
        else:
            if not last_ok:
                price_wrong += 1
            if not prev_ok:
                prev_wrong += 1
            problems.append({
                "ticker": ticker,
                "last_ours": ours_last, "last_archive": true_last,
                "prev_ours": ours_prev, "prev_archive": true_prev,
                "change_ours": None if ours_change is None else round(ours_change, 4),
                "change_archive": round(true_change, 4),
                "session": last["date"], "previous_session": prev["date"],
            })
        time.sleep(0.15)
        if i % 20 == 0:
            print(f"  ...{i}/{len(rows)}")

    total = len(rows)
    print(f"\ncorrect (price AND previous close match the archive): {ok}/{total}")
    print(f"  last price wrong        {price_wrong}")
    print(f"  previous close wrong    {prev_wrong}")
    print(f"  board has no price      {no_price}")
    print(f"  no usable archive       {no_history}")

    if problems:
        print("\nDETAIL:")
        for p in problems[:25]:
            if p.get("issue"):
                print(f"  {p['ticker']:9s} {p['issue']} (archive {p['archive_last']} "
                      f"on {p['archive_date']})")
            else:
                print(f"  {p['ticker']:9s} last {p['last_ours']} vs {p['last_archive']} | "
                      f"prev {p['prev_ours']} vs {p['prev_archive']} | "
                      f"chg {p['change_ours']} vs {p['change_archive']} "
                      f"({p['previous_session']} -> {p['session']})")
        with open("quotes_arithmetic_report.json", "w", encoding="utf-8") as fh:
            json.dump(problems, fh, ensure_ascii=False, indent=1)
    return 0 if ok == total else 1


if __name__ == "__main__":
    sys.exit(main())

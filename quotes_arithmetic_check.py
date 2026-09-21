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

A security that has NEVER TRADED has no two closes to compare, and an earlier
version of this file reported those as "no usable archive" and left it there —
which quietly counted "we did not check" as "we cannot know". It can be known:
uzse.uz publishes a standing reference price for them, and that price is exactly
what the board should show. Those securities are therefore verified on PRICE
against the exchange, and only the change % is left unverified, because for a
security that has never traded there is no change to verify.
"""
from __future__ import annotations

import json
import os
import sys
import time

import requests

from openinfo_collector import fetch_price_history
from uzse_quotes import fetch_quote

APP = os.environ.get("APP_URL", "https://uzstock.uz").rstrip("/")
LIMIT = int(os.environ.get("LIMIT", "0"))
# A three-month window has fewer than two sessions for the thinnest
# securities, which made 18 of them UNVERIFIABLE rather than wrong.
# Widening it does not fix anything — it completes the measurement.
MONTHS = int(os.environ.get("MONTHS", "60"))
TOL = 1e-6


def norm_day(value) -> str:
    """DD.MM.YYYY / YYYY-MM-DD / YYYYMMDD -> YYYYMMDD."""
    text = str(value or "").strip()
    if len(text) == 10 and text[2] == "." and text[5] == ".":
        return text[6:] + text[3:5] + text[:2]
    digits = text.replace("-", "")
    return digits if len(digits) == 8 and digits.isdigit() else ""


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
    # The session the board describes is the latest day any row reports. A
    # security traded in it only if its own trade date IS that day — the rule
    # the interface already uses to decide whether stored statistics belong
    # beside a live quote. The trade-stats feed carries the LAST KNOWN stats for
    # every security, so counting its rows says "all 108 traded", which is the
    # same mistake as reading trade_count off a board row that never has one.
    board_day = max((norm_day(r.get("last_trade_date")) for r in rows), default="")
    traded_set = {str(r.get("isin")).upper() for r in rows
                  if norm_day(r.get("last_trade_date")) == board_day and board_day}
    print(f"board session {board_day}: {len(traded_set)} of {len(rows)} traded in it")
    if LIMIT:
        rows = rows[:LIMIT]
    print(f"verifying {len(rows)} securities against the openinfo trade archive\n")

    ok = price_wrong = prev_wrong = no_history = no_price = 0
    never_traded_ok = never_traded_bad = 0
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
            # Never traded: no change to check, but the exchange still quotes a
            # price and the board must match it.
            market = "BND" if str(row.get("type") or "").lower() == "bond" else "STK"
            quote = fetch_quote(isin, market)
            time.sleep(0.25)
            theirs = (quote or {}).get("close_price")
            if theirs is None:
                no_history += 1
                continue
            if near(row.get("last_price"), theirs):
                never_traded_ok += 1
            else:
                never_traded_bad += 1
                problems.append({
                    "ticker": ticker,
                    "issue": "never traded; board price disagrees with uzse",
                    "archive_last": theirs, "archive_date": "uzse reference"})
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

        # WHICH previous close is the right one depends on whether the security
        # traded in the session the board is showing.
        #
        # It did: the exchange's previous close IS the previous session's close,
        # so both must match the archive.
        #
        # It did not: the exchange carries the close forward and reports
        # prev == close, change 0 %. Demanding that our `prev` match a session
        # three weeks ago would be demanding we disagree with the exchange. Only
        # the price is checkable, and there is no change to check — TGPG's -20 %
        # happened on 15.07 and is not news today.
        traded_now = isin in traded_set
        last_ok = near(ours_last, true_last)
        prev_ok = near(ours_prev, true_prev) if traded_now else near(ours_prev, ours_last)
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
    verified = ok + never_traded_ok
    print(f"\nVERIFIED CORRECT: {verified}/{total}")
    print(f"  traded      — price and previous close match the archive  {ok}")
    print(f"  never traded — price matches the exchange's quote         {never_traded_ok}")
    print("problems:")
    print(f"  last price wrong          {price_wrong}")
    print(f"  previous close wrong      {prev_wrong}")
    print(f"  board has no price        {no_price}")
    print(f"  never traded, disagrees   {never_traded_bad}")
    print(f"  no source at all          {no_history}")

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
    return 0 if verified == total else 1


if __name__ == "__main__":
    sys.exit(main())

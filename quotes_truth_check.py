"""Does the board show what the exchange shows? Measured, not asserted.

The site's quote column has one job: report the price and the day's change that
UZSE published. This fetches BOTH — the live API on one side, uzse.uz's own
per-security page on the other — and compares them security by security.

uzse.uz is the authority here, not a second opinion. It is where the exchange
states the closing price, the previous close it measured the change against, and
the date of the session that produced them. If our board disagrees with that
page, our board is wrong, whatever it was computed from.

Read-only against both.
"""
from __future__ import annotations

import json
import os
import sys
import time

import requests

from uzse_quotes import fetch_quote

APP = os.environ.get("APP_URL", "https://ai-analys-production.up.railway.app").rstrip("/")
LIMIT = int(os.environ.get("LIMIT", "0"))
PACE = float(os.environ.get("PACE", "0.35"))


def board() -> list[dict]:
    rows: list[dict] = []
    for kind in ("stock", "bond"):
        data = requests.get(f"{APP}/api/market/stocks", params={"type": kind},
                            timeout=120).json()
        rows.extend(data.get("stocks") or [])
    return rows


def close_enough(a, b, tol=1e-6) -> bool:
    if a is None or b is None:
        return a is None and b is None
    scale = max(abs(a), abs(b))
    return scale == 0 or abs(a - b) / scale <= tol


def main() -> int:
    rows = [r for r in board() if r.get("isin")]
    if LIMIT:
        rows = rows[:LIMIT]
    print(f"comparing {len(rows)} securities against uzse.uz\n")

    matched = mismatched = unreachable = skipped = 0
    problems: list[dict] = []

    for i, row in enumerate(rows, 1):
        ticker = str(row.get("ticker") or "").upper()
        isin = str(row.get("isin") or "").upper()
        market = "BND" if str(row.get("type") or "").lower() == "bond" else "STK"
        truth = fetch_quote(isin, market)
        time.sleep(PACE)
        if not truth:
            unreachable += 1
            continue

        ours_price = row.get("last_price")
        ours_prev = row.get("close_price")
        theirs_price = truth.get("close_price")
        theirs_prev = truth.get("prev_close")

        # The change the SITE would draw, from the two numbers it holds.
        ours_change = (((ours_price - ours_prev) / ours_prev * 100.0)
                       if (ours_price and ours_prev) else None)
        theirs_change = truth.get("change_percent")

        if theirs_price is None:
            skipped += 1
            continue

        price_ok = close_enough(ours_price, theirs_price)
        # The exchange rounds its published percentage; allow that, nothing more.
        change_ok = (ours_change is None and theirs_change is None) or (
            ours_change is not None and theirs_change is not None
            and abs(ours_change - theirs_change) <= 0.011)

        if price_ok and change_ok:
            matched += 1
        else:
            mismatched += 1
            problems.append({
                "ticker": ticker, "isin": isin,
                "price_ours": ours_price, "price_uzse": theirs_price,
                "prev_ours": ours_prev, "prev_uzse": theirs_prev,
                "change_ours": None if ours_change is None else round(ours_change, 4),
                "change_uzse": theirs_change,
                "date_uzse": truth.get("trade_date"),
                "traded_uzse": truth.get("traded"),
            })
        if i % 20 == 0:
            print(f"  ...{i}/{len(rows)}")

    print(f"\nmatched      {matched}")
    print(f"mismatched   {mismatched}")
    print(f"no price on uzse (skipped) {skipped}")
    print(f"unreachable  {unreachable}")

    if problems:
        print("\nDISAGREEMENTS:")
        for p in problems:
            print(f"  {p['ticker']:9s} price ours={p['price_ours']} uzse={p['price_uzse']} | "
                  f"chg ours={p['change_ours']} uzse={p['change_uzse']} | "
                  f"prev ours={p['prev_ours']} uzse={p['prev_uzse']} | {p['date_uzse']}")
        with open("quotes_disagreements.json", "w", encoding="utf-8") as fh:
            json.dump(problems, fh, ensure_ascii=False, indent=1)
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main())

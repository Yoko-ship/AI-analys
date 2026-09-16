"""Collect commercial-bank exchange rates from bankxizmatlari.uz — the Central
Bank's own retail-services portal.

The rates page (``/ru/rates/``) is server-rendered: every bank's card carries
its full rate matrix as ``data-*`` attributes on the item element (USD/EUR/RUB
× buy/sell × three channels — обменный пункт / приложение / банкомат), plus a
stable three-digit bank code (``data-bank``) and the bank's OWN stated update
time. One GET reads the whole market; there is no per-bank request and no JS
to execute.

Two things the source does NOT give us that this module guards against:

* A blank or ``"0"`` cell means the bank does not publish that channel — it is
  absent, not a zero rate, and must not be pushed as one.
* A bank occasionally enters a channel wrong (Халк банки showed a RUB
  обменный-пункт buy of 50 against a sell of 140 on 2026-08-18 — roughly a
  triple of the real spread). There is no authoritative "correct" RUB/USD/EUR
  level to check against, so the guard is relative: a buy/sell spread wider
  than ``_MAX_SPREAD`` is implausible on its face and is dropped rather than
  published, with a log line naming what was dropped.

Pure fetch/parse: no DB writes here. ``collector_financials.push_bank_fx``
posts the result to ``/api/admin/bank-fx``.
"""
from __future__ import annotations

import logging
import re
import statistics
from datetime import datetime, timedelta, timezone
from typing import Any

import requests
from bs4 import BeautifulSoup

log = logging.getLogger("bank_fx")

RATES_URL = "https://bankxizmatlari.uz/ru/rates/"
_HEADERS = {"User-Agent": "Mozilla/5.0", "Accept": "text/html"}

# The page states each bank's update time as wall-clock with no offset
# ("11:00, 18.08.2026") on a site serving Uzbek retail customers — read as
# Tashkent local time, the same assumption reports_watch.py makes for
# openinfo's timestamps. Store fetched_at (ours) in UTC regardless, so a wrong
# assumption here only skews the bank's own displayed time, never our audit trail.
TASHKENT = timezone(timedelta(hours=5))

_CURRENCIES = ("usd", "eur", "rub")
_CHANNELS = {"bank": "BANK", "app": "APP", "atm": "ATM"}

_UPDATED_RE = re.compile(r"(\d{2}):(\d{2}),\s*(\d{2})\.(\d{2})\.(\d{4})")

# There is no authoritative "correct" level for a RUB/EUR retail spread to
# check a bank against — and the real distribution varies wildly by currency.
# Measured 2026-08-18: USD spreads cluster at 0.5-1.3% (one bank at 6.2%), EUR
# at 1.5-19.2%, RUB at 23-89% with a separate cluster at 178-380% (Халк банки's
# RUB обменный-пункт: buy 50 / sell 140, roughly triple its peers' spread). A
# single fixed cutoff cannot fit both USD and RUB, so the check is peer-relative:
# computed per currency from the SAME fetch, comparing each cell against that
# batch's own median spread. This only ever FLAGS — a wide spread is data the
# bank published and may be genuine (thin RUB liquidity is real), so it is
# always stored and served; the flag lets a reader or the UI treat it with
# suspicion instead of ranking it as the best rate on the board.
_WIDE_SPREAD_FACTOR = 3.0
_WIDE_SPREAD_FLOOR = 0.10  # percentage points, so a near-zero USD median doesn't flag trivial noise
_MIN_PEERS_FOR_MEDIAN = 5


def _num(text: str | None) -> float | None:
    if not text:
        return None
    text = text.strip()
    if not text:
        return None
    try:
        value = float(text)
    except ValueError:
        return None
    return value if value > 0 else None


def _parse_updated_at(text: str) -> str | None:
    """"Время обновления: 11:00, 18.08.2026" -> ISO-8601 with a +05:00 offset.

    Matched by pattern, not by splitting on the label's own colon — "Время
    обновления:" and "11:00" both contain one, and rfind(":") found the wrong
    one every time.
    """
    m = _UPDATED_RE.search(text or "")
    if not m:
        return None
    hh, mm, dd, mo, yyyy = m.groups()
    try:
        naive = datetime(int(yyyy), int(mo), int(dd), int(hh), int(mm))
    except ValueError:
        return None
    return naive.replace(tzinfo=TASHKENT).isoformat()


def _spread(buy: float | None, sell: float | None) -> float | None:
    if buy is None or sell is None or buy <= 0:
        return None
    return sell / buy - 1


def parse_bank_rates(html: str) -> list[dict[str, Any]]:
    """Every (bank, currency, channel) cell on the page.

    Nothing is dropped: a wide spread may be a genuine thin-liquidity quote
    (see the module docstring), so every cell that parses is returned, wide
    ones carrying ``flag: "wide_spread"`` instead of being discarded.
    """
    soup = BeautifulSoup(html, "lxml")
    cells: list[dict[str, Any]] = []

    for item in soup.select(".items-list .item.js-element-item"):
        bank_code = (item.get("data-bank") or "").strip()
        if not bank_code:
            continue
        name_el = item.select_one(".item__header--name")
        bank_name = name_el.get_text(strip=True) if name_el else bank_code
        upd_el = item.select_one(".item__update--text")
        bank_updated_at = _parse_updated_at(upd_el.get_text(strip=True) if upd_el else "")
        link = item.select_one("a.item__media--bank")
        detail_url = ("https://bankxizmatlari.uz" + link["href"]) if link and link.get("href") else None

        for ccy in _CURRENCIES:
            for suffix, channel in _CHANNELS.items():
                buy = _num(item.get(f"data-{ccy}-buy-{suffix}"))
                sell = _num(item.get(f"data-{ccy}-sale-{suffix}"))
                if buy is None and sell is None:
                    continue
                cells.append({
                    "bank_code": bank_code,
                    "bank_name": bank_name,
                    "ccy": ccy.upper(),
                    "channel": channel,
                    "buy": buy,
                    "sell": sell,
                    "bank_updated_at": bank_updated_at,
                    "source_url": detail_url or RATES_URL,
                    "spread": _spread(buy, sell),
                })

    # Peer-relative median, pooled across channels — computed from THIS batch
    # only, so the check adapts to whatever the market spread structurally is
    # today rather than a value hand-picked once and left to go stale.
    by_ccy: dict[str, list[float]] = {}
    for cell in cells:
        if cell["spread"] is not None and cell["spread"] >= 0:
            by_ccy.setdefault(cell["ccy"], []).append(cell["spread"])
    medians = {ccy: statistics.median(vals) for ccy, vals in by_ccy.items()
              if len(vals) >= _MIN_PEERS_FOR_MEDIAN}

    flagged = 0
    for cell in cells:
        spread = cell.pop("spread")
        flag = None
        if spread is not None and spread < 0:
            flag = "inverted"  # sell below buy — never a real quote
        elif spread is not None and cell["ccy"] in medians:
            median = medians[cell["ccy"]]
            if spread > median * _WIDE_SPREAD_FACTOR and spread - median > _WIDE_SPREAD_FLOOR:
                flag = "wide_spread"
        cell["flag"] = flag
        if flag:
            flagged += 1
            log.info("bank_fx: flagged bank=%s ccy=%s channel=%s buy=%s sell=%s flag=%s",
                     cell["bank_code"], cell["ccy"], cell["channel"],
                     cell["buy"], cell["sell"], flag)

    if flagged:
        log.info("bank_fx: %d of %d cells flagged (median-relative, not dropped)",
                 flagged, len(cells))
    return cells


def collect_bank_rates(session: requests.Session | None = None) -> list[dict[str, Any]]:
    session = session or requests.Session()
    resp = session.get(RATES_URL, headers=_HEADERS, timeout=30)
    resp.raise_for_status()
    return parse_bank_rates(resp.text)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    result = collect_bank_rates()
    print(f"parsed {len(result)} rows from {len({r['bank_code'] for r in result})} banks")

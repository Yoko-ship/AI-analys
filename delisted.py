"""Securities deleted from the site — dead registry lines, not live issuers.

The Справочник's "Неактивны / возможный делистинг" tab listed 61 tickers, but that
flag is derived from one field: the openinfo RFB registry's ``last_trade_date``. It
never cross-checks the live UZSE feed, so it also caught securities that are trading
normally — ALKB and the ACMT*/BFMT*/CTFB*/UZUMS3B microfinance bonds all printed a
trade the same week they were listed as delisting candidates. Deleting the tab's
contents verbatim would have removed actively traded lines, and Uzbekneftegaz and
Olmaliq KMK with them.

This set is the part of that list that is genuinely dead:

  * issuer bond series that never had a board presence — priced at par (or not at
    all), no trade in years, and already hidden from the market view by
    ``BOARD_DENYLIST``; they survived only in the registry feed behind this tab;
  * issuers whose openinfo record carries no tradable RFB security and no
    price anywhere (MNGM, NGQT) — see also the market-gaps audit, which
    confirmed there is no source for them rather than a gap to fill. OCBK sat
    here until 2026-08-20: uzse.uz now serves a real quote page for
    UZ7048610008 (last trade 03.06.2026 at 47 000), so Octobank is back on the
    site as a live issuer.

One issuer is here for a different reason — Kapitalbank was removed because the
customer asked for it, not because the data called it dead. It is kept separate
below so nobody reads it as a data verdict and "corrects" it back.

Unlike ``BOARD_DENYLIST`` (display-only suppression) these are *purged*: removed
from the catalog DB, never re-collected, and filtered on read so a stale row cannot
resurface. ``purge_delisted()`` in ``reports_catalog`` performs the deletion and
runs on API startup, so a redeploy cleans a persisted volume with no manual step.

Extend at runtime with ``DELISTED_TICKERS_EXTRA`` (comma-separated) — same escape
hatch as ``BOARD_DENYLIST_EXTRA``.
"""
from __future__ import annotations

import os
from typing import Any

# Bond series and non-primary lines of issuers that remain listed under their own
# ordinary ticker — the issuer stays on the site, only the dead paper goes.
_DEAD_ISSUER_PAPER = {
    "SQB2", "SQB3", "SQB301", "SQB4", "SQB6", "SQB7", "SQB8",  # O'zsanoatqurilishbank
    "KPB2", "KPB3", "KPB4", "KPBA1", "KPBA10",                 # Kapitalbank (the ordinary goes too, below)
    "IPK3", "IPK4", "IPK5",                                    # Ipak Yo'li
    "IPTB2",                                                   # Ipoteka-bank
    "TRS2", "TRS201",                                          # Trastbank
    "ALK201",                                                  # Aloqabank
    "HMBK1",                                                   # Hamkorbank
    "KKB2",                                                    # Biznesni rivojlantirish banki
    "TNB101",                                                  # Turonbank
    "MCB2",                                                    # Mikrokreditbank
    "UZMB2",                                                   # O'zbekiston metallurgiya kombinati
    # O'zagrolizing (UZAL and UZALP stay). This one reached the board through the
    # registry merge, which routes by the securities catalog's `type` — and the
    # catalog had it as a share. It is not: ISIN UZ6011507AA9 is in the bond
    # namespace (all 15 bonds on the board are UZ6*, all 95 shares UZ7*), uzse
    # serves an instrument card for it only under /isu_infos/BND, and that card
    # gives par 1 000 000 with the last trade on 30.05.2023 at 1 015 000 —
    # 101.5% of par, a bond quote. Filed as equity it was valued at 50 000 shares
    # × 1 015 000, so a series that has not traded in three years sat in Прочее
    # on the heat map as a 50.75 bn block, larger than most of the real market.
    "UZAL2",
}

# Issuers with no tradable security and no price on any source we read.
_NO_SECURITY = {
    "MNGM",   # "Muborakneftgazmontaj" AJ
    "NGQT",   # "Neftgazqurilishta'mir" AJ
}

# Removed at the customer's request. Not a data verdict: KPBA is a live registry
# line — ISIN UZ7047440001, "Kapitalbank" aksiyadorlik tijorat banki, last traded
# 23.02.2024 at 1 030 — that reached the board through the inactive-registry
# merge, never through the live feed (the /stocks mirror's 78-security universe
# does not carry it). Its ISIN goes below too: purging the ticker alone is what
# turned UZAL2 into a nameless quote-cache tile, and this security is quoted the
# same way.
_REMOVED_BY_REQUEST = {
    "KPBA",   # "Kapitalbank" AJ, removed 2026-08-09
}

DELISTED_TICKERS = frozenset(
    _DEAD_ISSUER_PAPER
    | _NO_SECURITY
    | _REMOVED_BY_REQUEST
    | {t.strip().upper() for t in os.getenv("DELISTED_TICKERS_EXTRA", "").split(",") if t.strip()}
)

# The ticker is not the only key a board row arrives with. The quote cache is
# keyed by ISIN and its rows carry whatever the exchange page named them — for a
# security the /stocks mirror never listed, that is nothing at all. Such a row
# used to be deduped away by the registry line that shared its ISIN, so deleting
# the registry line is what exposed it: UZAL2 came back as a nameless tile the
# moment its ticker was purged. Anything deleted by ticker is deleted by ISIN too.
_DELISTED_ISINS = {
    "UZ6011507AA9": "UZAL2",  # O'zagrolizing bond series, last traded 30.05.2023
    "UZ7047440001": "KPBA",   # Kapitalbank ordinary, last traded 23.02.2024
}

DELISTED_ISINS = frozenset(
    set(_DELISTED_ISINS)
    | {i.strip().upper() for i in os.getenv("DELISTED_ISINS_EXTRA", "").split(",") if i.strip()}
)


def is_delisted(ticker: Any) -> bool:
    """True if ``ticker`` (any case, may be None) has been deleted from the site."""
    return str(ticker or "").strip().upper() in DELISTED_TICKERS


def is_delisted_isin(isin: Any) -> bool:
    """True if ``isin`` names a security deleted from the site.

    Kept separate from ``is_delisted`` because it answers for rows that have no
    ticker to test — the only thing they carry is the ISIN.
    """
    return str(isin or "").strip().upper() in DELISTED_ISINS

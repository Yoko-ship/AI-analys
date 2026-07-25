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
  * three issuers whose openinfo record carries no tradable RFB security and no
    price anywhere (MNGM, NGQT, OCBK) — see also the market-gaps audit, which
    confirmed there is no source for them rather than a gap to fill.

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
    "KPB2", "KPB3", "KPB4", "KPBA1", "KPBA10",                 # Kapitalbank (KPBA ordinary stays)
    "IPK3", "IPK4", "IPK5",                                    # Ipak Yo'li
    "IPTB2",                                                   # Ipoteka-bank
    "TRS2", "TRS201",                                          # Trastbank
    "ALK201",                                                  # Aloqabank
    "HMBK1",                                                   # Hamkorbank
    "KKB2",                                                    # Biznesni rivojlantirish banki
    "TNB101",                                                  # Turonbank
    "MCB2",                                                    # Mikrokreditbank
    "UZMB2",                                                   # O'zbekiston metallurgiya kombinati
}

# Issuers with no tradable security and no price on any source we read.
_NO_SECURITY = {
    "MNGM",   # "Muborakneftgazmontaj" AJ
    "NGQT",   # "Neftgazqurilishta'mir" AJ
    "OCBK",   # "Octobank" AJ
}

DELISTED_TICKERS = frozenset(
    _DEAD_ISSUER_PAPER
    | _NO_SECURITY
    | {t.strip().upper() for t in os.getenv("DELISTED_TICKERS_EXTRA", "").split(",") if t.strip()}
)


def is_delisted(ticker: Any) -> bool:
    """True if ``ticker`` (any case, may be None) has been deleted from the site."""
    return str(ticker or "").strip().upper() in DELISTED_TICKERS

"""Which kind of organization an issuer is, decided before any metric is chosen.

The catalogue sector says too little: ``finance`` holds banks, insurers, a
leasing company and the exchange, and a fund can sit under ``funds`` or under
``other``. Each kind files a different statement form — a bank has no revenue
or cost of sales, an insurer's balance is built around reserves, a fund is
described by its net assets — so every catalogue lens (financial analysis,
SWOT, conclusion, comparison, ratios) asks this module first and only then
picks the figures that kind actually files.

Evidence, strongest first: the form the filings were submitted on (openinfo
records it as ``org_type`` on the statement export), then the issuer's legal
name, then the catalogue sector. Nothing here is keyed by ticker.
"""
from __future__ import annotations

import re
import sqlite3
from typing import Any, Iterable

import catalogue.filings as catalogue_filings
import catalogue.settings as catalogue_settings
import catalogue.storage as catalogue_storage

BANK = "bank"
INSURANCE = "insurance"
FUND = "fund"
# Lenders and market infrastructure that file the commercial (jsc) form:
# leasing, microfinance, the exchange. Their figures are the commercial form's,
# but leverage is their business, so a factory's debt test does not apply.
FINANCIAL = "financial"
INDUSTRY = "industry"

KINDS = (BANK, INSURANCE, FUND, FINANCIAL, INDUSTRY)

# The statement form openinfo states for a filing → the kind it describes.
_FORM_KINDS = {
    "bank": BANK,
    "microfinance_bank": BANK,
    "microbank": BANK,
    "insurance": INSURANCE,
    "insurer": INSURANCE,
    "microfinance": FINANCIAL,
    "mfo": FINANCIAL,
    "investment_fund": FUND,
}

_ORG_TYPE_IN_URL = re.compile(r"[?&]org_type=([a-z_]+)", re.IGNORECASE)

# Legal-name evidence. Uzbek names are written with several apostrophes
# (o', o‘, o’) and Latin/Cyrillic mixes, so the patterns are deliberately loose.
_NAME_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    (FUND, re.compile(r"investi\w*\s+(fond|jamg\W?arma)|инвестиц\w*\s+фонд|investment\s+fund",
                      re.IGNORECASE)),
    (INSURANCE, re.compile(r"sug\W?urta|страхов|insurance", re.IGNORECASE)),
    (FINANCIAL, re.compile(r"mikromoliya|микрофинанс|microfinance|lizing|лизинг|leasing", re.IGNORECASE)),
    # «Aloqabank», «Hamkorbank»: the word is glued to the name, so no leading \b.
    (BANK, re.compile(r"bank(i)?\b|банк", re.IGNORECASE)),
)

_SECTOR_KINDS = {"funds": FUND, "fund": FUND, "finance": FINANCIAL}


def kind_from_form(org_type: Any) -> str | None:
    """The kind an openinfo statement form describes, or None for the jsc form."""
    return _FORM_KINDS.get(str(org_type or "").strip().lower())


def kind_from_name(name: Any) -> str | None:
    text = str(name or "")
    for kind, pattern in _NAME_RULES:
        if pattern.search(text):
            return kind
    return None


def resolve_kind(*, org_type: Any = None, name: Any = None, sector: Any = None) -> str:
    """Decide the organization kind from the evidence at hand.

    A filing form that names a financial kind wins outright. The commercial
    (jsc) form is not evidence of an industrial company: funds, leasing
    companies and the exchange file it too, so the name and then the sector
    decide those.
    """
    by_form = kind_from_form(org_type)
    if by_form:
        return by_form
    by_name = kind_from_name(name)
    if by_name:
        return by_name
    return _SECTOR_KINDS.get(str(sector or "").strip().lower(), INDUSTRY)


def _org_types(conn: sqlite3.Connection, tickers: Iterable[str]) -> dict[str, str]:
    """ticker → the statement form its filings were submitted on."""
    wanted = sorted({str(t).upper() for t in tickers if t})
    if not wanted:
        return {}
    marks = ",".join("?" * len(wanted))
    found: dict[str, str] = {}
    try:
        for row in conn.execute(
                f"SELECT ticker, org_type FROM catalog_financials WHERE ticker IN ({marks}) "
                "AND org_type IS NOT NULL AND org_type != '' ORDER BY year, quarter", wanted):
            found[str(row["ticker"]).upper()] = str(row["org_type"])
    except sqlite3.Error:
        catalogue_settings.logger.exception("catalogue: org_type read failed")
    missing = [t for t in wanted if t not in found]
    if missing:
        marks = ",".join("?" * len(missing))
        try:
            for row in conn.execute(
                    f"SELECT ticker, excel_url, excel_url_form1 FROM catalog_reports "
                    f"WHERE ticker IN ({marks}) AND report_form='NSBU'", missing):
                for url in (row["excel_url"], row["excel_url_form1"]):
                    match = _ORG_TYPE_IN_URL.search(str(url or ""))
                    if match:
                        found.setdefault(str(row["ticker"]).upper(), match.group(1).lower())
        except sqlite3.Error:
            catalogue_settings.logger.exception("catalogue: report org_type read failed")
    return found


def filing_org_type(ticker: str) -> str | None:
    """The statement form an issuer files on, read across its share classes."""
    conn = catalogue_storage.get_catalog_conn()
    try:
        siblings = catalogue_filings._org_siblings(conn, ticker) or [str(ticker).upper()]
        types = _org_types(conn, siblings)
    finally:
        conn.close()
    own = types.get(str(ticker).upper())
    return own or next(iter(types.values()), None)


def filing_org_types(tickers: Iterable[str]) -> dict[str, str]:
    """``filing_org_type`` for many issuers in two queries."""
    conn = catalogue_storage.get_catalog_conn()
    try:
        return _org_types(conn, tickers)
    finally:
        conn.close()


def organization_kind(ticker: str, *, name: Any = None, sector: Any = None,
                      org_type: Any = None) -> str:
    if org_type is None:
        try:
            org_type = filing_org_type(ticker)
        except Exception:  # noqa: BLE001 — a missing catalogue still has a name and sector
            catalogue_settings.logger.exception("catalogue: org_type lookup failed for %s", ticker)
            org_type = None
    return resolve_kind(org_type=org_type, name=name, sector=sector)

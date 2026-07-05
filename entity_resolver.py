"""Dynamic entity resolver — the self-discovering replacement for the hand-kept
COMPANY_CATALOG.

The UZSE stock feed is the source of truth for *what is listed*; openinfo autofill
resolves each security's name to an ``org_id`` (the key to every report / financial /
disclosure). COMPANY_CATALOG survives only as an override for the rare case where the
UZSE name does not match how openinfo indexes the issuer (e.g. Cyrillic-only names).

Design goals (see pipeline proposal):
- New listings are picked up automatically — a security that appears in the UZSE
  feed is resolved on the next run with no code change.
- Preferred shares (HMKBP) and bonds inherit their issuer org, so their financials
  fall out of the same issuer statements as the ordinary share.
"""
from __future__ import annotations

import logging
import os
from typing import Any

import requests

from company_catalog import COMPANY_CATALOG
from openinfo_collector import resolve_company

logger = logging.getLogger(__name__)

UZSE_STOCK_API_BASE = os.getenv(
    "UZSE_STOCK_API_BASE", "https://uzse-stock-production.up.railway.app"
).rstrip("/")

# Explicit ticker -> org_id overrides for issuers where openinfo autofill picks the
# wrong duplicate org. e.g. the UZSE name "O'zmetkombinat AJ" fuzzy-matches
# "O'zmarkazimpeks" (org 568) instead of the entity that files O'zmetkombinat's
# reports (org 953, the one UZMK already uses). Applied everywhere org resolution
# happens, including the financials read path.
ORG_OVERRIDES: dict[str, str] = {
    "UZMK": "953", "UZMKP": "953",     # O'zmetkombinat (autofill hits O'zmarkazimpeks 568)
    "KVTS": "445",                      # Кварц (UZSE "Kvarts AJ" hits a payment processor 1001)
    "GRBK": "11",                       # Garant bank (catalog carried a stale org)
}

# Tickers with no correct openinfo entity — the only match is a *different* company,
# so their financials cannot be trusted and are shown blank rather than wrong.
UNRELIABLE_FINANCIALS: set[str] = {
    "UTYK",  # O'ztemiryo'lkonteyner — only fuzzy-matches O'zmarkazimpeks (org 568)
}

# ticker -> curated openinfo name (reverse of COMPANY_CATALOG), used as an override
# query when the UZSE-provided name does not resolve.
_TICKER_TO_CURATED_NAME: dict[str, str] = {}
for _name, _ticker in COMPANY_CATALOG.items():
    _TICKER_TO_CURATED_NAME.setdefault(_ticker, _name)


def fetch_uzse_securities(session: requests.Session | None = None) -> list[dict[str, Any]]:
    """Return the authoritative list of listed securities from the UZSE feed.

    Each item carries at least ``ticker``, ``isin``, ``name`` and ``type``
    (stock/bond). This is what the market view is built from, so it is the correct
    universe to guarantee data for.
    """
    client = session or requests
    resp = client.get(f"{UZSE_STOCK_API_BASE}/stocks", timeout=30)
    resp.raise_for_status()
    payload = resp.json()
    stocks = payload.get("stocks") if isinstance(payload, dict) else payload
    return list(stocks or [])


def base_ticker(ticker: str, all_tickers: set[str]) -> str | None:
    """Return the ordinary-share ticker a preferred ticker belongs to, if listed.

    Preferred tickers conventionally end in ``P`` (HMKB -> HMKBP). Only treat it as
    a preferred share when the stripped ordinary ticker is itself listed, so real
    tickers ending in P (e.g. a standalone name) are not misread.
    """
    t = (ticker or "").upper()
    if len(t) > 1 and t.endswith("P") and t[:-1] in all_tickers:
        return t[:-1]
    return None


def resolve_security(
    sec: dict[str, Any],
    session: requests.Session | None = None,
    *,
    resolved_orgs: dict[str, str] | None = None,
    all_tickers: set[str] | None = None,
) -> dict[str, Any]:
    """Resolve one UZSE security to an openinfo ``org_id``.

    Resolution order (first hit wins):
      1. Preferred share inherits the already-resolved ordinary share's org.
      2. openinfo autofill on the UZSE-provided name.
      3. openinfo autofill on the curated COMPANY_CATALOG name (override).
    """
    ticker = (sec.get("ticker") or "").upper()
    name = (sec.get("name") or "").strip()
    all_tickers = all_tickers or set()

    # 0. explicit override for known wrong-autofill cases.
    if ticker in ORG_OVERRIDES:
        return {"ticker": ticker, "org_id": ORG_OVERRIDES[ticker], "resolved_by": "override", "name": name}

    # 1. preferred share inherits its ordinary share's org (no network call).
    if resolved_orgs:
        parent = base_ticker(ticker, all_tickers)
        if parent and resolved_orgs.get(parent):
            return {"ticker": ticker, "org_id": resolved_orgs[parent],
                    "resolved_by": "base_ticker", "name": name}

    # 2 & 3. try the UZSE name, then the curated override name.
    curated = _TICKER_TO_CURATED_NAME.get(ticker)
    if not curated:
        parent = base_ticker(ticker, all_tickers)
        if parent:
            curated = _TICKER_TO_CURATED_NAME.get(parent)

    queries: list[tuple[str, str]] = []
    if name:
        queries.append((name, "uzse_name"))
    if curated and curated.strip().lower() != name.lower():
        queries.append((curated, "catalog_override"))

    for query, how in queries:
        try:
            company = resolve_company(query, session=session)
        except Exception as exc:  # noqa: BLE001 — resolution is best-effort
            logger.debug("resolve %s via %s failed: %s", ticker, how, exc)
            continue
        org_id = company.get("org_id")
        if org_id:
            return {"ticker": ticker, "org_id": str(org_id), "resolved_by": how,
                    "name": name, "org_name": company.get("company_name")}

    return {"ticker": ticker, "org_id": None, "resolved_by": None, "name": name}


def resolve_all(session: requests.Session | None = None) -> list[dict[str, Any]]:
    """Discover every listed security and resolve each to an org.

    Ordinary shares are resolved first so preferred shares can inherit their org
    without a second lookup. Returns one record per security with ``org_id`` set
    (or ``None`` when unresolved), plus ``base_ticker`` for grouping.
    """
    securities = fetch_uzse_securities(session=session)
    all_tickers = {(s.get("ticker") or "").upper() for s in securities}
    # Ordinaries first (shorter / non-P), then preferred, so inheritance works.
    ordered = sorted(
        securities,
        key=lambda s: ((s.get("ticker") or "").upper().endswith("P"), (s.get("ticker") or "").upper()),
    )
    resolved_orgs: dict[str, str] = {}
    out: list[dict[str, Any]] = []
    for sec in ordered:
        rec = resolve_security(sec, session=session, resolved_orgs=resolved_orgs, all_tickers=all_tickers)
        rec["type"] = sec.get("type")
        rec["isin"] = sec.get("isin")
        rec["base_ticker"] = base_ticker(rec["ticker"], all_tickers)
        if rec.get("org_id"):
            resolved_orgs[rec["ticker"]] = rec["org_id"]
        out.append(rec)
    return out

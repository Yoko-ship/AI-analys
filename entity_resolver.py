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

import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any

import requests

from company_catalog import COMPANY_CATALOG
from db import APP_DATA_DIR
from openinfo_collector import _json_get, _make_session, resolve_company

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
    # O'zmetkombinat: org 383 "O'zbekiston metallurgiya kombinati" — confirmed
    # via the exchange screener TIN→INN join (previous value 953 was itself a
    # mismatch: openinfo names 953 "O`ZTEMIRYO`LMASHTA`MIR").
    "UZMK": "383", "UZMKP": "383",
    "KVTS": "445",                      # Кварц (UZSE "Kvarts AJ" hits a payment processor 1001)
    "GRBK": "11",                       # Garant bank (catalog carried a stale org)
    # Andijon biokimyo zavodi (org 78, INN 200240495). Name matching hit the
    # other biochemical plant "QO'QON BIOKIMYO" (org 433, INN 200126834), which
    # left BIOK's ratios empty and would attach the wrong issuer's filings.
    "BIOK": "78",
    # O'z-Tong Hong Kompani (org 80, INN 201832779): the screener TIN join
    # returns nothing for its ISIN UZ7044930004, so the deterministic index
    # never resolves it and its ratios/financials stayed blank.
    "UTHK": "80",
    # O'zbekiston neftgaz (org 735) resolves correctly, but its NSBU excels are
    # all-zero stubs (the SOE files IFRS only), so the fact-store figures are
    # the ONLY real financials — pin the org so the enrichment takes the
    # authoritative branch and fills net_income/revenue/liabilities from facts.
    "UZNGP": "735",
    # Octobank (org 27, INN 203644820, ISIN UZ7048610008): un-delisted
    # 2026-08-20. The org's info_rfb.isin_codes is empty, so the listings walk
    # takes the screener-fallback branch — the pin is what puts the issuer in
    # the walk at all, and what keeps name matching away from the org-1001
    # payment processor that once contaminated its net profit.
    "OCBK": "27",
    # Davr Bank (org 26, INN 203709707): relisted under the new DRBK ticker on
    # 2026-08-28. Openinfo still advertises the old DVRB ticker and currently
    # attaches Asia Insurance's AISK security to this org, so neither ticker nor
    # ISIN discovery can resolve it safely without explicit pins.
    "DRBK": "26",
}

# Explicit ticker -> ISIN pins for securities that openinfo's info_rfb and stock
# screener either omit or attach incorrectly. Without the ISIN the listings walk
# carries no trustworthy security — no share count, no last trade, or even a
# foreign issuer's line — while uzse.uz itself serves the authoritative card.
# Consulted before the screener join.
ISIN_OVERRIDES: dict[str, str] = {
    "OCBK": "UZ7048610008",   # Octobank ordinary; uzse quote page is live
    "DRBK": "UZ7050240009",   # Davr Bank ordinary; relisted 2026-08-28
}

# Tickers with no correct openinfo entity — the only match is a *different* company,
# so their financials cannot be trusted and are shown blank rather than wrong.
# UTYK was here (mis-matched O'zmarkazimpeks org 568) but now resolves correctly to
# org 528 ("O'ZTEMIRYOLKONTEYNER", ISIN UZ7051720009), so its figures are trusted.
UNRELIABLE_FINANCIALS: set[str] = set()

# ticker -> curated openinfo name (reverse of COMPANY_CATALOG), used as an override
# query when the UZSE-provided name does not resolve.
_TICKER_TO_CURATED_NAME: dict[str, str] = {}
for _name, _ticker in COMPANY_CATALOG.items():
    _TICKER_TO_CURATED_NAME.setdefault(_ticker, _name)


# ---------------------------------------------------------------------------
# Deterministic org index — ticker/ISIN/INN → org_id without name matching.
#
# openinfo's /home/organizations/ carries the INN (tax id) for every org, and
# /iuzse/stock-screener/ (STK + BND markets) carries ticker + ISIN + issuer TIN
# for every exchange-listed security. Joining screener.tin -> org.inn resolves
# any listed security to its issuer org exactly — including newly listed ones —
# so fuzzy name matching is only ever a last resort. (The /home/autofill/
# endpoint ignores its search parameter and returns ALL orgs, which is how
# name-based resolution used to attach the wrong company's data to a ticker.)
# ---------------------------------------------------------------------------

ORG_INDEX_TTL_HOURS = int(os.getenv("ORG_INDEX_TTL_HOURS", "24"))
_ORG_INDEX_PATH = (
    Path(os.getenv("ORG_INDEX_CACHE_PATH")).expanduser()
    if os.getenv("ORG_INDEX_CACHE_PATH")
    else APP_DATA_DIR / "org_index_cache.json"
)
_SCREENER_MARKETS = ("STK", "BND")
_org_index_mem: dict[str, Any] | None = None


def _normalize_name_key(value: str | None) -> str:
    return "".join(ch.lower() for ch in (value or "") if ch.isalnum())


def _fetch_org_index(session: requests.Session | None = None) -> dict[str, Any]:
    client = session or _make_session()

    orgs: list[dict[str, Any]] = []
    page = 1
    while page <= 20:
        payload = _json_get(client, "/home/organizations/", {"page": page, "page_size": 100})
        orgs.extend(payload.get("results") or [])
        if not payload.get("next"):
            break
        page += 1

    screener_rows: list[dict[str, Any]] = []
    for market in _SCREENER_MARKETS:
        try:
            payload = _json_get(client, "/iuzse/stock-screener/", {"mkt_id": market, "page_size": 500})
            screener_rows.extend(payload.get("results") or [])
        except Exception as exc:  # noqa: BLE001 — a missing market must not kill the index
            logger.warning("stock-screener %s fetch failed: %s", market, exc)

    by_inn: dict[str, dict[str, str]] = {}
    by_ticker: dict[str, dict[str, str]] = {}
    by_isin: dict[str, dict[str, str]] = {}
    by_name: dict[str, dict[str, str]] = {}

    for org in orgs:
        org_id = str(org.get("id") or "").strip()
        if not org_id:
            continue
        name = str(org.get("full_name_text") or org.get("short_name_text") or "").strip()
        entry = {"org_id": org_id, "name": name}
        inn = str(org.get("inn") or "").strip()
        if inn:
            by_inn.setdefault(inn, entry)
        for raw in (org.get("full_name_text"), org.get("short_name_text")):
            key = _normalize_name_key(raw)
            if key:
                by_name.setdefault(key, entry)
        # exchange_ticket_name can hold several tickers ("ORFI; ORFIP") or "-".
        for token in re.split(r"[^A-Za-z0-9]+", str(org.get("exchange_ticket_name") or "")):
            token = token.strip().upper()
            if len(token) >= 3:
                by_ticker.setdefault(token, entry)

    for row in screener_rows:
        entry = by_inn.get(str(row.get("tin") or "").strip())
        if not entry:
            continue
        ticker = str(row.get("ticker") or "").strip().upper()
        isin = str(row.get("isin_code") or "").strip().upper()
        if ticker:
            by_ticker[ticker] = entry  # exchange data outranks the org-card field
        if isin:
            by_isin[isin] = entry

    return {
        "fetched_at": time.time(),
        "org_count": len(orgs),
        "screener_count": len(screener_rows),
        "by_ticker": by_ticker,
        "by_isin": by_isin,
        "by_inn": by_inn,
        "by_name": by_name,
    }


def _index_is_fresh(index: dict[str, Any] | None) -> bool:
    if not index:
        return False
    fetched_at = float(index.get("fetched_at") or 0)
    return (time.time() - fetched_at) < ORG_INDEX_TTL_HOURS * 3600


def get_org_index(session: requests.Session | None = None, *, force: bool = False) -> dict[str, Any]:
    """The cached deterministic index; refreshed from openinfo when stale.

    On refresh failure a stale copy (memory or disk) is served rather than
    nothing — resolution then still works, just against yesterday's universe.
    """
    global _org_index_mem
    if not force and _index_is_fresh(_org_index_mem):
        return _org_index_mem

    disk: dict[str, Any] | None = None
    if _ORG_INDEX_PATH.exists():
        try:
            disk = json.loads(_ORG_INDEX_PATH.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            disk = None
    if not force and _index_is_fresh(disk):
        _org_index_mem = disk
        return disk

    try:
        index = _fetch_org_index(session)
    except Exception as exc:  # noqa: BLE001
        stale = _org_index_mem or disk
        if stale:
            logger.warning("org index refresh failed (%s); serving stale copy", exc)
            _org_index_mem = stale
            return stale
        raise
    # The screener reflects recent trading activity, so its membership varies
    # run to run. Ticker/ISIN→org mappings are stable facts — union them with
    # the previous cache so coverage only ever grows (new data wins conflicts).
    previous = _org_index_mem or disk or {}
    for key in ("by_ticker", "by_isin", "by_inn", "by_name"):
        index[key] = {**(previous.get(key) or {}), **index[key]}
    try:
        _ORG_INDEX_PATH.write_text(json.dumps(index, ensure_ascii=False), encoding="utf-8")
    except Exception:  # noqa: BLE001 — cache write is best-effort
        logger.warning("could not persist org index to %s", _ORG_INDEX_PATH)
    _org_index_mem = index
    logger.info(
        "org index refreshed: %d orgs, %d screener rows, %d tickers, %d isins",
        index["org_count"], index["screener_count"], len(index["by_ticker"]), len(index["by_isin"]),
    )
    return index


def resolve_by_index(
    ticker: str,
    isin: str | None = None,
    session: requests.Session | None = None,
) -> dict[str, str] | None:
    """Exact resolution via the deterministic index, or None (never a guess)."""
    index = get_org_index(session)
    t = (ticker or "").strip().upper()
    for key, how in ((t, "ticker"), ((isin or "").strip().upper(), "isin")):
        source = index["by_isin"] if how == "isin" else index["by_ticker"]
        hit = source.get(key) if key else None
        if hit:
            return {"org_id": hit["org_id"], "org_name": hit["name"], "resolved_by": how}
    # Preferred/secondary lines sometimes list only the base ticker on the org
    # card (UPOSP -> UPOS): try the stripped variant as an exact key too.
    if len(t) > 1 and t.endswith("P"):
        hit = index["by_ticker"].get(t[:-1])
        if hit:
            return {"org_id": hit["org_id"], "org_name": hit["name"], "resolved_by": "base_ticker_index"}
    return None


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
      1. Explicit ORG_OVERRIDES escape hatch.
      2. Deterministic index: exchange ticker / ISIN → issuer TIN → org INN.
      3. Preferred share inherits the already-resolved ordinary share's org.
      4. Name matching (autofill/fuzzy) — last resort only.
    """
    ticker = (sec.get("ticker") or "").upper()
    name = (sec.get("name") or "").strip()
    all_tickers = all_tickers or set()

    # 0. explicit override for known wrong-autofill cases.
    if ticker in ORG_OVERRIDES:
        return {"ticker": ticker, "org_id": ORG_OVERRIDES[ticker], "resolved_by": "override", "name": name}

    # 1. deterministic ticker/ISIN → INN → org join (never guesses).
    try:
        hit = resolve_by_index(ticker, sec.get("isin"), session=session)
    except Exception as exc:  # noqa: BLE001 — index build needs network
        logger.warning("org index unavailable for %s: %s", ticker, exc)
        hit = None
    if hit:
        return {"ticker": ticker, "org_id": hit["org_id"], "resolved_by": hit["resolved_by"],
                "name": name, "org_name": hit.get("org_name")}

    # 2. preferred share inherits its ordinary share's org (no network call).
    if resolved_orgs:
        parent = base_ticker(ticker, all_tickers)
        if parent and resolved_orgs.get(parent):
            return {"ticker": ticker, "org_id": resolved_orgs[parent],
                    "resolved_by": "base_ticker", "name": name}

    # 3. last resort: name matching on the UZSE name, then the curated name.
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
        rec["share_type"] = sec.get("share_type")
        rec["base_ticker"] = base_ticker(rec["ticker"], all_tickers)
        if rec.get("org_id"):
            resolved_orgs[rec["ticker"]] = rec["org_id"]
        out.append(rec)
    return out

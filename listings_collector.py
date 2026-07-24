"""Collect the exchange-listing registry (openinfo info_rfb) + last trade.

Runs where openinfo.uz is reachable. For every catalogued issuer it reads the
org's RFB securities (ISIN, shares outstanding, reference price, listing date)
from ``/home/organizations/{org_id}/`` and the last trade from
``/iuzse/conclusions/``, producing one row per security (ordinary + preferred
are separate rows). ``collector_financials`` pushes these to prod so that
issuers listed on RFB Tashkent but absent from the live uzse-stock feed (no
recent trades) still appear on the market board, tagged inactive.
"""
from __future__ import annotations

import html as _html
import logging
import re
from datetime import date, timedelta
from typing import Any

import requests

import reports_catalog as rc
from entity_resolver import ORG_OVERRIDES
from openinfo_collector import OPENINFO_API_BASE, _json_get, _make_session

log = logging.getLogger("listings")

# openinfo stock_type codes → the market feed's share_type vocabulary.
_STOCK_TYPE = {"01": "ordinary", "02": "preferred"}
_CONCLUSIONS_LOOKBACK_DAYS = 3650

# UZSE (RFB Tashkent) site — fallback source of the issued-share count for
# issuers openinfo omits from info_rfb (empty isin_codes).
_UZSE_BASE = "https://uzse.uz"
_SCREENER_ISINS: dict[str, str] | None = None


def _uzse_screener_isins(session: Any) -> dict[str, str]:
    """ticker → ISIN for every UZSE-listed stock (openinfo's screener proxy).

    Recovers the ISIN of issuers whose openinfo org detail carries no RFB
    securities, so their share count can still be read from UZSE. Memoized.
    """
    global _SCREENER_ISINS
    if _SCREENER_ISINS is not None:
        return _SCREENER_ISINS
    out: dict[str, str] = {}
    for page in range(1, 12):
        try:
            data = _json_get(session, "/iuzse/stock-screener/",
                             {"mkt_id": "STK", "page_size": 100, "page": page})
        except Exception:  # noqa: BLE001
            break
        results = (data.get("results") or []) if isinstance(data, dict) else (data or [])
        if not results:
            break
        for r in results:
            tk = str(r.get("ticker") or "").strip().upper()
            isin = str(r.get("isin_code") or "").strip().upper()
            if tk and isin:
                out.setdefault(tk, isin)
        if len(results) < 100:
            break
    _SCREENER_ISINS = out
    return out


_BOND_NOMINAL_CACHE: dict[str, float | None] = {}


def _uzse_bond_nominal(isin: str) -> float | None:
    """Bond par value from UZSE's BND page ("Номинал (UZS)").

    openinfo's info_rfb carries no reference price for exchange bonds, so a
    never-traded bond row had no cap at all. UZSE publishes the par value;
    outstanding face value (count × par) is the standard size metric for a
    bond and is what the board's cap column shows for these rows. Fetched with
    browser headers — uzse.uz answers 406 to JSON-accepting clients.
    """
    if isin in _BOND_NOMINAL_CACHE:
        return _BOND_NOMINAL_CACHE[isin]
    val: float | None = None
    try:
        resp = requests.get(
            f"{_UZSE_BASE}/isu_infos/BND",
            params={"isu_cd": isin, "locale": "ru"},
            headers={"User-Agent": "Mozilla/5.0", "Accept": "text/html"},
            timeout=30,
        )
        text = re.sub(r"<[^>]+>", "|", _html.unescape(resp.text))
        cells = [c.strip() for c in re.sub(r"\|+", "|", re.sub(r"[ \t]+", " ", text)).split("|") if c.strip()]
        for i, c in enumerate(cells):
            if "Номинал" in c and i + 1 < len(cells):
                val = _num(cells[i + 1].replace("\xa0", "").replace(" ", "").replace(",", ""))
                break
    except Exception:  # noqa: BLE001
        val = None
    _BOND_NOMINAL_CACHE[isin] = val
    return val


def _uzse_share_count(session: Any, isin: str) -> float | None:
    """Issued share count from UZSE's isu_infos detail endpoint.

    openinfo omits ``list_shares`` for some issuers (empty isin_codes); UZSE
    returns it as ``shares[].list_shrs`` from ``/isu_infos/{isin}/detail`` (a
    JSON list of yearly issuance records). Prefers the share record whose ISIN
    matches, else the first with a count.
    """
    try:
        data = session.get(f"{_UZSE_BASE}/isu_infos/{isin}/detail",
                           params={"locale": "ru"}, timeout=30).json()
    except Exception:  # noqa: BLE001
        return None
    records = data if isinstance(data, list) else [data]
    fallback: float | None = None
    for rec in records:
        for sh in (rec.get("shares") or []) if isinstance(rec, dict) else []:
            count = _num(sh.get("list_shrs"))
            if count and str(sh.get("isu_cd") or "").upper() == isin.upper():
                return count
            if count and fallback is None:
                fallback = count
    return fallback


_UZSE_EQUITY_CACHE: dict[str, dict | None] = {}


def _uzse_equity(session: Any, isin: str) -> dict | None:
    """Authoritative share count + last trade for an equity ISIN, from UZSE.

    openinfo's ``info_rfb.list_shares``/``price`` are frequently stale or carry an
    older denomination (pre-issuance count, par-value redenomination), which skewed
    the board's market cap — verified against uzse.uz, 38/109 tickers disagreed,
    almost all because the share count was off while the price already matched the
    exchange. UZSE (the exchange's own registry) publishes the current ``list_shrs``
    and last ``trade_price`` at ``/isu_infos/{isin}/detail``. Returns
    ``{shares, price, date, mktcap}`` for the line whose ISIN matches, or None.
    Cached per ISIN; fetched with the paced browser session.
    """
    if isin in _UZSE_EQUITY_CACHE:
        return _UZSE_EQUITY_CACHE[isin]
    result: dict | None = None
    try:
        data = session.get(f"{_UZSE_BASE}/isu_infos/{isin}/detail",
                           params={"locale": "ru"}, timeout=30).json()
        for rec in (data if isinstance(data, list) else [data]):
            if not isinstance(rec, dict) or rec.get("error"):
                continue
            for sh in rec.get("shares") or []:
                if str(sh.get("isu_cd") or "").upper() == isin.upper():
                    result = {
                        "shares": _num(sh.get("list_shrs")),
                        "price": _num(sh.get("trade_price")),
                        "date": sh.get("executions_date"),
                        "mktcap": _num(rec.get("market_capitalization")),
                    }
                    break
            if result:
                break
    except Exception:  # noqa: BLE001
        result = None
    _UZSE_EQUITY_CACHE[isin] = result
    return result


def _num(v: Any) -> float | None:
    try:
        return None if v in (None, "", "-") else float(v)
    except (TypeError, ValueError):
        return None


def _fmt_date(v: Any) -> str | None:
    """openinfo listing_date is 'YYYYMMDD' → 'YYYY-MM-DD'."""
    s = str(v or "").strip()
    if len(s) == 8 and s.isdigit():
        return f"{s[:4]}-{s[4:6]}-{s[6:]}"
    return s or None


def _org_ids() -> dict[str, str]:
    """ticker → org_id from the local catalog (already resolved by sync_all)."""
    conn = rc.get_catalog_conn()
    rows = conn.execute(
        "SELECT ticker, org_id FROM catalog_companies "
        "WHERE org_id IS NOT NULL AND org_id != ''"
    ).fetchall()
    conn.close()
    result = {r["ticker"]: ORG_OVERRIDES.get(r["ticker"], str(r["org_id"])) for r in rows}
    # Some issuers (e.g. UTHK) never land in catalog_companies because discovery's
    # screener TIN join misses them, yet they carry an explicit ORG_OVERRIDES pin
    # and real facts under that org. Seed those override-only tickers so the org
    # map still joins the org's facts to the ticker in get_all_ratios.
    for tk, org in ORG_OVERRIDES.items():
        result.setdefault(tk, str(org))
    return result


def _last_conclusion(session: Any, isin: str) -> dict[str, Any] | None:
    """Latest OHLC trade point for an ISIN, or None if it has never traded."""
    end = date.today()
    start = end - timedelta(days=_CONCLUSIONS_LOOKBACK_DAYS)
    try:
        payload = _json_get(
            session, "/iuzse/conclusions/",
            {"isu_cd": isin, "start_date": start.isoformat(), "end_date": end.isoformat()},
        )
    except Exception:  # noqa: BLE001 — no history just means no last trade
        return None
    points = (payload.get("results") or []) if isinstance(payload, dict) else []
    if not points:
        return None
    points.sort(key=lambda p: str(p.get("date") or ""))
    return points[-1]


def collect_listing_rows() -> list[dict[str, Any]]:
    """One row per RFB-registered security across all catalogued issuers."""
    session = _make_session()
    org_ids = _org_ids()
    org_detail_cache: dict[str, dict] = {}
    seen_tickers: set[str] = set()
    rows: list[dict[str, Any]] = []

    for ticker, org_id in org_ids.items():
        detail = org_detail_cache.get(org_id)
        if detail is None:
            # Many tickers share an org (common + preferred); info_rfb already
            # lists all of the org's securities, so fetch each org only once.
            try:
                resp = session.get(f"{OPENINFO_API_BASE}/home/organizations/{org_id}/", timeout=30)
                resp.raise_for_status()
                detail = resp.json()
            except Exception:  # noqa: BLE001
                log.warning("org %s (%s) detail fetch failed", org_id, ticker)
                detail = {}
            org_detail_cache[org_id] = detail

        rfb = (detail.get("info_rfb") or {}) if isinstance(detail, dict) else {}
        name = detail.get("full_name_text") or detail.get("short_name_text") or ticker
        for ic in rfb.get("isin_codes") or []:
            tk = str(ic.get("ticker") or "").strip().upper()
            isin = str(ic.get("isu_cd") or "").strip().upper()
            if not tk or not isin or tk in seen_tickers:
                continue
            seen_tickers.add(tk)

            shares = _num(ic.get("list_shares"))
            reference_price = _num(ic.get("price"))
            # UZSE (the exchange) is authoritative for the current share count and
            # last trade; openinfo's info_rfb figures are frequently stale or in an
            # older denomination, which skewed market cap. Prefer UZSE for equities.
            uz = _uzse_equity(session, isin) if isin.startswith("UZ7") else None
            if uz and uz.get("shares"):
                shares = uz["shares"]
            if not reference_price and isin.startswith("UZ6"):
                # Exchange bond (UZ6… ISIN) with no openinfo reference price:
                # par from UZSE so the cap shows outstanding face value.
                reference_price = _uzse_bond_nominal(isin)

            last = _last_conclusion(session, isin)
            last_close = _num(last.get("close")) if last else None
            uz_price = uz.get("price") if uz else None
            # The conclusions feed looks back years; for a redenominated / long-idle
            # equity its close can be a pre-redenomination stub that no longer matches
            # the current share count and would blow up the cap. Trust it only when it
            # agrees with UZSE's stated last trade, else take UZSE's price and drop the
            # mismatched OHLC.
            if uz_price:
                if last_close and 0.9 <= (last_close / uz_price) <= 1.1:
                    last_price = last_close
                else:
                    last = None
                    last_price = uz_price
            else:
                last_price = last_close
            price_for_cap = last_price if last_price is not None else reference_price

            if last:
                last_trade_date = last.get("date")
            elif uz and uz.get("date"):
                p = str(uz["date"]).split(".")
                last_trade_date = f"{p[2]}-{p[1]}-{p[0]}" if len(p) == 3 else uz["date"]
            else:
                last_trade_date = None
            rows.append({
                "ticker": tk,
                "isin": isin,
                "name": name,
                "share_type": _STOCK_TYPE.get(str(ic.get("stock_type") or ""), "ordinary"),
                "listing_date": _fmt_date(ic.get("listing_date")),
                "shares_outstanding": shares,
                "reference_price": reference_price,
                "last_price": last_price,
                "last_trade_date": last_trade_date,
                "open_price": _num(last.get("open")) if last else None,
                "high_price": _num(last.get("high")) if last else None,
                "low_price": _num(last.get("low")) if last else None,
                "volume": _num(last.get("trading_volume")) if last else None,
                "market_cap": (shares * price_for_cap) if (shares and price_for_cap) else None,
            })

        # Issuer listed on openinfo but with no tradable RFB security (empty
        # isin_codes — e.g. an inactive exchange registration like NGQT): still
        # surface it on the board (financials only, no price) so curated catalog
        # companies stay visible instead of vanishing. Keyed by our catalog ticker.
        if not (rfb.get("isin_codes") or []) and ticker not in seen_tickers:
            seen_tickers.add(ticker)
            # openinfo lists no RFB security for this issuer, but UZSE may still
            # publish its ISIN and share count — recover them so the market-cap
            # join has shares to multiply by the live price (e.g. BIOK, DORI).
            uz_isin = _uzse_screener_isins(session).get(ticker)
            uz_shares = _uzse_share_count(session, uz_isin) if uz_isin else None
            last = _last_conclusion(session, uz_isin) if uz_isin else None
            last_price = _num(last.get("close")) if last else None
            rows.append({
                "ticker": ticker, "isin": uz_isin, "name": name,
                "share_type": "ordinary", "listing_date": None,
                "shares_outstanding": uz_shares, "reference_price": None,
                "last_price": last_price, "last_trade_date": (last or {}).get("date"),
                "open_price": _num(last.get("open")) if last else None,
                "high_price": _num(last.get("high")) if last else None,
                "low_price": _num(last.get("low")) if last else None,
                "volume": _num(last.get("trading_volume")) if last else None,
                "market_cap": (uz_shares * last_price) if (uz_shares and last_price) else None,
            })

    log.info("collected %d listing rows from %d orgs", len(rows), len(org_detail_cache))
    return rows


_FIN_VALUE_KEYS = ("revenue", "gross_profit", "cash", "total_liabilities",
                   "net_income", "operating_income")


_ORG_TICKERS_MEMO: dict[str, set[str]] | None = None


def _org_to_tickers(session: Any) -> dict[str, set[str]]:
    """org_id → every security ticker of that issuer (catalog + info_rfb).

    Memoized per process: the collector calls this from both the financials-alias
    and org-map steps, and the ~one org-detail request per issuer is the whole
    cost of the walk.
    """
    global _ORG_TICKERS_MEMO
    if _ORG_TICKERS_MEMO is not None:
        return _ORG_TICKERS_MEMO
    org_ids = _org_ids()
    mapping: dict[str, set[str]] = {}
    detail_cache: dict[str, dict] = {}
    for ticker, org_id in org_ids.items():
        detail = detail_cache.get(org_id)
        if detail is None:
            try:
                resp = session.get(f"{OPENINFO_API_BASE}/home/organizations/{org_id}/", timeout=30)
                resp.raise_for_status()
                detail = resp.json()
            except Exception:  # noqa: BLE001
                detail = {}
            detail_cache[org_id] = detail
        rfb = (detail.get("info_rfb") or {}) if isinstance(detail, dict) else {}
        bucket = mapping.setdefault(org_id, set())
        bucket.add(ticker.upper())
        for ic in rfb.get("isin_codes") or []:
            tk = str(ic.get("ticker") or "").strip().upper()
            if tk:
                bucket.add(tk)
    _ORG_TICKERS_MEMO = mapping
    return mapping


def collect_org_map_rows() -> list[dict[str, Any]]:
    """The collector's authoritative ticker→org map as fact rows (dataset
    ``org_map``, entity_id = ticker).

    The fact store is keyed by the collector's org IDs, but the deployment used
    to join it against its *own* catalog_companies — a map that drifts (BIOK
    resolved to a different biochemical plant there) and lacks secondary lines
    (a bank's SQB2/HMBK1-style issues), leaving their ratios blank. Pushing the
    map alongside the facts lets ``get_all_ratios`` join on the same IDs the
    facts were landed under, siblings included.
    """
    session = _make_session()
    rows: list[dict[str, Any]] = []
    for org_id, tickers in _org_to_tickers(session).items():
        for tk in sorted(tickers):
            rows.append({
                "entity_id": tk, "dataset": "org_map", "field": "org_id",
                "period": "", "value": str(org_id), "source": "collector",
            })
    return rows


def collect_financials_aliases() -> list[dict[str, Any]]:
    """Financials rows copied onto every security ticker of the same issuer.

    A company's financials are issuer-level, but the market board keys them by
    ticker — so an issuer's preferred line, bonds, or ordinary/preferred variant
    (AGMK vs AGMKP, KSCMP vs KSCM, a bank's bonds) showed blank financials even
    though the issuer's numbers exist. For each org, copy the financials of a
    ticker that has them onto its siblings that don't.
    """
    session = _make_session()
    fin = {t.upper(): f for t, f in rc.get_all_financials().items()}
    rows: list[dict[str, Any]] = []
    for org_id, tickers in _org_to_tickers(session).items():
        source = next(
            (fin[t] for t in tickers
             if t in fin and any(fin[t].get(k) is not None for k in _FIN_VALUE_KEYS)),
            None,
        )
        if not source:
            continue
        for tk in tickers:
            if tk in fin:
                continue  # already carries its own financials
            rows.append({
                "ticker": tk, "form": "NSBU",
                "year": source.get("year"), "quarter": source.get("quarter") or 0,
                **{k: source.get(k) for k in _FIN_VALUE_KEYS},
            })
    log.info("financials aliases: %d sibling tickers", len(rows))
    return rows


if __name__ == "__main__":
    import json
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    print(json.dumps(collect_listing_rows(), ensure_ascii=False, indent=2))

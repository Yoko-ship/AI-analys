"""securities_catalog.py — structured securities catalog with Wikipedia caching."""
from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

from db import APP_DATA_DIR
from delisted import DELISTED_TICKERS

logger = logging.getLogger(__name__)

# Railway's container filesystem is ephemeral, so the default path is wiped on
# every redeploy. This DB (securities + volume_records) defaults under
# APP_DATA_DIR, which db.py resolves to RAILWAY_VOLUME_MOUNT_PATH when a volume is
# mounted — so mounting a volume persists it across deploys with no extra config.
# SECURITIES_DB_PATH still overrides the location explicitly if set.
DB_PATH = Path(os.getenv("SECURITIES_DB_PATH") or (APP_DATA_DIR / "securities.db"))

# Sector mapping for tickers known from company_catalog
_TICKER_SECTORS: dict[str, str] = {
    "HMKB": "finance", "HMKBP": "finance",
    "IPKY": "finance",
    "IPTB": "finance", "IPTBP": "finance",
    "AGBA": "finance", "AGBAP": "finance",
    "SQBN": "finance", "SQBNP": "finance",
    "TRSB": "finance", "TRSBP": "finance",
    "TNBN": "finance", "TNBNP": "finance",
    "ALKB": "finance", "ALKBP": "finance",
    "GRBK": "finance",
    "MCBA": "finance", "MCBAP": "finance",
    "UNVB": "finance",
    "BRBN": "finance", "BRBNP": "finance",
    "TNGB": "finance",
    "URTS": "finance",
    "KASU": "finance", "KASUP": "finance",
    "ALSM": "finance", "ALSMP": "finance",
    "TMYS": "finance",
    "UZMK": "manufacturing", "UZMKP": "manufacturing",
    "KVTS": "manufacturing",
    "QZSM": "manufacturing",
    "BECM": "manufacturing", "BECMP": "manufacturing",
    "UZMT": "manufacturing",
    "DORI": "manufacturing",
    "ORGS": "manufacturing",
    "BIOK": "manufacturing",
    "UZHM": "manufacturing",
    "AGMKP": "mining",
    "BNGP": "mining", "BNGPP": "mining",
    "UZNGP": "mining",
    "UZGFP": "mining",
    "NGQS": "mining",
    "UZIR": "mining", "UZIRP": "mining",
    "PLST": "mining",
    "SANE": "mining",
    "UTGA": "logistics", "UTGAP": "logistics",  # O'ztransgaz — gas transport / pipelines
    "QATT": "transport",
    "UPOS": "transport", "UPOSP": "transport",
    "UZTL": "telecom", "UZTLP": "telecom",
    "BTRL": "professional",
    "CBSK": "trade",
    "JASM": "other",
    "TKDMP": "other",
    # Added companies
    "KFSK": "finance", "KFSKP": "finance",
    "UZAS": "finance", "UZASP": "finance",
    # Insurance / leasing (financial sector)
    "UZINP": "finance",  # O'zbekinvest — national export-import insurer
    "UZAL": "finance",   # O'zagrolizing — leasing
    "UZML": "finance",   # UzMED-lizing — medical-equipment leasing
    # Chemicals (manufacturing)
    "FRAZP": "manufacturing",  # Farg'onaazot — nitrogen fertilizers / chemicals
    "KSCM": "manufacturing", "KSCMP": "manufacturing",
    "YGSY": "mining",
    "UTYK": "transport", "UVGT": "transport",
    "METQ": "other", "UQEQ": "other",
    "TGPG": "professional",
    # Investment funds
    "UZNF": "funds", "UZNFP": "funds",  # National Investment Fund of Uzbekistan
}

# Wikipedia search titles for known tickers
_WIKI_TITLES: dict[str, dict[str, str]] = {
    "HMKB":  {"ru": "Хамкорбанк", "en": "Hamkorbank", "uz": "Hamkorbank"},
    "IPKY":  {"ru": "Ипак Йули Банк", "en": "Ipak Yuli Bank"},
    "IPTB":  {"ru": "Ипотека-банк", "en": "Ipoteka-Bank"},
    "AGBA":  {"ru": "Агробанк (Узбекистан)", "en": "Agrobank (Uzbekistan)"},
    "SQBN":  {"ru": "Узпромстройбанк", "en": "Uzpromstroybank"},
    "TRSB":  {"ru": "Трастбанк", "en": "Trustbank (Uzbekistan)"},
    "TNBN":  {"ru": "Туронбанк", "en": "Turonbank"},
    "ALKB":  {"ru": "Алокабанк", "en": "Aloqabank"},
    "MCBA":  {"ru": "Микрокредитбанк", "en": "Microcreditbank"},
    "UNVB":  {"ru": "Universal Bank (Узбекистан)", "en": "Universal Bank (Uzbekistan)"},
    "BRBN":  {"ru": "Банк развития бизнеса (Узбекистан)", "en": "Business Development Bank of Uzbekistan"},
    "UZTL":  {"ru": "Узбектелеком", "en": "Uzbektelecom"},
    "UZMT":  {"ru": "УзАвто Моторс", "en": "UzAuto Motors"},
    "UZMK":  {"ru": "Узметкомбинат", "en": "Uzmetkombinat"},
    "QZSM":  {"ru": "Кизилкумцемент", "en": "Kizilkumcement"},
    "BECM":  {"ru": "Бекабадцемент", "en": "Bekabadcement"},
    "DORI":  {"ru": "Дори-Дармон", "en": "Dori-Darmon"},
    "AGMKP": {"ru": "Алмалыкский ГМК", "en": "Almalyk Mining and Metallurgical Complex"},
    "BNGP":  {"ru": "Бухоронефтгазпармалаш", "en": "Bukhara Oil and Gas Production"},
}


# Curated descriptions for issuers that have no Wikipedia article. Used as a
# fallback when ``_search_wikipedia`` finds nothing, so the company page always
# shows real information instead of "unavailable". Keyed by the base ticker;
# preferred/common siblings (e.g. TKDM <-> TKDMP) and bond series codes resolve
# to the same entry. The data lives in its own module to keep this file readable.
from manual_company_info import MANUAL_INFO as _MANUAL_INFO


def _manual_info(ticker: str, language: str) -> dict[str, str] | None:
    """Return a curated description for a ticker, or None.

    Tries the ticker as-is, then its preferred/common sibling, so both ``TKDM``
    and ``TKDMP`` resolve to the same entry. Falls back ru -> en -> uz for text.
    """
    ticker = (ticker or "").upper().strip()
    if not ticker:
        return None
    sibling = ticker[:-1] if ticker.endswith("P") else ticker + "P"
    entry = _MANUAL_INFO.get(ticker) or _MANUAL_INFO.get(sibling)
    if not entry:
        # Bonds trade under series codes (BFMT3V2, ACMT2B4) rather than the
        # issuer's stock ticker; key them by the issuer's leading-letter prefix,
        # the same way resolve_logo / BOND_ISSUER_LOGOS do.
        prefix = re.match(r"^[A-Z]+", ticker)
        if prefix:
            entry = _MANUAL_INFO.get(prefix.group(0))
    if not entry:
        return None
    text = entry.get(language) or entry.get("ru") or entry.get("en") or entry.get("uz")
    if not text:
        return None
    return {"title": entry.get("title"), "text": text, "url": entry.get("url")}


def _get_conn():
    """Backend-agnostic (ТЗ §10.1). WAL and friends belong to dbx's SQLite
    factory — they configure SQLite, not "a database"."""
    from db import sqlite_connect

    return sqlite_connect(str(DB_PATH))


def _init_db(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS securities (
            ticker       TEXT PRIMARY KEY,
            isin         TEXT,
            name         TEXT,
            name_uz      TEXT,
            name_en      TEXT,
            type         TEXT,
            share_type   TEXT,
            sector       TEXT,
            logo_url     TEXT,
            is_preferred INTEGER DEFAULT 0,
            last_price   REAL,
            close_price  REAL,
            last_trade_date TEXT,
            url          TEXT,
            updated_at   TEXT
        );
        CREATE TABLE IF NOT EXISTS wiki_cache (
            ticker       TEXT PRIMARY KEY,
            lang         TEXT NOT NULL DEFAULT 'ru',
            title        TEXT,
            extract      TEXT,
            page_url     TEXT,
            fetched_at   TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS volume_records (
            ticker          TEXT PRIMARY KEY,
            max_volume      REAL,
            max_volume_date TEXT,
            max_quantity    REAL,
            updated_at      TEXT
        );
    """)
    conn.commit()


def record_volume(stocks: list[dict]) -> int:
    """Track the largest single-day turnover ever seen per ticker.

    The UZSE feed only exposes per-stock daily aggregates (no individual trades),
    so the closest thing to "the biggest deal" is the record trading day. Each
    sync we compare the day's volume against the stored max and keep the larger,
    along with the trade date it occurred on. Returns the number of records
    updated/created. To persist across deploys, point SECURITIES_DB_PATH at a
    mounted volume (the table otherwise resets with the ephemeral container).
    """
    conn = _get_conn()
    _init_db(conn)
    now = datetime.now(timezone.utc).isoformat()
    changed = 0
    for s in stocks:
        ticker = (s.get("ticker") or "").upper().strip()
        try:
            vol = float(s.get("volume") or 0)
        except (TypeError, ValueError):
            vol = 0.0
        if not ticker or vol <= 0:
            continue
        date = s.get("last_trade_date")
        qty = s.get("quantity")
        row = conn.execute("SELECT max_volume FROM volume_records WHERE ticker=?", (ticker,)).fetchone()
        if row is None:
            conn.execute(
                "INSERT INTO volume_records (ticker, max_volume, max_volume_date, max_quantity, updated_at) VALUES (?,?,?,?,?)",
                (ticker, vol, date, qty, now),
            )
            changed += 1
        elif vol > (row["max_volume"] or 0):
            conn.execute(
                "UPDATE volume_records SET max_volume=?, max_volume_date=?, max_quantity=?, updated_at=? WHERE ticker=?",
                (vol, date, qty, now, ticker),
            )
            changed += 1
    conn.commit()
    conn.close()
    return changed


# Bonds trade under series codes (BFMT3V2, ACMT2B4, UZUMS3B) rather than the
# issuer's stock ticker, so they never match company_logos.json. Map the
# leading-letter issuer prefix to the issuer's logo instead.
BOND_ISSUER_LOGOS: dict[str, str] = {
    "BFMT": "/logos/plate/BFMT.jpg",  # BIZNES FINANS (self-hosted wordmark)
    "ACMT": "https://www.google.com/s2/favicons?domain=agatcredit.uz&sz=128",  # AGAT CREDIT
    "CTFB": "https://www.google.com/s2/favicons?domain=contactfinance.uz&sz=128",  # CONTACT FINANCE
    "UZUMS": "https://www.google.com/s2/favicons?domain=uzumsarmoya.uz&sz=128",  # UZUM SARMOYA
}


def _preferred_flag(share_type, name) -> bool:
    """Preferred is what the feed SAYS is preferred, never what the ticker
    looks like. BNGP and UZINP are ordinary shares whose tickers happen to end
    in ``P``, and the old ticker-shape guess labelled both «Привилегированная»
    on their pages. The name suffix covers the one row the feed itself
    mislabels: UZNGP carries ``share_type=ordinary`` under a name that says
    «привилегированные»."""
    return (str(share_type or "").lower() == "preferred"
            or "привилегирован" in str(name or "").lower())


def resolve_logo(ticker: str, logos: dict[str, str]) -> str | None:
    """Resolve a ticker's logo, sharing it across common/preferred share pairs.

    Share pairs follow the ``P``-suffix ticker convention (``TKDM``/``TKDMP``),
    which is safe here because a wrong guess only shares a logo between two
    listings of the same issuer — unlike ``is_preferred``, which must come from
    the feed's own class field (see ``_preferred_flag``).
    When a ticker has no logo of its own, borrow its sibling's: the common share
    falls back to the preferred logo (``TKDM`` -> ``TKDMP``) and vice versa, since
    both are the same issuer. This avoids blank fallbacks for one half of a pair.

    Bonds (series codes like ``BFMT3V2``) fall back to their issuer-prefix logo.
    """
    ticker = (ticker or "").upper().strip()
    if not ticker:
        return None
    direct = logos.get(ticker)
    if direct:
        return direct
    sibling = ticker[:-1] if ticker.endswith("P") else ticker + "P"
    sib = logos.get(sibling)
    if sib:
        return sib
    prefix = re.match(r"^[A-Z]+", ticker)
    if prefix:
        return BOND_ISSUER_LOGOS.get(prefix.group(0)) or None
    return None


def sync_securities(stocks: list[dict], logos: dict[str, str]) -> int:
    """Upsert all UZSE stocks into the securities table. Returns count of rows upserted."""
    conn = _get_conn()
    _init_db(conn)
    now = datetime.now(timezone.utc).isoformat()
    count = 0
    for s in stocks:
        ticker = (s.get("ticker") or "").upper().strip()
        if not ticker or ticker in DELISTED_TICKERS:
            continue
        sector = _TICKER_SECTORS.get(ticker, "other")
        is_preferred = 1 if _preferred_flag(s.get("share_type"), s.get("name") or s.get("company_name")) else 0
        conn.execute(
            """
            INSERT INTO securities
                (ticker, isin, name, type, share_type, sector, logo_url, is_preferred,
                 last_price, close_price, last_trade_date, url, updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(ticker) DO UPDATE SET
                isin=excluded.isin,
                -- The exchange feed carries a name for only 9 of its 78 securities,
                -- and a plain overwrite let that null erase a name we already had.
                -- A sync never un-names a security.
                name=COALESCE(excluded.name, securities.name),
                type=excluded.type,
                share_type=excluded.share_type,
                sector=excluded.sector,
                logo_url=excluded.logo_url,
                is_preferred=excluded.is_preferred,
                last_price=excluded.last_price,
                close_price=excluded.close_price,
                last_trade_date=excluded.last_trade_date,
                url=COALESCE(excluded.url, securities.url),
                updated_at=excluded.updated_at
            """,
            (
                ticker,
                s.get("isin"),
                s.get("name") or s.get("company_name"),
                s.get("type", "stock"),
                s.get("share_type"),
                sector,
                resolve_logo(ticker, logos),
                is_preferred,
                s.get("last_price"),
                s.get("close_price"),
                s.get("last_trade_date"),
                s.get("url"),
                now,
            ),
        )
        count += 1
    conn.commit()
    conn.close()
    return count


def get_securities_map() -> dict[str, dict]:
    """Return {ticker: info_dict} for all securities."""
    conn = _get_conn()
    _init_db(conn)
    rows = conn.execute("SELECT * FROM securities ORDER BY ticker").fetchall()
    vrows = conn.execute("SELECT ticker, max_volume, max_volume_date, max_quantity FROM volume_records").fetchall()
    conn.close()
    records = {v["ticker"]: v for v in vrows}
    result: dict[str, dict] = {}
    for row in rows:
        d = dict(row)
        if d["ticker"] in DELISTED_TICKERS:
            # Deleted from the site: skip on read as well as on write, so a row
            # written before the ticker was delisted cannot serve a company page.
            continue
        # Recomputed on read so rows written under the old ticker-shape guess
        # (BNGP, UZINP) answer correctly without waiting for the next sync.
        d["is_preferred"] = _preferred_flag(d.get("share_type"), d.get("name"))
        vr = records.get(d["ticker"])
        if vr:
            d["max_volume"] = vr["max_volume"]
            d["max_volume_date"] = vr["max_volume_date"]
            d["max_quantity"] = vr["max_quantity"]
        result[d["ticker"]] = d
    return result


def _build_info(ticker: str, language: str, title, extract, page_url) -> dict:
    """Assemble the info payload, falling back to a curated description.

    When Wikipedia has no article (``extract`` empty), substitute the manually
    curated description so the company page always shows real information. The
    ``source`` field lets the UI label the link ("Wikipedia" vs official site).
    """
    if extract:
        return {"ticker": ticker, "title": title, "extract": extract,
                "page_url": page_url, "source": "wikipedia"}
    manual = _manual_info(ticker, language)
    if manual:
        return {"ticker": ticker, "title": manual["title"], "extract": manual["text"],
                "page_url": manual["url"], "source": "official"}
    return {"ticker": ticker, "title": title, "extract": extract,
            "page_url": page_url, "source": None}


def get_wiki_info(ticker: str, company_name: str, language: str = "ru") -> dict:
    """Fetch and cache Wikipedia summary for a ticker. Cache TTL = 30 days."""
    conn = _get_conn()
    _init_db(conn)
    ticker = ticker.upper()
    row = conn.execute(
        "SELECT * FROM wiki_cache WHERE ticker=? AND lang=?", (ticker, language)
    ).fetchone()
    if row:
        fetched = row["fetched_at"]
        age_days = (time.time() - datetime.fromisoformat(fetched).timestamp()) / 86400
        if age_days < 30:
            conn.close()
            return _build_info(ticker, language, row["title"], row["extract"], row["page_url"])

    # Try to find a Wikipedia article
    extract, title, page_url = _search_wikipedia(ticker, company_name, language)

    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """INSERT INTO wiki_cache (ticker, lang, title, extract, page_url, fetched_at)
           VALUES (?,?,?,?,?,?)
           ON CONFLICT(ticker) DO UPDATE SET
             lang=excluded.lang, title=excluded.title,
             extract=excluded.extract, page_url=excluded.page_url,
             fetched_at=excluded.fetched_at""",
        (ticker, language, title, extract, page_url, now),
    )
    conn.commit()
    conn.close()
    return _build_info(ticker, language, title, extract, page_url)


def _search_wikipedia(ticker: str, company_name: str, language: str) -> tuple[str | None, str | None, str | None]:
    """Search Wikipedia and return (extract, title, url) or (None, None, None)."""
    lang_map = {"ru": "ru", "en": "en", "uz": "uz"}
    wiki_lang = lang_map.get(language, "ru")

    # First try known title mapping
    known = _WIKI_TITLES.get(ticker, {})
    candidate_title = known.get(language) or known.get("ru") or known.get("en")

    # Fall back to a search query using the company name
    search_terms = []
    if candidate_title:
        search_terms.append(candidate_title)
    if company_name:
        # Clean up the company name from quoted form
        clean_name = company_name.strip('"').replace('"', "").strip()
        if clean_name not in search_terms:
            search_terms.append(clean_name)

    for term in search_terms:
        result = _fetch_wiki_summary(term, wiki_lang)
        if result:
            return result

    # If primary language failed, try Russian as fallback
    if wiki_lang != "ru":
        for term in search_terms:
            result = _fetch_wiki_summary(term, "ru")
            if result:
                return result

    return None, None, None


def _fetch_wiki_summary(title: str, lang: str) -> tuple[str, str, str] | None:
    """Fetch Wikipedia REST summary for a given title and language code."""
    try:
        encoded = requests.utils.quote(title, safe="")
        url = f"https://{lang}.wikipedia.org/api/rest_v1/page/summary/{encoded}"
        resp = requests.get(url, timeout=8, headers={"User-Agent": "UzStockAnalyzer/1.0"})
        if resp.status_code == 200:
            data = resp.json()
            extract = data.get("extract", "")
            if extract and len(extract) > 40:
                page_url = data.get("content_urls", {}).get("desktop", {}).get("page") or data.get("canonicalurl")
                return extract, data.get("title", title), page_url
    except Exception:
        pass
    return None

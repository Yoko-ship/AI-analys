"""securities_catalog.py — structured securities catalog with Wikipedia caching."""
from __future__ import annotations

import json
import logging
import re
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

logger = logging.getLogger(__name__)

DB_PATH = Path(__file__).parent / "securities.db"

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
    "OCBK": "finance",
    "BRBN": "finance", "BRBNP": "finance",
    "KPBA": "finance",
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
    "MNGM": "mining",
    "UZGFP": "mining",
    "NGQS": "mining",
    "UZIR": "mining", "UZIRP": "mining",
    "PLST": "mining",
    "SANE": "mining",
    "UTGAP": "transport",
    "QATT": "transport",
    "UPOS": "transport",
    "UZTL": "telecom", "UZTLP": "telecom",
    "BTRL": "professional",
    "CBSK": "trade",
    "JASM": "other",
    "TKDMP": "other",
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
    "OCBK":  {"ru": "Октобанк", "en": "Octobank"},
    "BRBN":  {"ru": "Банк развития бизнеса (Узбекистан)", "en": "Business Development Bank of Uzbekistan"},
    "KPBA":  {"ru": "Капиталбанк", "en": "Kapitalbank"},
    "UZTL":  {"ru": "Узбектелеком", "en": "Uzbektelecom"},
    "UZMT":  {"ru": "УзАвто Моторс", "en": "UzAuto Motors"},
    "UZMK":  {"ru": "Узметкомбинат", "en": "Uzmetkombinat"},
    "QZSM":  {"ru": "Кизилкумцемент", "en": "Kizilkumcement"},
    "BECM":  {"ru": "Бекабадцемент", "en": "Bekabadcement"},
    "DORI":  {"ru": "Дори-Дармон", "en": "Dori-Darmon"},
    "AGMKP": {"ru": "Алмалыкский ГМК", "en": "Almalyk Mining and Metallurgical Complex"},
    "BNGP":  {"ru": "Бухоронефтгазпармалаш", "en": "Bukhara Oil and Gas Production"},
}


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


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
    """)
    conn.commit()


# Bonds trade under series codes (BFMT3V2, ACMT2B4, UZUMS3B) rather than the
# issuer's stock ticker, so they never match company_logos.json. Map the
# leading-letter issuer prefix to the issuer's logo instead.
BOND_ISSUER_LOGOS: dict[str, str] = {
    "BFMT": "/logos/plate/BFMT.jpg",  # BIZNES FINANS (self-hosted wordmark)
    "ACMT": "https://www.google.com/s2/favicons?domain=agatcredit.uz&sz=128",  # AGAT CREDIT
    "CTFB": "https://www.google.com/s2/favicons?domain=contactfinance.uz&sz=128",  # CONTACT FINANCE
    "UZUMS": "https://www.google.com/s2/favicons?domain=uzumsarmoya.uz&sz=128",  # UZUM SARMOYA
}


def resolve_logo(ticker: str, logos: dict[str, str]) -> str | None:
    """Resolve a ticker's logo, sharing it across common/preferred share pairs.

    Preferred shares end in ``P`` (the same heuristic used for ``is_preferred``).
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
        if not ticker:
            continue
        sector = _TICKER_SECTORS.get(ticker, "other")
        is_preferred = 1 if s.get("share_type") == "preferred" or ticker.endswith("P") else 0
        conn.execute(
            """
            INSERT INTO securities
                (ticker, isin, name, type, share_type, sector, logo_url, is_preferred,
                 last_price, close_price, last_trade_date, url, updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(ticker) DO UPDATE SET
                isin=excluded.isin,
                name=excluded.name,
                type=excluded.type,
                share_type=excluded.share_type,
                sector=excluded.sector,
                logo_url=excluded.logo_url,
                is_preferred=excluded.is_preferred,
                last_price=excluded.last_price,
                close_price=excluded.close_price,
                last_trade_date=excluded.last_trade_date,
                url=excluded.url,
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
    conn.close()
    result: dict[str, dict] = {}
    for row in rows:
        d = dict(row)
        d["is_preferred"] = bool(d.get("is_preferred"))
        result[d["ticker"]] = d
    return result


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
            return {"ticker": ticker, "title": row["title"], "extract": row["extract"], "page_url": row["page_url"]}

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
    return {"ticker": ticker, "title": title, "extract": extract, "page_url": page_url}


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

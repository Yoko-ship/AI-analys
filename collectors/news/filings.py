"""News filings operations with explicit dependencies."""
from __future__ import annotations
from typing import Any

import collectors.news.facts as collectors_news_facts
import collectors.news.issuers as collectors_news_issuers
import collectors.news.settings as collectors_news_settings
import os


_OPENINFO_ORG_URL = "https://openinfo.uz/ru/organizations/{org}?fact={fact_id}"


_FACT_TYPE_MAP = {
    32: "financial_report",   # начисление доходов по ценным бумагам
    42: "financial_report",   # дивиденды выплаченные
    49: "financial_report",   # рекомендация НС по распределению чистой прибыли
    50: "financial_report",   # дивиденды, выплаченные акционерам
    25: "corporate_event", 26: "corporate_event",   # выпуск ценных бумаг
    46: "corporate_event", 47: "corporate_event",   # листинг / делистинг
    6: "corporate_event", 7: "corporate_event",     # решения высшего органа управления
    8: "corporate_event", 9: "corporate_event",     # изменения в НС / исполнительном органе
    20: "corporate_event", 21: "corporate_event", 22: "corporate_event",  # крупные сделки
    31: "corporate_event", 36: "corporate_event", 37: "corporate_event",
    51: "corporate_event", 52: "corporate_event", 53: "corporate_event",
    15: "corporate_event", 16: "corporate_event", 17: "corporate_event",  # крупные кредиты
    18: "market", 19: "market",                      # изменение стоимости активов >10%
    14: "regulatory", 23: "regulatory", 24: "regulatory", 34: "regulatory",
    27: "regulatory", 28: "regulatory", 29: "regulatory", 30: "regulatory",
}


def fetch_openinfo(source: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    """openinfo material facts — the primary issuer-disclosure channel (§3.11 cats 1–9).

    Reads the newest filings from ``/disclosure/facts/`` (the API returns them newest-first;
    ~21/day across all ~790 filers), keeps those filed by OUR listed issuers via
    ``catalog_companies.org_id``, and collapses same-issuer/same-fact-type/same-day filings
    into one item: O'zbekneftgaz files six affiliate-deal notices in an hour and that is one
    story, not six cards.

    Items come back marked ``always_relevant`` with their tickers already attached — a
    material fact filed by a listed issuer is market news by definition, so it skips the
    prefilter and the triage gate and the model only judges tone/impact and writes the
    summary. All traffic goes through ``openinfo_http`` (paced 350 ms, retries, TLS verify).
    """
    endpoint = os.getenv("OPENINFO_FACTS_ENDPOINT", "/disclosure/facts/").strip()
    pages = max(1, min(int(os.getenv("OPENINFO_FACTS_PAGES", "2")), 6))
    page_size = max(10, min(limit if limit and limit > 10 else 50, 100))
    tickers_by_org = collectors_news_issuers._openinfo_ticker_map()
    if not tickers_by_org:
        # Loud on purpose: this is the highest-value source, and losing it silently for a run
        # looks identical to "no issuer filed anything today".
        collectors_news_settings.logger.error("openinfo facts SKIPPED: no org_id → ticker mapping available, locally or "
                     "from prod. Filings cannot be attributed to a ticker, so nothing is "
                     "collected from the issuer channel this run.")
        return []

    try:
        import openinfo_http
        from collectors.openinfo.settings import OPENINFO_API_BASE
    except ImportError as exc:
        collectors_news_settings.logger.warning("openinfo modules unavailable: %s", exc)
        return []

    base = endpoint if endpoint.startswith("http") else f"{OPENINFO_API_BASE}{endpoint}"
    raw: list[dict[str, Any]] = []
    for page in range(1, pages + 1):
        try:
            resp = openinfo_http.get(base, params={"page_size": page_size, "page": page}, timeout=40)
            resp.raise_for_status()
            batch = (resp.json() or {}).get("results") or []
        except Exception as exc:  # noqa: BLE001 — one bad page must not kill the run
            collectors_news_settings.logger.warning("openinfo facts page %d failed: %s", page, exc)
            break
        raw.extend(batch)
        if len(batch) < page_size:
            break

    # Group: one card per issuer + fact type + day.
    groups: dict[tuple[str, Any, str], dict[str, Any]] = {}
    unmatched: dict[str, int] = {}
    for rec in raw:
        org = str(rec.get("organization") or "")
        tickers = tickers_by_org.get(org)
        if not tickers:
            name = rec.get("organization_short_name") or org
            unmatched[name] = unmatched.get(name, 0) + 1
            continue
        pub = str(rec.get("pub_date") or "").strip()
        key = (org, rec.get("fact_number"), pub[:10])
        group = groups.get(key)
        if group is None:
            groups[key] = {
                "org": org, "tickers": tickers, "count": 1,
                "fact_id": rec.get("id"),
                # Every filing in the group, newest first: the enrichment sums the day's
                # deals, and one anchor id could only ever describe one of them.
                "fact_ids": [rec.get("id")],
                "fact_number": rec.get("fact_number"),
                "short_title": (rec.get("fact_short_title") or rec.get("fact_title") or "").strip(),
                "full_title": (rec.get("fact_title") or "").strip(),
                "org_name": (rec.get("organization_short_name")
                             or rec.get("organization_name") or "").strip(),
                "pub_date": pub,
            }
        else:
            group["count"] += 1
            group["fact_ids"].append(rec.get("id"))
            # keep the newest filing of the group as its anchor
            if pub > str(group["pub_date"]):
                group["pub_date"], group["fact_id"] = pub, rec.get("id")

    items: list[dict[str, Any]] = []
    for g in sorted(groups.values(), key=lambda x: str(x["pub_date"]), reverse=True)[:limit]:
        if not g["short_title"] or not g["org_name"]:
            continue
        suffix = f" ({g['count']})" if g["count"] > 1 else ""
        detail = g["full_title"] if g["full_title"] and g["full_title"] != g["short_title"] else ""
        figures = collectors_news_facts._fact_figures(g["fact_number"], g.get("fact_ids") or [g["fact_id"]])
        items.append({
            "url": _OPENINFO_ORG_URL.format(org=g["org"], fact_id=g["fact_id"]),
            "title": f"{g['org_name']}: {g['short_title']}{suffix}",
            # Filing metadata we publish ourselves — no article body is involved.
            "snippet": collectors_news_facts._filing_snippet(g, detail, figures),
            "published_at": g["pub_date"].replace(" ", "T")[:19] or None,
            "lang": "ru",
            "tickers": g["tickers"],
            "always_relevant": True,
            "type_hint": _FACT_TYPE_MAP.get(g["fact_number"]),
            # Which openinfo fact type this came from — the backfill uses it to tell an item
            # that CAN carry figures from one that never will.
            "fact_number_hint": g["fact_number"],
        })
    collectors_news_settings.logger.info("openinfo facts: %d filings fetched, %d relevant to our issuers "
                "(grouped into %d item(s)); %d filings from %d non-covered filers skipped",
                len(raw), sum(g["count"] for g in groups.values()), len(items),
                sum(unmatched.values()), len(unmatched))
    return items

"""Read authorized sources. Internal adapters never visit the public website."""
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
import hashlib
import json
from urllib.parse import urlsplit

from bs4 import BeautifulSoup


@dataclass
class CollectionBatch:
    materials: list[dict]
    # Only a trusted internal adapter can provide this proof. The import API
    # accepts Material objects, not this in-process type or its authority.
    verified_ids: set[str] = field(default_factory=set)


def _stamp(value):
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed.replace(tzinfo=timezone.utc).isoformat() if parsed.tzinfo is None else parsed.isoformat()


def fetch(source):
    if source.get("authorization_required", False):
        raise ValueError("Source login is required; no alternate access is attempted")
    method = source["method"]
    if method == "internal_news":
        return internal_news(source)
    if method == "internal_market":
        return internal_market(source)
    if method == "internal_analysis":
        return internal_analysis(source)
    if method == "rss":
        return rss(source)
    raise ValueError("This source accepts owner imports; it has no polling adapter")


def internal_news(source):
    import news_store
    items = news_store.get_news_feed(limit=100, days=7, order="recent")
    materials = []
    for item in items:
        if not item.get("published_at") or not item.get("snippet"):
            continue
        materials.append({"source_item_id": str(item["id"]), "canonical_event_id": "news:" + str(item["id"]),
            "title": item["title"], "url": item["url"], "publisher": item["source"],
            "entity": (item.get("tickers") or [""])[0], "published_at": _stamp(item["published_at"]),
            "event_at": None, "excerpt": item["snippet"][:20000], "rights": source["rights"],
            "destination_url": f"https://uzstock.uz/news/{item['id']}", "suggested_rubric": "news"})
    # A classified news card is not independent verification of its claims.
    return CollectionBatch(materials)


def internal_market(source):
    from catalogue import facts, market_store
    rows = facts.get_facts("_collector", "meta")
    raw = next((r.get("value_text") for r in rows if r.get("field") == "market_validation"), None)
    validation = json.loads(raw) if raw else {}
    if validation.get("partial") is not False or not validation.get("trade_date"):
        raise ValueError("A complete validated market session is required")
    day = validation["trade_date"]
    stats = [r for r in market_store.get_all_trade_stats().values() if r["trade_date"] == day]
    if not stats or any(r.get("total_value") is None or r.get("trade_count") is None for r in stats):
        raise ValueError("No complete session rows are available")
    from .permissions import TASHKENT
    closed = day < datetime.now(TASHKENT).date().isoformat() or validation.get("session_closed") is True
    values = {"turnover": sum(r["total_value"] for r in stats), "trades": sum(r["trade_count"] for r in stats), "session_complete": closed, "trade_date": day}
    material = {"source_item_id": day, "canonical_event_id": "market:" + day, "title": f"Итоги торгов · {day}",
                "url": "https://uzse.uz/trade_results/", "publisher": "UZSE / UZStock", "entity": "",
                "published_at": _stamp(max(r["updated_at"] for r in stats)), "event_at": day + "T00:00:00+05:00",
                "excerpt": json.dumps(values, ensure_ascii=False), "data": values, "units": {"turnover": "UZS", "trades": "trades", "session_complete": ""},
                "rights": source["rights"], "destination_url": "https://uzstock.uz/market", "suggested_rubric": "market"}
    return CollectionBatch([material], {day} if closed else set())


def _analysis_groups(refs):
    groups = {}
    for fact in refs:
        fields = ("period_end", "accounting_standard", "consolidation_scope", "currency")
        if any(not isinstance(fact.get(key), str) or not fact[key].strip() for key in fields):
            raise ValueError("An original fact's financial scope is required")
        try:
            period = date.fromisoformat(fact["period_end"]).isoformat()
            start = date.fromisoformat(fact["period_start"]).isoformat() if fact.get("period_start") else ""
            if start and start > period:
                raise ValueError("Original period starts after its end")
        except ValueError as exc:
            raise ValueError("An original fact's financial scope needs an exact period end") from exc
        key = (fact["source_url"], period, fact["accounting_standard"].strip().lower(),
               fact["consolidation_scope"].strip(), fact["currency"].strip().upper(), start, str(fact.get("period_kind") or "").strip().lower())
        groups.setdefault(key, []).append(fact)
    return groups.items()


def internal_analysis(source):
    from reporting import store
    from reporting.links import url as report_url
    with store.connect() as c:
        rows = c.execute("SELECT r.payload FROM sector_publications p JOIN sector_runs r ON r.version=p.version "
                         "WHERE r.status='available' AND r.language=? ORDER BY r.created_at DESC LIMIT 100",
                         (source.get("language", "ru"),)).fetchall()
    materials, verified = [], set()
    for row in rows:
        report = json.loads(row["payload"])
        if report.get("source_refresh_failed") or (report.get("text_checks") or {}).get("status") != "passed":
            continue
        ticker = report["issuer"]["ticker"]
        refs = [r for r in report.get("verified_facts", []) if r.get("verification_status") == "verified" and r.get("source_url")]
        if not refs or not report.get("short_summary"):
            continue
        for identity, group in _analysis_groups(refs):
            original_url, period, standard, scope, currency, period_start, period_kind = identity
            if any(not r.get("source_published_at") for r in group):
                raise ValueError("An original filing publication date is required; report generation time is different")
            dates = {_stamp(r["source_published_at"]) for r in group}
            if len(dates) != 1:
                raise ValueError("The original filing publication dates disagree")
            event = f"analysis:{ticker}:{report['standard']}:{report['period']}"
            # One filing can contain current and comparative periods. Neither
            # the report's latest date nor dict overwrite may merge those facts.
            key = event + ":" + hashlib.sha256(json.dumps(identity).encode()).hexdigest()[:12]
            values = {}
            for fact in group:
                field = fact["metric_code"]
                value = (fact.get("raw", fact.get("value")), fact.get("unit_raw", fact.get("unit", "")))
                if field in values and values[field] != value:
                    raise ValueError("The original contains conflicting values for the same metric and financial scope")
                values[field] = value
            data = {r["metric_code"]: r.get("raw", r.get("value")) for r in group if r.get("raw", r.get("value")) is not None}
            extract = [{"line": r.get("source_original_line") or r["metric_code"], "field": r["metric_code"],
                        "value": data.get(r["metric_code"]), "unit": r.get("unit_raw", r.get("unit", "")),
                        "location": r.get("source_location", {})} for r in group]
            materials.append({"source_item_id": key, "canonical_event_id": event,
                "title": report["headline"], "url": original_url, "publisher": ticker, "entity": ticker,
                "published_at": dates.pop(), "event_at": _stamp(report["generated_at"]),
                "excerpt": json.dumps({"extracted_original_lines": extract}, ensure_ascii=False)[:20000],
                "data": {**data, "analysis_ready": True}, "units": {r["metric_code"]: r.get("unit_raw", r.get("unit", "")) for r in group},
                "period": period, "standard": standard, "scope": scope, "currency": currency,
                "period_start": period_start, "period_kind": period_kind,
                "rights": source["rights"], "destination_url": report_url(report),
                "suggested_rubric": "quarterly", "analysis_version": report["version"]})
            verified.add(key)
    return CollectionBatch(materials, verified)


def rss_url_check(url):
    import public_fetch
    if (urlsplit(url).hostname or "").lower() in {"uzstock.uz", "www.uzstock.uz"}:
        raise ValueError("Use an internal UZStock source instead of public crawling")
    public_fetch.check_url(url, schemes=("https",))


def rss(source):
    import feedparser
    import public_fetch
    import requests
    # Reject even when a caller injects a fetch test adapter.
    if (urlsplit(source["url"]).hostname or "").lower() in {"uzstock.uz", "www.uzstock.uz"}:
        raise ValueError("Use an internal UZStock source instead of public crawling")
    with requests.Session() as session:
        response = public_fetch.fetch(session, source["url"], max_bytes=2_000_000, timeout=(5, 20), check=rss_url_check)
    if response.status_code != 200:
        raise ValueError("The source did not return a usable feed")
    feed = feedparser.parse(response.content)
    if feed.bozo and not feed.entries:
        raise ValueError("Invalid feed document")
    materials = []
    for entry in feed.entries[:100]:
        stamp = entry.get("published_parsed") or entry.get("updated_parsed")
        if not stamp or not entry.get("link"):
            continue
        published = datetime(*stamp[:6], tzinfo=timezone.utc).isoformat()
        key = str(entry.get("id") or entry.link)[:200]
        materials.append({"source_item_id": key, "canonical_event_id": "rss:" + hashlib.sha256(entry.link.encode()).hexdigest(),
            "title": entry.get("title", "Material")[:500], "url": entry.link, "publisher": source["name"],
            "published_at": published, "excerpt": BeautifulSoup(entry.get("summary", entry.get("title", "")), "html.parser").get_text(" ", strip=True)[:20000],
            "rights": source["rights"], "data": {}})
    return CollectionBatch(materials)

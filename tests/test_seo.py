"""Crawler-facing shell: per-URL meta tags, a text snapshot, robots and sitemap."""

import asyncio
import json
import re

from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

import api
import server.bonds.routes as bonds_routes
import server.company.routes as company_routes
import server.market.routes as market_routes
import server.seo as seo
import news_store

SHELL = ('<!doctype html><html lang="ru"><head><meta charset="UTF-8" />'
         '<title>UZStock</title><script type="module" src="/assets/index.js"></script></head>'
         '<body><div id="root"></div><script>theme()</script></body></html>')


def _client(tmp_path, monkeypatch):
    (tmp_path / "index.html").write_text(SHELL, encoding="utf-8")
    monkeypatch.setattr(api, "WEB_DIR", tmp_path)
    seo._cache.clear()
    return TestClient(api.app)


def _fake_company(monkeypatch, calls=None):
    async def info(ticker, language="ru"):
        if calls is not None:
            calls.append(ticker)
        if ticker != "UZTL":
            raise company_routes.HTTPException(status_code=404)
        return {"ok": True, "security": {
            "ticker": "UZTL", "isin": "UZ7047110000", "type": "stock", "share_type": "ordinary",
            "company_name": "\"O'zbektelekom\" <AK>", "sector": "telecom", "last_price": 17999.0,
            "last_trade_date": "2026-10-09", "market_cap": 14192315150331.78,
            "shares_outstanding": 818339529.0, "logo_url": "/logos/UZTL.png"},
            "wiki": {"title": "Uztelecom", "extract": "Uztelecom — оператор связи </script>."}}

    async def financials(ticker=None):
        return {"ok": True, "financials": {"UZTL": {
            "year": 2026, "period_months": 6, "revenue": 5.77e12, "net_income": 8.96e11,
            "prior": {"revenue": 5.12e12, "net_income": 1.0e10},
            "annual": {"year": 2025, "period_months": 12, "revenue": 1.05e13, "net_income": 5.9e11,
                       "total_assets": 1.35e13, "total_equity": 3.03e12}}}}

    async def multiples(request, view="full", ticker=None):
        return JSONResponse({"items": [{"ticker": "UZTL", "pe": {"value": 12.5, "status": "ok"},
                                        "pb": {"value": 3.1, "status": "unverified"},
                                        "roe": {"value": 45.0, "status": "ok"}}]})

    monkeypatch.setattr(company_routes, "api_securities_info", info)
    monkeypatch.setattr(market_routes, "api_market_financials", financials)
    monkeypatch.setattr(market_routes, "api_market_multiples", multiples)


def _ldjson(text):
    return [json.loads(m) for m in re.findall(r'<script type="application/ld\+json">(.*?)</script>', text)]


def test_company_page_carries_its_own_title_meta_and_snapshot(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    _fake_company(monkeypatch)
    page = client.get("/company/uztl")
    assert page.status_code == 200
    text = page.text
    assert "<title>Uztelecom (UZTL) — акции, цена, отчётность, P/E | UZStock</title>" in text
    assert '<link rel="canonical" href="https://uzstock.uz/company/UZTL" />' in text
    assert 'name="description"' in text and "Капитализация 14,19 трлн сум" in text
    # The snapshot sits inside #root, where React's first render replaces it,
    # and the app's own scripts are untouched.
    root = text.split('<div id="root">', 1)[1]
    assert root.index("<h1>") < root.index("</div><script>theme()</script>")
    assert '<script type="module" src="/assets/index.js"></script>' in text
    assert "17 999,00 сум (09.10.2026)" in text
    assert "<td>12,50</td>" in text            # P/E, status ok
    assert "P/B" not in root                   # an unverified multiple is withheld
    assert "Выручка за 6 мес. 2026 г." in text and "+12,7% г/г" in text
    assert "Собственный капитал на конец 2025 года" in text
    # Names and extracts are escaped — no markup from the data reaches the page.
    assert "<AK>" not in text and "</script>." not in text
    blocks = _ldjson(text)
    corp = next(b for b in blocks if b["@type"] == "Corporation")
    assert corp["tickerSymbol"] == "UZTL" and corp["identifier"]["value"] == "UZ7047110000"
    assert any(b["@type"] == "BreadcrumbList" for b in blocks)


def test_company_snapshot_is_cached(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    calls = []
    _fake_company(monkeypatch, calls)
    client.get("/company/UZTL")
    client.get("/company/UZTL")
    assert calls == ["UZTL"]


def test_unknown_ticker_and_failures_fall_back_to_the_generic_shell(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    _fake_company(monkeypatch)
    page = client.get("/company/NOPE")
    assert page.status_code == 200 and f"<title>{seo.DEFAULT_TITLE}</title>" in page.text

    async def broken(*args, **kwargs):
        raise RuntimeError("store down")
    monkeypatch.setattr(company_routes, "api_securities_info", broken)
    seo._cache.clear()
    page = client.get("/company/UZTL")
    assert page.status_code == 200 and '<div id="root">' in page.text


def test_render_failure_serves_the_bare_shell(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)

    def boom(*args, **kwargs):
        raise RuntimeError("template")
    monkeypatch.setattr(seo, "render", boom)
    page = client.get("/market")
    assert page.status_code == 200 and page.text == SHELL


def test_static_and_private_pages(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    market = client.get("/market").text
    assert "<title>Акции Узбекистана — котировки UZSE сегодня | UZStock</title>" in market
    home = client.get("/").text
    assert {b["@type"] for b in _ldjson(home)} >= {"WebSite", "Organization"}
    for path in ("/admin", "/profile", "/login"):
        text = client.get(path).text
        assert '<meta name="robots" content="noindex, nofollow" />' in text, path
        assert "canonical" not in text, path


def test_bond_page(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)

    async def bonds(request):
        return JSONResponse({"items": [{
            "ticker": "ACMT1B2", "isin": "UZ6058977AB6", "issuer": "<AGAT CREDIT>", "price": 100000.01,
            "last_trade_date": "2026-10-09", "price_pct": {"value": 100.0, "status": "ok"},
            "ytm": {"value": 27.4, "status": "ok"},
            "reference": {"coupon_rate": 28.0, "maturity_date": "2027-07-23", "nominal": 100000}}]})
    monkeypatch.setattr(bonds_routes, "api_bonds", bonds)
    text = client.get("/bond/acmt1b2").text
    assert "<title>Облигация ACMT1B2 — «AGAT CREDIT»: купон, доходность, цена | UZStock</title>" in text
    assert "100 000,01 сум" in text and "100,00% от номинала" in text
    assert "28,00% годовых" in text and "23.07.2027" in text and "27,40%" in text


def test_news_page(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    monkeypatch.setattr(news_store, "get_news_item", lambda news_id: {
        "id": news_id, "title_ru": "UZTL отчитался", "summary_ru": "Выручка выросла.",
        "published_at": "2026-09-11T18:08:33", "source": "openinfo.uz", "url": "https://openinfo.uz/x",
        "tickers": ["UZTL"]} if news_id == 7 else None)
    text = client.get("/news/7").text
    assert "<title>UZTL отчитался | UZStock</title>" in text
    assert '<a href="/company/UZTL">UZTL</a>' in text
    article = next(b for b in _ldjson(text) if b["@type"] == "NewsArticle")
    assert article["datePublished"] == "2026-09-11T18:08:33"
    assert f"<title>{seo.DEFAULT_TITLE}</title>" in client.get("/news/8").text
    assert f"<title>{seo.DEFAULT_TITLE}</title>" in client.get("/news/abc").text


def test_robots_txt_allows_search_and_ai_crawlers(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    robots = client.get("/robots.txt")
    assert robots.status_code == 200 and robots.headers["content-type"].startswith("text/plain")
    body = robots.text
    for bot in ("GPTBot", "OAI-SearchBot", "ClaudeBot", "PerplexityBot", "Google-Extended"):
        assert f"User-agent: {bot}" in body
    assert "Disallow: /api/" in body and "Disallow: /admin" in body
    assert "Disallow: /\n" not in body
    assert "Sitemap: https://uzstock.uz/sitemap.xml" in body


def test_sitemap_lists_pages_companies_bonds_and_news(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)

    async def instruments(request, include_inactive=True):
        return JSONResponse({"items": [
            {"ticker": "UZTL", "type": "stock", "is_active": True, "last_trade_date": "2026-10-09"},
            {"ticker": "ACMT1B2", "type": "bond", "is_active": True, "last_trade_date": None},
            {"ticker": "BAD/../X", "type": "stock"}]})
    monkeypatch.setattr(market_routes, "api_instruments", instruments)
    monkeypatch.setattr(news_store, "get_news_feed",
                        lambda **kw: [{"id": 393, "published_at": "2026-09-11T18:08:33"}])
    response = client.get("/sitemap.xml")
    assert response.status_code == 200 and response.headers["content-type"].startswith("application/xml")
    xml = response.text
    assert "<loc>https://uzstock.uz/market</loc>" in xml
    assert "<loc>https://uzstock.uz/company/UZTL</loc><lastmod>2026-10-09</lastmod>" in xml
    assert "<loc>https://uzstock.uz/bond/ACMT1B2</loc>" in xml
    assert "<loc>https://uzstock.uz/news/393</loc><lastmod>2026-09-11</lastmod>" in xml
    assert "BAD" not in xml


def test_slow_snapshot_times_out_but_keeps_filling(monkeypatch):
    monkeypatch.setattr(seo, "_DATA_TIMEOUT", 0.05)
    seo._cache.clear()

    async def scenario():
        async def slow():
            await asyncio.sleep(0.2)
            return "value"
        try:
            await seo._cached("k", slow)
        except asyncio.TimeoutError:
            pass
        else:
            raise AssertionError("expected a timeout")
        await asyncio.sleep(0.3)
        return await seo._cached("k", slow)

    assert asyncio.run(scenario()) == "value"

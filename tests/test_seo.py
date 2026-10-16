"""Crawler-facing shell: per-URL meta tags, a text snapshot, robots and sitemap."""

import asyncio
import json
import re
import struct
from pathlib import Path

from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

import api
import server.bonds.routes as bonds_routes
import server.company.routes as company_routes
import server.market.routes as market_routes
import server.seo.routes as seo
import news_store

SHELL = ('<!doctype html><html lang="ru"><head><meta charset="UTF-8" />'
         '<title>UZStock</title><script type="module" src="/assets/index.js"></script></head>'
         '<body><div id="root"></div><script>theme()</script></body></html>')


def _client(tmp_path, monkeypatch):
    (tmp_path / "index.html").write_text(SHELL, encoding="utf-8")
    monkeypatch.setattr(api, "WEB_DIR", tmp_path)
    seo._cache.clear()

    # The list pages read these; a test that needs rows fakes them again.
    async def no_rows(*args, **kwargs):
        return JSONResponse({"stocks": [], "items": []})
    monkeypatch.setattr(market_routes, "api_market_stocks", no_rows)
    monkeypatch.setattr(bonds_routes, "api_bonds", no_rows)
    monkeypatch.setattr(news_store, "get_news_feed", lambda **kw: [])
    return TestClient(api.app)


def _fake_boards(monkeypatch):
    async def stocks(request, type=None, refresh=False):
        return JSONResponse({"stocks": [
            {"ticker": "SQBN", "name": "\"O'zsanoatqurilishbank\" ATB", "last_price": 9.5,
             "last_trade_date": "2026-10-13", "market_cap": 2.4e12},
            {"ticker": "UZTL", "name": "\"O'zbektelekom\" <AK>", "last_price": 17999.0,
             "last_trade_date": "2026-10-09", "market_cap": 1.419e13},
            {"ticker": "QUIET", "name": "Quiet", "last_price": None, "market_cap": None},
            {"ticker": "BAD/../X", "name": "Bad"}]})

    async def bonds(request):
        return JSONResponse({"items": [{"ticker": "ACMT1B2", "issuer": "AGAT CREDIT",
                                        "reference": {"coupon_rate": 28.0, "maturity_date": "2027-07-23"}}]})
    monkeypatch.setattr(market_routes, "api_market_stocks", stocks)
    monkeypatch.setattr(bonds_routes, "api_bonds", bonds)


def _fake_company(monkeypatch, calls=None, languages=None):
    async def info(ticker, language="ru"):
        if calls is not None:
            calls.append(ticker)
        if languages is not None:
            languages.append(language)
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


def _is_not_found(page):
    return (page.status_code == 404 and '<meta name="robots" content="noindex, nofollow" />' in page.text
            and "<title>Страница не найдена | UZStock</title>" in page.text
            and '<script type="module" src="/assets/index.js"></script>' in page.text)


def test_unknown_ticker_is_404_but_a_failing_store_is_not(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    _fake_company(monkeypatch)
    assert _is_not_found(client.get("/company/NOPE"))

    # A store that fails says nothing about whether the company exists: the
    # page keeps its 200, and the failure is not cached as a missing company.
    async def broken(*args, **kwargs):
        raise company_routes.HTTPException(status_code=500, detail="store down")
    monkeypatch.setattr(company_routes, "api_securities_info", broken)
    seo._cache.clear()
    page = client.get("/company/UZTL")
    assert page.status_code == 200 and f"<title>{seo.DEFAULT_TITLE}</title>" in page.text
    _fake_company(monkeypatch)
    assert "Uztelecom (UZTL)" in client.get("/company/UZTL").text


def test_paths_the_app_has_no_page_for_are_404(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    for path in ("/site.webmanifest", "/wp-login.php", "/company", "/marketx", "/market/extra"):
        assert _is_not_found(client.get(path)), path


def test_every_route_the_app_opens_is_not_404(tmp_path, monkeypatch):
    # Read from the app's own route table, so a page added there cannot start
    # answering 404 to crawlers unnoticed.
    client = _client(tmp_path, monkeypatch)
    routing = (Path(__file__).resolve().parents[1] / "frontend/src/app/routing.jsx").read_text(encoding="utf-8")
    table = re.search(r"const VIEW_PATHS = \{(.*?)\};", routing, re.S).group(1)
    paths = re.findall(r'^\s*\w+:\s*"(/[^"]*)"', table, re.M)
    assert {"/", "/market", "/feedback", "/currency", "/admin"} <= set(paths)
    for path in paths + ["/bonds", "/market/", "/admin/users", "/chart/UZTL", "/news/announcement/5"]:
        assert client.get(path).status_code == 200, path
    bonds = client.get("/bonds").text
    assert '<link rel="canonical" href="https://uzstock.uz/market" />' in bonds


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
    assert "<title>Акции компаний Узбекистана — котировки UZSE сегодня | UZStock</title>" in market
    home = client.get("/").text
    assert {b["@type"] for b in _ldjson(home)} >= {"WebSite", "Organization"}
    org = next(b for b in _ldjson(home) if b["@type"] == "Organization")
    assert org["logo"] == f"https://uzstock.uz{seo.LOGO_PATH}"
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
    assert _is_not_found(client.get("/bond/NOPE1B1"))

    # An empty board cannot tell a missing bond from a failed read.
    async def empty(request):
        return JSONResponse({"items": []})
    monkeypatch.setattr(bonds_routes, "api_bonds", empty)
    seo._cache.clear()
    assert client.get("/bond/NOPE1B1").status_code == 200


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
    assert _is_not_found(client.get("/news/8"))
    assert _is_not_found(client.get("/news/abc"))

    def down(news_id):
        raise RuntimeError("db locked")
    monkeypatch.setattr(news_store, "get_news_item", down)
    seo._cache.clear()
    assert client.get("/news/7").status_code == 200


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


def _fake_ai_report(monkeypatch, report, calls=None):
    import issuer_analysis_api

    def ai_report(issuer_id, **kwargs):
        if calls is not None:
            calls.append((issuer_id, kwargs))
        if report is None:
            raise issuer_analysis_api.HTTPException(status_code=404)
        return report

    monkeypatch.setattr(issuer_analysis_api, "issuer_ai_report", ai_report)


def test_shared_ai_report_link_previews_the_reports_own_headline(tmp_path, monkeypatch):
    _fake_company(monkeypatch)
    calls = []
    _fake_ai_report(monkeypatch, {
        "ok": True, "status": "available", "period_label": "9 месяцев 2026 года",
        "headline": "Выручка выросла на 12%, и чистая прибыль увеличилась на 8%.",
        "verdict_line": "Вердикт: улучшение — растут и выручка, и прибыль."}, calls)
    html = _client(tmp_path, monkeypatch).get("/company/uztl?report=ai").text
    assert "<title>AI-финансовый отчёт UZTL · 9 месяцев 2026 года | UZStock</title>" in html
    assert ('<meta property="og:description" content="Выручка выросла на 12%, и чистая прибыль '
            'увеличилась на 8%. Вердикт: улучшение — растут и выручка, и прибыль." />') in html
    # Still the company page for search: one canonical, nothing new indexed.
    assert '<link rel="canonical" href="https://uzstock.uz/company/UZTL" />' in html
    assert calls == [("UZTL", {"standard": "nsbu", "period": None, "scope": "separate", "lang": "ru", "summary": True})]


def test_report_link_without_an_analysis_keeps_the_company_card(tmp_path, monkeypatch):
    _fake_company(monkeypatch)
    _fake_ai_report(monkeypatch, None)
    html = _client(tmp_path, monkeypatch).get("/company/UZTL?report=ai").text
    assert "<title>Uztelecom (UZTL) — акции, цена, отчётность, P/E | UZStock</title>" in html


def test_plain_company_link_does_not_load_the_analysis(tmp_path, monkeypatch):
    _fake_company(monkeypatch)
    calls = []
    _fake_ai_report(monkeypatch, {"status": "available", "headline": "x"}, calls)
    _client(tmp_path, monkeypatch).get("/company/UZTL")
    assert calls == []


def test_organization_logo_is_a_size_google_accepts():
    # Google ignores an organisation logo under 112×112; the 96-px favicon was.
    logo = Path(__file__).resolve().parents[1] / "frontend/public" / seo.LOGO_PATH.lstrip("/")
    head = logo.read_bytes()[:24]
    assert head[:8] == b"\x89PNG\r\n\x1a\n"
    width, height = struct.unpack(">II", head[16:24])
    assert width >= 112 and height >= 112 and width == height


# --------------------------------------------------------------------------- lists

def test_market_page_lists_every_company_by_size_with_links(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    _fake_boards(monkeypatch)
    text = client.get("/market").text
    root = text.split('<div id="root">', 1)[1]
    assert "<h1>Акции компаний Узбекистана — котировки UZSE сегодня</h1>" in root
    assert "Акции 3 компаний Узбекистана" in root
    links = re.findall(r'<a href="(/company/[A-Z0-9]+)">', root)
    # Largest first; a company without a capitalisation still gets its link.
    assert links == ["/company/UZTL", "/company/SQBN", "/company/QUIET"]
    assert "14,19 трлн сум" in root and "Телекоммуникации" in root
    assert "&lt;AK&gt;" not in root and "<AK>" not in root and "«AK»" in root
    assert "BAD" not in root
    assert '<a href="/bond/ACMT1B2">ACMT1B2</a>' in root and "28,00% годовых" in root


def test_market_page_keeps_its_title_when_the_board_fails(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)

    async def down(*args, **kwargs):
        raise RuntimeError("board down")
    monkeypatch.setattr(market_routes, "api_market_stocks", down)
    monkeypatch.setattr(bonds_routes, "api_bonds", down)
    page = client.get("/market")
    assert page.status_code == 200
    assert "<title>Акции компаний Узбекистана — котировки UZSE сегодня | UZStock</title>" in page.text


def test_home_page_lists_the_largest_companies_and_latest_news(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    _fake_boards(monkeypatch)
    monkeypatch.setattr(news_store, "get_news_feed",
                        lambda **kw: [{"id": 393, "title_ru": "UZTL отчитался"}])
    root = client.get("/").text.split('<div id="root">', 1)[1]
    assert root.index("/company/UZTL") < root.index("/company/SQBN")
    assert '<a href="/news/393">UZTL отчитался</a>' in root
    uz = client.get("/uz").text.split('<div id="root">', 1)[1]
    assert '<a href="/uz/company/UZTL">' in uz
    assert "/news/393" not in uz           # the news is Russian; the Uzbek page does not borrow it


# --------------------------------------------------------------------------- languages

def test_every_language_has_every_text():
    for lang in seo.URL_LANGUAGES:
        assert seo._TX[lang].keys() == seo._TX["ru"].keys(), lang
        assert seo._PAGES[lang].keys() == seo._STATIC_PAGES.keys(), lang
        assert seo._SECTORS[lang].keys() == seo.SECTOR_NAMES.keys(), lang
        assert lang in seo._OG_LOCALE and lang in seo._LANGUAGE_NAMES


def test_language_prefix_is_a_whole_path_segment():
    assert seo.split_language("/uz") == ("uz", "/")
    assert seo.split_language("/uz/company/AGBA") == ("uz", "/company/AGBA")
    assert seo.split_language("/uzbek") == ("ru", "/uzbek")
    assert seo.localized("/", "uz") == "/uz" and seo.localized("/market", "ru") == "/market"


def test_uzbek_company_page(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    languages = []
    _fake_company(monkeypatch, languages=languages)
    page = client.get("/uz/company/UZTL")
    assert page.status_code == 200
    text = page.text
    assert "<title>Uztelecom (UZTL) — aksiyalar, narx, hisobot, P/E | UZStock</title>" in text
    assert '<html lang="uz">' in text and 'content="uz_UZ"' in text
    assert '<link rel="canonical" href="https://uzstock.uz/uz/company/UZTL" />' in text
    for lang, url in (("ru", "/company/UZTL"), ("uz", "/uz/company/UZTL"), ("x-default", "/company/UZTL")):
        assert f'<link rel="alternate" hreflang="{lang}" href="https://uzstock.uz{url}" />' in text
    root = text.split('<div id="root">', 1)[1]
    assert "Kapitallashuv 14,19 trln so‘m" in root and "Telekommunikatsiyalar" in root
    assert "Asosiy ko‘rsatkichlar" in root and "сум" not in root
    assert '<a href="/uz/market">' in root and '<a href="/uz/chart/UZTL">' in root
    assert '<a href="/" hreflang="ru">Русский</a>' in root
    assert "uz" in languages                # the Wikipedia extract is asked for in Uzbek

    ru = client.get("/company/UZTL").text
    assert '<html lang="ru">' in ru
    assert '<link rel="alternate" hreflang="uz" href="https://uzstock.uz/uz/company/UZTL" />' in ru
    assert '<a href="/uz" hreflang="uz">O‘zbekcha</a>' in ru


def test_uzbek_static_missing_and_private_pages(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    for path, (title, _) in seo._STATIC_PAGES_UZ.items():
        page = client.get(seo.localized(path, "uz"))
        assert page.status_code == 200 and f"<title>{title}</title>" in page.text, path
    assert client.get("/uz/feedback").status_code == 200
    missing = client.get("/uz/nope")
    assert missing.status_code == 404 and "<title>Sahifa topilmadi | UZStock</title>" in missing.text
    assert client.get("/uzbek").status_code == 404
    admin = client.get("/uz/admin").text
    assert '<meta name="robots" content="noindex, nofollow" />' in admin and "hreflang" not in admin


def test_uzbek_news_link_points_at_the_russian_story(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    monkeypatch.setattr(news_store, "get_news_item", lambda news_id: {
        "id": news_id, "title_ru": "UZTL отчитался", "summary_ru": "Выручка выросла."})
    text = client.get("/uz/news/7").text
    assert '<link rel="canonical" href="https://uzstock.uz/news/7" />' in text
    assert "hreflang=\"uz\" href" not in text


def test_robots_and_sitemap_cover_the_uzbek_pages(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    robots = client.get("/robots.txt").text
    assert "Disallow: /uz/admin" in robots and "Disallow: /uz/login" in robots

    async def instruments(request, include_inactive=True):
        return JSONResponse({"items": [{"ticker": "UZTL", "type": "stock", "is_active": True}]})
    monkeypatch.setattr(market_routes, "api_instruments", instruments)
    monkeypatch.setattr(news_store, "get_news_feed", lambda **kw: [{"id": 393}])
    xml = client.get("/sitemap.xml").text
    for path in ("/uz", "/uz/market", "/uz/company/UZTL", "/company/UZTL", "/news/393"):
        assert f"<loc>https://uzstock.uz{path}</loc>" in xml, path
    assert "/uz/news/393" not in xml


def test_random_paths_cannot_grow_the_page_cache(tmp_path, monkeypatch):
    # Cache keys come from the URL. Probing random story ids used to add a
    # fresh entry per path, swept only once they had expired.
    client = _client(tmp_path, monkeypatch)
    monkeypatch.setattr(seo, "_cache", seo._PageDataCache(limit=20, miss_limit=5))
    monkeypatch.setattr(news_store, "get_news_item", lambda news_id: {
        "id": news_id, "title_ru": "UZTL отчитался", "summary_ru": "Выручка выросла.",
        "published_at": "2026-09-11T18:08:33", "tickers": []} if news_id == 7 else None)
    assert client.get("/news/7").status_code == 200
    for probe in range(1000, 1200):
        assert _is_not_found(client.get(f"/news/{probe}"))
    assert len(seo._cache) <= 20 and len(seo._cache._misses) <= 5

    # The real page kept its place: with the store down it is still served from
    # the cache, so the misses never pushed it out.
    def down(news_id):
        raise RuntimeError("db locked")
    monkeypatch.setattr(news_store, "get_news_item", down)
    assert "<title>UZTL отчитался | UZStock</title>" in client.get("/news/7").text


def test_the_page_cache_evicts_the_least_recent_and_drops_expired():
    cache = seo._PageDataCache(limit=3, miss_limit=2)
    for key in ("a", "b", "c"):
        cache.put(key, {"page": key}, expires_at=100.0)
    assert cache.get("a", now=1.0)  # touched, so "b" is now the least recent
    cache.put("d", {"page": "d"}, expires_at=100.0)
    assert "b" not in cache and all(k in cache for k in ("a", "c", "d"))
    for key in ("x", "y", "z"):
        cache.put(key, None, expires_at=100.0)
    assert sum(k in cache for k in ("x", "y", "z")) == 2 and len(cache) == 3
    assert cache.get("a", now=200.0) is None and "a" not in cache


def test_list_links_carry_only_url_safe_tickers():
    rows = [{"ticker": "UZTL", "name": "Uzbektelecom"}, {"ticker": 'X"><b>', "name": "Odd"}]
    for table, prefix in ((seo._stocks_table, "/company/"), (seo._bonds_table, "/bond/")):
        out = table(rows, "ru")
        assert f'<a href="{prefix}UZTL">' in out
        assert "<b>" not in out and "X&quot;" not in out

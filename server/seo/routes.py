"""What a crawler reads before any JavaScript runs.

The site is a single-page app: every URL used to answer with the same empty
``<div id="root"></div>`` and the same title. Google renders JavaScript late
and unreliably; the AI crawlers (GPTBot, ClaudeBot, PerplexityBot) do not run
it at all, so to them every company page was blank.

This module fills the shell per URL — its own title, description, canonical
link, Open Graph tags, JSON-LD, and a plain-HTML snapshot of the page's key
facts inside ``#root``. React's ``createRoot`` replaces that snapshot on its
first render, so a visitor sees the app exactly as before. The numbers come
from the same handlers the app's own API calls, never a second computation.

Nothing here may break a page: any failure or slow read falls back to the
route's static title and the bare shell.
"""

from __future__ import annotations

import asyncio
import html
import json
import math
import os
import re
import time
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Awaitable, Callable

from fastapi import APIRouter
from fastapi.responses import PlainTextResponse, Response
from starlette.requests import Request

import server.http as http

router = APIRouter()

SITE_URL = os.getenv("PUBLIC_SITE_URL", "https://uzstock.uz").rstrip("/")
SITE_NAME = "UZStock"
DEFAULT_TITLE = "UZStock — фондовый рынок Узбекистана"
DEFAULT_DESCRIPTION = (
    "Котировки акций и облигаций Ташкентской фондовой биржи (UZSE), финансовая "
    "отчётность эмитентов, мультипликаторы P/E и P/B, дивиденды и новости рынка Узбекистана."
)

# Pages a search result should never point at.
_PRIVATE_PREFIXES = ("/admin", "/profile", "/login")

_STATIC_PAGES: dict[str, tuple[str, str]] = {
    "/": (DEFAULT_TITLE, DEFAULT_DESCRIPTION),
    "/market": (
        "Акции Узбекистана — котировки UZSE сегодня | UZStock",
        "Все акции и облигации Ташкентской фондовой биржи: цены, изменения, обороты, "
        "капитализация, P/E, P/B и ROE эмитентов.",
    ),
    "/heatmap": (
        "Тепловая карта рынка акций Узбекистана | UZStock",
        "Карта изменений цен акций UZSE по секторам и капитализации.",
    ),
    "/catalog": (
        "Финансовая отчётность эмитентов Узбекистана | UZStock",
        "Каталог годовой и квартальной отчётности акционерных обществ Узбекистана "
        "по НСБУ и МСФО.",
    ),
    "/news": (
        "Новости фондового рынка Узбекистана | UZStock",
        "Корпоративные события, раскрытия эмитентов и экономические новости Узбекистана.",
    ),
    "/currency": (
        "Курсы валют в банках Узбекистана | UZStock",
        "Курсы покупки и продажи доллара, евро и рубля в коммерческих банках Узбекистана "
        "и официальный курс ЦБ.",
    ),
}

SECTOR_NAMES = {
    "finance": "Финансы", "funds": "Фонды", "energy": "Энергетика",
    "manufacturing": "Промышленность", "mining": "Добыча", "telecom": "Телекоммуникации",
    "transport": "Транспорт", "logistics": "Логистика", "trade": "Торговля",
    "professional": "Профессиональные услуги",
}

_CACHE_TTL = 600.0
_DATA_TIMEOUT = 6.0
_cache: dict[str, tuple[float, Any]] = {}
_pending: dict[str, asyncio.Task] = {}


@dataclass
class PageMeta:
    title: str = DEFAULT_TITLE
    description: str = DEFAULT_DESCRIPTION
    canonical: str | None = None
    noindex: bool = False
    og_type: str = "website"
    image: str | None = None
    jsonld: list[dict[str, Any]] = field(default_factory=list)
    body: str = ""


# --------------------------------------------------------------------------- helpers

def _esc(value: Any) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


def _num(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _fmt_num(value: Any, digits: int = 0) -> str:
    number = _num(value)
    if number is None:
        return "—"
    return f"{number:,.{digits}f}".replace(",", "\u00a0").replace(".", ",")


def _fmt_money(value: Any) -> str:
    """Sums in UZS, read the way a Russian financial page writes them."""
    number = _num(value)
    if number is None:
        return "—"
    for scale, unit in ((1e12, "трлн"), (1e9, "млрд"), (1e6, "млн")):
        if abs(number) >= scale:
            return f"{_fmt_num(number / scale, 2)} {unit} сум"
    return f"{_fmt_num(number)} сум"


def _fmt_date(value: Any) -> str | None:
    text = str(value or "")[:10]
    try:
        return date.fromisoformat(text).strftime("%d.%m.%Y")
    except ValueError:
        return None


def _clean_name(name: Any) -> str:
    text = re.sub(r"\s+", " ", str(name or "")).strip()
    return text.replace("<", "«").replace(">", "»")


def _clip(text: str, limit: int = 160) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rsplit(" ", 1)[0].rstrip(",.;: ") + "…"


def _json_body(response: Any) -> dict[str, Any]:
    if isinstance(response, dict):
        return response
    body = getattr(response, "body", None)
    return json.loads(body) if body else {}


def _internal_request() -> Request:
    return Request({"type": "http", "method": "GET", "path": "/", "headers": [], "query_string": b""})


async def _cached(key: str, loader: Callable[[], Awaitable[Any]]) -> Any:
    hit = _cache.get(key)
    now = time.monotonic()
    if hit and hit[0] > now:
        return hit[1]
    task = _pending.get(key)
    if task is None:
        async def fill() -> Any:
            try:
                value = await loader()
                _cache[key] = (time.monotonic() + _CACHE_TTL, value)
                return value
            finally:
                _pending.pop(key, None)
        task = _pending[key] = asyncio.ensure_future(fill())
        task.add_done_callback(lambda t: t.cancelled() or t.exception())
    if len(_cache) > 2000:
        for stale in [k for k, (exp, _) in _cache.items() if exp <= now]:
            _cache.pop(stale, None)
    # A slow read times out this response only: the fill keeps running and the
    # crawler's next visit is served from the cache it leaves behind.
    return await asyncio.wait_for(asyncio.shield(task), timeout=_DATA_TIMEOUT)


def _metric(row: dict[str, Any] | None, key: str) -> float | None:
    metric = (row or {}).get(key)
    if isinstance(metric, dict):
        return _num(metric.get("value")) if metric.get("status") == "ok" else None
    return None


def _breadcrumbs(*crumbs: tuple[str, str]) -> dict[str, Any]:
    return {
        "@context": "https://schema.org", "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": i + 1, "name": name, "item": f"{SITE_URL}{path}"}
            for i, (name, path) in enumerate(crumbs)
        ],
    }


def _table(rows: list[tuple[str, str]]) -> str:
    cells = "".join(f"<tr><th scope=\"row\">{_esc(k)}</th><td>{_esc(v)}</td></tr>"
                    for k, v in rows if v and v != "—")
    return f"<table>{cells}</table>" if cells else ""


def _nav() -> str:
    links = [("/", "Главная"), ("/market", "Акции"), ("/news", "Новости"),
             ("/catalog", "Отчётность"), ("/currency", "Курсы валют")]
    return "<nav>" + " · ".join(f"<a href=\"{p}\">{_esc(t)}</a>" for p, t in links) + "</nav>"


# --------------------------------------------------------------------------- pages

async def _company_page(ticker: str) -> PageMeta | None:
    from server.company.routes import api_securities_info
    from server.market.routes import api_market_financials, api_market_multiples

    async def load() -> dict[str, Any] | None:
        try:
            info = await api_securities_info(ticker)
        except Exception:  # 404 for an unknown ticker, or a store hiccup
            return None
        fin, mult = await asyncio.gather(
            api_market_financials(ticker), api_market_multiples(_internal_request(), "board", ticker),
            return_exceptions=True)
        fin_row = ((_json_body(fin) if not isinstance(fin, BaseException) else {})
                   .get("financials") or {}).get(ticker)
        mult_items = (_json_body(mult) if not isinstance(mult, BaseException) else {}).get("items") or []
        return {"info": info, "fin": fin_row,
                "mult": next((r for r in mult_items if str(r.get("ticker")).upper() == ticker), None)}

    data = await _cached(f"company:{ticker}", load)
    if not data:
        return None
    sec = (data["info"] or {}).get("security") or {}
    wiki = (data["info"] or {}).get("wiki") or {}
    if str(sec.get("type") or "") == "bond":
        return None
    name = _clean_name(sec.get("company_name") or sec.get("security_name") or ticker)
    preferred = sec.get("share_type") == "preferred" or sec.get("is_preferred") is True
    if preferred and "привилегирован" not in name.lower():
        name = f"{name} (привилегированные)"
    short = _clean_name(wiki.get("title")) or name
    sector = SECTOR_NAMES.get(str(sec.get("sector") or ""), None)
    price, trade_date = _num(sec.get("last_price")), _fmt_date(sec.get("last_trade_date"))
    cap = _num(sec.get("market_cap"))
    mult, fin = data["mult"], data["fin"] or {}
    pe, pb, roe = _metric(mult, "pe"), _metric(mult, "pb"), _metric(mult, "roe")

    facts = [
        ("Тикер", ticker), ("ISIN", sec.get("isin") or ""),
        ("Тип бумаги", "Привилегированная акция" if preferred else "Обыкновенная акция"),
        ("Сектор", sector or ""),
        ("Последняя цена", f"{_fmt_num(price, 2)} сум" + (f" ({trade_date})" if trade_date else "")
         if price else ""),
        ("Рыночная капитализация", _fmt_money(cap) if cap else ""),
        ("Акций в обращении", _fmt_num(sec.get("shares_outstanding")) if sec.get("shares_outstanding") else ""),
        ("Номинал", f"{_fmt_num(sec.get('nominal'))} сум" if _num(sec.get("nominal")) else ""),
        ("P/E", _fmt_num(pe, 2) if pe is not None else ""),
        ("P/B", _fmt_num(pb, 2) if pb is not None else ""),
        ("ROE", f"{_fmt_num(roe, 1)}%" if roe is not None else ""),
        ("Дата листинга", _fmt_date(sec.get("listing_date")) or ""),
    ]

    fin_rows: list[tuple[str, str]] = []
    annual = fin.get("annual") or (fin if fin.get("period_months") == 12 else None)
    if annual and annual.get("year"):
        y = annual["year"]
        fin_rows += [
            (f"Выручка за {y} год", _fmt_money(annual.get("revenue")) if _num(annual.get("revenue")) else ""),
            (f"Чистая прибыль за {y} год", _fmt_money(annual.get("net_income")) if _num(annual.get("net_income")) is not None else ""),
            (f"Активы на конец {y} года", _fmt_money(annual.get("total_assets")) if _num(annual.get("total_assets")) else ""),
            (f"Собственный капитал на конец {y} года", _fmt_money(annual.get("total_equity")) if _num(annual.get("total_equity")) else ""),
        ]
    if fin.get("year") and fin.get("period_months") and fin.get("period_months") != 12:
        label = f"{fin['period_months']} мес. {fin['year']} г."
        prior = fin.get("prior") or {}
        for key, title in (("revenue", "Выручка"), ("net_income", "Чистая прибыль")):
            value = _num(fin.get(key))
            if value is None:
                continue
            text = _fmt_money(value)
            base = _num(prior.get(key))
            if base and base > 0 and value is not None:
                text += f" ({'+' if value >= base else ''}{_fmt_num((value / base - 1) * 100, 1)}% г/г)"
            fin_rows.append((f"{title} за {label}", text))

    lead_bits = [f"{short} ({ticker}) — акции на Ташкентской фондовой бирже (UZSE)."]
    if price:
        lead_bits.append(f"Цена {_fmt_num(price, 2)} сум" + (f" на {trade_date}" if trade_date else "") + ".")
    if cap:
        lead_bits.append(f"Капитализация {_fmt_money(cap)}.")
    if pe is not None:
        lead_bits.append(f"P/E {_fmt_num(pe, 2)}.")
    lead = " ".join(lead_bits)

    path = f"/company/{ticker}"
    body = (
        f"<article><h1>{_esc(name)} ({_esc(ticker)})</h1><p>{_esc(lead)}</p>"
        + (f"<p>{_esc(wiki.get('extract'))}</p>" if wiki.get("extract") else "")
        + "<h2>Ключевые показатели</h2>" + _table(facts)
        + (("<h2>Финансовая отчётность (НСБУ)</h2>" + _table(fin_rows)) if _table(fin_rows) else "")
        + f"<p><a href=\"/chart/{_esc(ticker)}\">График цены {_esc(ticker)}</a> · "
          f"<a href=\"/market\">Все акции UZSE</a></p></article>"
    )
    org = {"@context": "https://schema.org", "@type": "Corporation", "name": name,
           "tickerSymbol": ticker, "url": f"{SITE_URL}{path}"}
    if short != name:
        org["alternateName"] = short
    if wiki.get("extract"):
        org["description"] = _clip(wiki["extract"], 300)
    if sec.get("isin"):
        org["identifier"] = {"@type": "PropertyValue", "propertyID": "ISIN", "value": sec["isin"]}
    return PageMeta(
        title=f"{short} ({ticker}) — акции, цена, отчётность, P/E | {SITE_NAME}",
        description=_clip(lead + " Финансовая отчётность, мультипликаторы, дивиденды и график цены."),
        canonical=path, og_type="website",
        image=f"{SITE_URL}{sec['logo_url']}" if str(sec.get("logo_url") or "").startswith("/") else None,
        jsonld=[org, _breadcrumbs(("Главная", "/"), ("Акции", "/market"), (short, path))],
        body=body,
    )


async def _bonds_board() -> list[dict[str, Any]]:
    from server.bonds.routes import api_bonds

    async def load() -> list[dict[str, Any]]:
        return _json_body(await api_bonds(_internal_request())).get("items") or []
    return await _cached("bonds", load)


async def _bond_page(ticker: str) -> PageMeta | None:
    row = next((r for r in await _bonds_board() if str(r.get("ticker")).upper() == ticker), None)
    if not row:
        return None
    ref = row.get("reference") or {}
    issuer = _clean_name(row.get("issuer") or row.get("name") or ticker)
    ytm = row.get("ytm") or {}
    ytm_value = _num(ytm.get("value")) if ytm.get("status") == "ok" else None
    rate, maturity = _num(ref.get("coupon_rate")), _fmt_date(ref.get("maturity_date"))
    facts = [
        ("Тикер", ticker), ("ISIN", row.get("isin") or ""), ("Эмитент", issuer),
        ("Цена", f"{_fmt_num(row.get('price'), 2)} сум" if _num(row.get("price")) else ""),
        ("Котировка", f"{_fmt_num(_metric(row, 'price_pct'), 2)}% от номинала"
         if _metric(row, "price_pct") is not None else ""),
        ("Последняя сделка", _fmt_date(row.get("last_trade_date")) or ""),
        ("Номинал", f"{_fmt_num(ref.get('nominal'))} сум" if _num(ref.get("nominal")) else ""),
        ("Купон", f"{_fmt_num(rate, 2)}% годовых" if rate is not None else ""),
        ("Дата погашения", maturity or ""),
        ("Доходность к погашению", f"{_fmt_num(ytm_value, 2)}%" if ytm_value is not None else ""),
    ]
    lead = f"Облигация {ticker} — {issuer}, торгуется на Ташкентской фондовой бирже."
    if rate is not None:
        lead += f" Купон {_fmt_num(rate, 2)}%."
    if maturity:
        lead += f" Погашение {maturity}."
    path = f"/bond/{ticker}"
    return PageMeta(
        title=f"Облигация {ticker} — {issuer}: купон, доходность, цена | {SITE_NAME}",
        description=_clip(lead), canonical=path,
        jsonld=[_breadcrumbs(("Главная", "/"), ("Облигации", "/market"), (ticker, path))],
        body=f"<article><h1>Облигация {_esc(ticker)} — {_esc(issuer)}</h1><p>{_esc(lead)}</p>"
             + _table(facts) + "<p><a href=\"/market\">Все облигации UZSE</a></p></article>",
    )


async def _news_page(news_id: str) -> PageMeta | None:
    if not news_id.isdigit():
        return None
    import news_store

    async def load() -> dict[str, Any] | None:
        return await asyncio.get_running_loop().run_in_executor(None, news_store.get_news_item, int(news_id))
    item = await _cached(f"news:{news_id}", load)
    if not item:
        return None
    title = _clean_name(item.get("title_ru") or item.get("title"))
    summary = str(item.get("summary_ru") or item.get("snippet") or "").strip()
    detail = str(item.get("detail_ru") or "").strip()
    published = str(item.get("published_at") or "")
    path = f"/news/{news_id}"
    paragraphs = "".join(f"<p>{_esc(p)}</p>" for p in (detail or summary).split("\n") if p.strip())
    tickers = "".join(f"<li><a href=\"/company/{_esc(t)}\">{_esc(t)}</a></li>" for t in item.get("tickers") or [])
    article = {
        "@context": "https://schema.org", "@type": "NewsArticle", "headline": _clip(title, 110),
        "datePublished": published or None, "mainEntityOfPage": f"{SITE_URL}{path}",
        "publisher": {"@type": "Organization", "name": SITE_NAME, "url": SITE_URL},
    }
    if item.get("image_url"):
        article["image"] = item["image_url"]
    if item.get("url"):
        article["isBasedOn"] = item["url"]
    return PageMeta(
        title=f"{_clip(title, 90)} | {SITE_NAME}", description=_clip(summary or title),
        canonical=path, og_type="article", image=item.get("image_url"),
        jsonld=[{k: v for k, v in article.items() if v}],
        body=(f"<article><h1>{_esc(title)}</h1>"
              + (f"<p><time datetime=\"{_esc(published)}\">{_esc(_fmt_date(published) or '')}</time>"
                 f" · {_esc(item.get('source') or '')}</p>")
              + paragraphs
              + (f"<p>Эмитенты:</p><ul>{tickers}</ul>" if tickers else "")
              + (f"<p><a href=\"{_esc(item['url'])}\" rel=\"nofollow noopener\">Источник</a></p>"
                 if item.get("url") else "")
              + "</article>"),
    )


async def page_meta(full_path: str) -> PageMeta:
    path = "/" + (full_path or "").strip("/")
    if path.startswith(_PRIVATE_PREFIXES):
        return PageMeta(noindex=True)
    meta: PageMeta | None = None
    try:
        if path.startswith("/company/"):
            meta = await _company_page(path[len("/company/"):].split("/")[0].upper())
        elif path.startswith("/bond/"):
            meta = await _bond_page(path[len("/bond/"):].split("/")[0].upper())
        elif path.startswith("/chart/"):
            ticker = path[len("/chart/"):].split("/")[0].upper()
            meta = PageMeta(title=f"{ticker} — график цены акций | {SITE_NAME}",
                            description=f"Интерактивный график цены {ticker} на UZSE с индикаторами.",
                            canonical=f"/chart/{ticker}")
        elif path.startswith("/news/announcement/"):
            meta = PageMeta(title=f"Корпоративное событие | {SITE_NAME}", canonical=path)
        elif path.startswith("/news/"):
            meta = await _news_page(path[len("/news/"):].split("/")[0])
    except Exception:
        http.logger.warning("seo: snapshot for %s failed", path, exc_info=True)
        meta = None
    if meta is None and path in _STATIC_PAGES:
        title, description = _STATIC_PAGES[path]
        meta = PageMeta(title=title, description=description, canonical=path)
        if path == "/":
            meta.jsonld = [
                {"@context": "https://schema.org", "@type": "WebSite", "name": SITE_NAME,
                 "url": SITE_URL, "inLanguage": "ru"},
                {"@context": "https://schema.org", "@type": "Organization", "name": SITE_NAME,
                 "url": SITE_URL, "logo": f"{SITE_URL}/favicon-96x96.png"},
            ]
    if meta is None:
        meta = PageMeta()
    if not meta.body:
        meta.body = f"<h1>{_esc(meta.title.split(' | ')[0])}</h1><p>{_esc(meta.description)}</p>"
    meta.body = (
        "<div class=\"seo-snapshot\" style=\"max-width:960px;margin:0 auto;padding:16px;"
        "font-family:system-ui,sans-serif;line-height:1.5\">" + meta.body + _nav() + "</div>"
    )
    return meta


def render(template: str, meta: PageMeta) -> str:
    head = [f"<title>{_esc(meta.title)}</title>",
            f"<meta name=\"description\" content=\"{_esc(meta.description)}\" />"]
    if meta.noindex:
        head.append("<meta name=\"robots\" content=\"noindex, nofollow\" />")
    if meta.canonical:
        url = f"{SITE_URL}{meta.canonical}"
        head += [f"<link rel=\"canonical\" href=\"{_esc(url)}\" />",
                 f"<meta property=\"og:url\" content=\"{_esc(url)}\" />"]
    head += [
        f"<meta property=\"og:site_name\" content=\"{SITE_NAME}\" />",
        f"<meta property=\"og:type\" content=\"{_esc(meta.og_type)}\" />",
        f"<meta property=\"og:title\" content=\"{_esc(meta.title)}\" />",
        f"<meta property=\"og:description\" content=\"{_esc(meta.description)}\" />",
        "<meta property=\"og:locale\" content=\"ru_RU\" />",
        f"<meta name=\"twitter:card\" content=\"{'summary_large_image' if meta.image else 'summary'}\" />",
    ]
    if meta.image:
        head.append(f"<meta property=\"og:image\" content=\"{_esc(meta.image)}\" />")
    for block in meta.jsonld:
        payload = json.dumps(block, ensure_ascii=False, default=str).replace("<", "\\u003c")
        head.append(f"<script type=\"application/ld+json\">{payload}</script>")
    out, swapped = re.subn(r"<title>.*?</title>", lambda _: "\n    ".join(head), template,
                           count=1, flags=re.S)
    if not swapped:
        out = out.replace("</head>", "    " + "\n    ".join(head) + "\n  </head>", 1)
    if meta.body:
        out = out.replace('<div id="root"></div>', f'<div id="root">{meta.body}</div>', 1)
    return out


# --------------------------------------------------------------------------- robots / sitemap

def robots_txt() -> str:
    return (
        "User-agent: *\n"
        "Allow: /\n"
        "Disallow: /api/\n"
        "Disallow: /admin\n"
        "Disallow: /profile\n"
        "Disallow: /login\n"
        "\n"
        # Named so nobody wonders whether a blanket rule covers them: these are
        # the crawlers behind ChatGPT, Claude, Perplexity and Gemini answers.
        "User-agent: GPTBot\nUser-agent: OAI-SearchBot\nUser-agent: ChatGPT-User\n"
        "User-agent: ClaudeBot\nUser-agent: Claude-SearchBot\nUser-agent: Claude-User\n"
        "User-agent: PerplexityBot\nUser-agent: Google-Extended\n"
        "Allow: /\n"
        "Disallow: /api/\n"
        "Disallow: /admin\n"
        "Disallow: /profile\n"
        "Disallow: /login\n"
        "\n"
        f"Sitemap: {SITE_URL}/sitemap.xml\n"
    )


def _iso(value: Any) -> str | None:
    text = str(value or "")[:10]
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError:
        return None


async def sitemap_xml() -> str:
    from server.market.routes import api_instruments
    import news_store

    async def load() -> str:
        entries: list[tuple[str, str | None, str]] = [
            (p, None, "daily") for p in _STATIC_PAGES]
        try:
            items = _json_body(await api_instruments(_internal_request(), True)).get("items") or []
        except Exception:
            http.logger.warning("seo: sitemap instruments failed", exc_info=True)
            items = []
        for item in sorted(items, key=lambda i: str(i.get("ticker"))):
            ticker = str(item.get("ticker") or "").strip().upper()
            if not ticker or not re.fullmatch(r"[A-Z0-9]+", ticker):
                continue
            kind = "bond" if item.get("type") == "bond" else "company"
            entries.append((f"/{kind}/{ticker}", _iso(item.get("last_trade_date")),
                            "daily" if item.get("is_active") else "monthly"))
        try:
            news = await asyncio.get_running_loop().run_in_executor(
                None, lambda: news_store.get_news_feed(limit=200, days=180, order="recent"))
        except Exception:
            http.logger.warning("seo: sitemap news failed", exc_info=True)
            news = []
        for item in news:
            if item.get("id") is not None:
                entries.append((f"/news/{item['id']}", _iso(item.get("published_at")), "monthly"))
        lines = ['<?xml version="1.0" encoding="UTF-8"?>',
                 '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
        seen: set[str] = set()
        for path, lastmod, freq in entries:
            if path in seen:
                continue
            seen.add(path)
            lines.append("  <url><loc>" + html.escape(f"{SITE_URL}{path}") + "</loc>"
                         + (f"<lastmod>{lastmod}</lastmod>" if lastmod else "")
                         + f"<changefreq>{freq}</changefreq></url>")
        lines.append("</urlset>")
        return "\n".join(lines) + "\n"

    return await _cached("sitemap", load)


@router.get("/robots.txt", include_in_schema=False)
async def robots_route() -> PlainTextResponse:
    return PlainTextResponse(robots_txt(), headers={"Cache-Control": "public, max-age=3600"})


@router.get("/sitemap.xml", include_in_schema=False)
async def sitemap_route() -> Response:
    return Response(await sitemap_xml(), media_type="application/xml",
                    headers={"Cache-Control": "public, max-age=3600"})


_template_cache: dict[str, tuple[float, str]] = {}


def template(index_path: Path) -> str:
    key = str(index_path)
    mtime = index_path.stat().st_mtime
    hit = _template_cache.get(key)
    if hit and hit[0] == mtime:
        return hit[1]
    text = index_path.read_text(encoding="utf-8")
    _template_cache[key] = (mtime, text)
    return text


__all__ = ["PageMeta", "page_meta", "render", "robots_txt", "router", "sitemap_xml", "template", "SITE_URL"]

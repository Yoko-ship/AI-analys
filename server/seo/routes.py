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

Recent valid data remains available during refresh. If a dynamic page cannot
be rendered at all, its app shell is served as a retryable 503, never as an
indexable copy of the homepage.
"""

from __future__ import annotations

import asyncio
import html
import json
import math
import os
import re
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable

from fastapi import APIRouter, HTTPException
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

# Languages with URLs of their own. Russian is the default and has no prefix;
# each other language lives under "/{lang}" (frontend/src/app/routing.jsx keeps
# the same list). A page that exists in every language names the others with
# hreflang, so Google shows each searcher the version in their language.
DEFAULT_LANGUAGE = "ru"
URL_LANGUAGES = ("uz",)
LANGUAGES = (DEFAULT_LANGUAGE, *URL_LANGUAGES)
_OG_LOCALE = {"ru": "ru_RU", "uz": "uz_UZ"}

# Pages a search result should never point at.
_PRIVATE_PREFIXES = ("/admin", "/profile", "/login", "/portfolio")

# Pages with one id after the prefix (frontend/src/app/routing.jsx, pathToView).
_ENTITY_PREFIXES = ("/company/", "/chart/", "/bond/", "/news/")
# Old paths the app still opens as another page. Public static pages belong in
# _STATIC_PAGES so each gets its own metadata, canonical and sitemap entry.
# Every other path is answered 404 rather than indexing the home page again.
_ALIASES = {"/bonds": "/market"}
# Google shows an organisation logo only from 112×112 up (tests/test_seo.py
# reads the file's real size).
LOGO_PATH = "/apple-touch-icon.png"

_STATIC_PAGES: dict[str, tuple[str, str]] = {
    "/": (DEFAULT_TITLE, DEFAULT_DESCRIPTION),
    "/market": (
        "Акции компаний Узбекистана — котировки UZSE сегодня | UZStock",
        "Все акции и облигации компаний Узбекистана на Ташкентской фондовой бирже: цены, "
        "капитализация, P/E, P/B и ROE эмитентов.",
    ),
    "/issuers": ("Каталог компаний Узбекистана | UZStock", "Эмитенты, тикеры, ISIN и финансовая отчётность компаний Узбекистана."),
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
    "/feedback": (
        "Обратная связь | UZStock",
        "Сообщите об ошибке, предложите улучшение или задайте вопрос команде UZStock. "
        "Для отправки сообщения войдите в аккаунт.",
    ),
}

_STATIC_PAGES_UZ: dict[str, tuple[str, str]] = {
    "/": (
        "UZStock — O‘zbekiston fond bozori",
        "Toshkent fond birjasi (UZSE) aksiyalari va obligatsiyalari kotirovkalari, emitentlarning "
        "moliyaviy hisobotlari, P/E va P/B multiplikatorlari, dividendlar va bozor yangiliklari.",
    ),
    "/market": (
        "O‘zbekiston kompaniyalari aksiyalari — bugungi UZSE kotirovkalari | UZStock",
        "Toshkent fond birjasidagi O‘zbekiston kompaniyalarining barcha aksiyalari va obligatsiyalari: "
        "narxlar, kapitallashuv, emitentlarning P/E, P/B va ROE ko‘rsatkichlari.",
    ),
    "/issuers": ("O‘zbekiston kompaniyalari katalogi | UZStock", "Emitentlar, tikerlar, ISIN va O‘zbekiston kompaniyalarining moliyaviy hisobotlari."),
    "/heatmap": (
        "O‘zbekiston aksiyalar bozorining issiqlik xaritasi | UZStock",
        "UZSE aksiyalari narxlarining sektorlar va kapitallashuv bo‘yicha o‘zgarishi xaritasi.",
    ),
    "/catalog": (
        "O‘zbekiston emitentlarining moliyaviy hisobotlari | UZStock",
        "O‘zbekiston aksiyadorlik jamiyatlarining BHMS va MHXS bo‘yicha yillik va choraklik "
        "hisobotlari katalogi.",
    ),
    "/news": (
        "O‘zbekiston fond bozori yangiliklari | UZStock",
        "Korporativ voqealar, emitentlarning oshkor qilingan ma’lumotlari va O‘zbekiston iqtisodiyoti yangiliklari.",
    ),
    "/currency": (
        "O‘zbekiston banklaridagi valyuta kurslari | UZStock",
        "Tijorat banklarida dollar, yevro va rublning sotib olish va sotish kurslari hamda "
        "Markaziy bankning rasmiy kursi.",
    ),
    "/feedback": (
        "Fikr-mulohaza | UZStock",
        "Xatolik haqida xabar bering, taklif yuboring yoki UZStock jamoasiga savol bering. "
        "Xabar yuborish uchun hisobingizga kiring.",
    ),
}
_PAGES = {"ru": _STATIC_PAGES, "uz": _STATIC_PAGES_UZ}

SECTOR_NAMES = {
    "finance": "Финансы", "funds": "Фонды", "energy": "Энергетика",
    "manufacturing": "Промышленность", "mining": "Добыча", "telecom": "Телекоммуникации",
    "transport": "Транспорт", "logistics": "Логистика", "trade": "Торговля",
    "professional": "Профессиональные услуги",
}
SECTOR_NAMES_UZ = {
    "finance": "Moliya", "funds": "Fondlar", "energy": "Energetika",
    "manufacturing": "Sanoat", "mining": "Qazib olish", "telecom": "Telekommunikatsiyalar",
    "transport": "Transport", "logistics": "Logistika", "trade": "Savdo",
    "professional": "Professional xizmatlar",
}
_SECTORS = {"ru": SECTOR_NAMES, "uz": SECTOR_NAMES_UZ}

# Every sentence a snapshot writes, per language. Russian is the original;
# tests/test_seo.py checks the other languages carry the same keys.
_TX: dict[str, dict[str, str]] = {
    "ru": {
        "home": "Главная", "stocks": "Акции", "bonds": "Облигации", "news": "Новости",
        "reports": "Отчётность", "currency": "Курсы валют",
        "money_units": "трлн|млрд|млн|сум",
        "ticker": "Тикер", "security_type": "Тип бумаги",
        "preferred_share": "Привилегированная акция", "ordinary_share": "Обыкновенная акция",
        "preferred_marker": "привилегирован", "preferred_suffix": "(привилегированные)",
        "sector": "Сектор", "last_price": "Последняя цена", "market_cap": "Рыночная капитализация",
        "shares_out": "Акций в обращении", "nominal": "Номинал", "listing_date": "Дата листинга",
        "revenue_year": "Выручка за {y} год", "net_income_year": "Чистая прибыль за {y} год",
        "assets_year": "Активы на конец {y} года", "equity_year": "Собственный капитал на конец {y} года",
        "period": "{m} мес. {y} г.", "revenue": "Выручка", "net_income": "Чистая прибыль",
        "for_period": "{title} за {label}", "yoy": "г/г",
        "company_lead": "{short} ({ticker}) — акции на Ташкентской фондовой бирже (UZSE).",
        "price_on": "Цена {price} сум", "on_date": " на {date}",
        "cap_lead": "Капитализация {cap}.",
        "key_figures": "Ключевые показатели", "fin_report": "Финансовая отчётность (НСБУ)",
        "chart_of": "График цены {ticker}", "all_stocks": "Все акции UZSE",
        "company_title": "{short} ({ticker}) — акции, цена, отчётность, P/E",
        "company_tail": " Финансовая отчётность, мультипликаторы, дивиденды и график цены.",
        "issuer": "Эмитент", "price": "Цена", "quote": "Котировка", "of_nominal": "{pct}% от номинала",
        "last_trade": "Последняя сделка", "coupon": "Купон", "per_year": "{rate}% годовых",
        "maturity": "Дата погашения", "ytm": "Доходность к погашению",
        "bond_lead": "Облигация {ticker} — {issuer}, торгуется на Ташкентской фондовой бирже.",
        "bond_coupon": " Купон {rate}%.", "bond_maturity": " Погашение {date}.",
        "bond_title": "Облигация {ticker} — {issuer}: купон, доходность, цена",
        "bond_h1": "Облигация {ticker} — {issuer}", "all_bonds": "Все облигации UZSE",
        "chart_title": "{ticker} — график цены акций",
        "chart_description": "Интерактивный график цены {ticker} на UZSE с индикаторами.",
        "event_title": "Корпоративное событие",
        "not_found_title": "Страница не найдена",
        "unavailable_title": "Временно недоступно",
        "unavailable_description": "Данные страницы временно недоступны. Повторите попытку через минуту.",
        "not_found_description": "Такой страницы на UZStock нет. Акции, облигации и новости рынка Узбекистана — по ссылкам ниже.",
        "market_intro": ("Акции {count} компаний Узбекистана, которые торгуются на Ташкентской "
                         "фондовой бирже (UZSE): последняя цена, дата сделки, сектор и рыночная "
                         "капитализация. Нажмите на компанию, чтобы открыть её отчётность, "
                         "мультипликаторы P/E и P/B, дивиденды и график цены."),
        "company": "Компания", "price_uzs": "Цена, сум", "trade_date": "Дата сделки",
        "bonds_heading": "Облигации на UZSE", "maturity_short": "Погашение",
        "largest": "Крупнейшие компании Узбекистана по капитализации",
        "latest_news": "Последние новости рынка",
    },
    "uz": {
        "home": "Bosh sahifa", "stocks": "Aksiyalar", "bonds": "Obligatsiyalar", "news": "Yangiliklar",
        "reports": "Hisobotlar", "currency": "Valyuta kurslari",
        "money_units": "trln|mlrd|mln|so‘m",
        "ticker": "Tiker", "security_type": "Qimmatli qog‘oz turi",
        "preferred_share": "Imtiyozli aksiya", "ordinary_share": "Oddiy aksiya",
        "preferred_marker": "imtiyozli", "preferred_suffix": "(imtiyozli)",
        "sector": "Sektor", "last_price": "So‘nggi narx", "market_cap": "Bozor kapitallashuvi",
        "shares_out": "Muomaladagi aksiyalar", "nominal": "Nominal", "listing_date": "Listingga kiritilgan sana",
        "revenue_year": "{y} yil tushumi", "net_income_year": "{y} yil sof foydasi",
        "assets_year": "{y} yil oxiridagi aktivlar", "equity_year": "{y} yil oxiridagi xususiy kapital",
        "period": "{y} yil {m} oy", "revenue": "Tushum", "net_income": "Sof foyda",
        "for_period": "{title} ({label})", "yoy": "yillik",
        "company_lead": "{short} ({ticker}) — Toshkent fond birjasidagi (UZSE) aksiyalar.",
        "price_on": "Narx {price} so‘m", "on_date": " ({date} holatiga)",
        "cap_lead": "Kapitallashuv {cap}.",
        "key_figures": "Asosiy ko‘rsatkichlar", "fin_report": "Moliyaviy hisobot (BHMS)",
        "chart_of": "{ticker} narx grafigi", "all_stocks": "UZSE barcha aksiyalari",
        "company_title": "{short} ({ticker}) — aksiyalar, narx, hisobot, P/E",
        "company_tail": " Moliyaviy hisobot, multiplikatorlar, dividendlar va narx grafigi.",
        "issuer": "Emitent", "price": "Narx", "quote": "Kotirovka", "of_nominal": "nominalning {pct}%",
        "last_trade": "So‘nggi bitim", "coupon": "Kupon", "per_year": "yillik {rate}%",
        "maturity": "So‘ndirish sanasi", "ytm": "So‘ndirishgacha daromadlilik",
        "bond_lead": "{ticker} obligatsiyasi — {issuer}, Toshkent fond birjasida savdo qilinadi.",
        "bond_coupon": " Kupon {rate}%.", "bond_maturity": " So‘ndirish {date}.",
        "bond_title": "{ticker} obligatsiyasi — {issuer}: kupon, daromadlilik, narx",
        "bond_h1": "{ticker} obligatsiyasi — {issuer}", "all_bonds": "UZSE barcha obligatsiyalari",
        "chart_title": "{ticker} — aksiya narxi grafigi",
        "chart_description": "{ticker} aksiyasining UZSE dagi indikatorli interaktiv narx grafigi.",
        "event_title": "Korporativ voqea",
        "not_found_title": "Sahifa topilmadi",
        "unavailable_title": "Vaqtincha mavjud emas",
        "unavailable_description": "Sahifa ma’lumotlari vaqtincha mavjud emas. Bir daqiqadan so‘ng qayta urinib ko‘ring.",
        "not_found_description": "UZStock’da bunday sahifa yo‘q. O‘zbekiston bozori aksiyalari, obligatsiyalari va yangiliklari — quyidagi havolalarda.",
        "market_intro": ("Toshkent fond birjasida (UZSE) savdo qilinadigan {count} ta O‘zbekiston "
                         "kompaniyasining aksiyalari: so‘nggi narx, bitim sanasi, sektor va bozor "
                         "kapitallashuvi. Kompaniyaning hisobotlari, P/E va P/B multiplikatorlari, "
                         "dividendlari va narx grafigini ochish uchun uning nomini bosing."),
        "company": "Kompaniya", "price_uzs": "Narx, so‘m", "trade_date": "Bitim sanasi",
        "bonds_heading": "UZSE dagi obligatsiyalar", "maturity_short": "So‘ndirish",
        "largest": "Kapitallashuv bo‘yicha O‘zbekistonning eng yirik kompaniyalari",
        "latest_news": "Bozorning so‘nggi yangiliklari",
    },
}


def split_language(path: str) -> tuple[str, str]:
    """("uz", "/market") for "/uz/market"; ("ru", path) for an unprefixed path."""
    for lang in URL_LANGUAGES:
        prefix = f"/{lang}"
        if path == prefix or path.startswith(prefix + "/"):
            return lang, path[len(prefix):] or "/"
    return DEFAULT_LANGUAGE, path


def localized(path: str, lang: str) -> str:
    """The URL of `path` (an unprefixed site path) in `lang`."""
    if lang == DEFAULT_LANGUAGE:
        return path
    return f"/{lang}" + ("" if path == "/" else path)

_CACHE_TTL = 600.0
# A dated snapshot may bridge a slow refresh, but never an indefinite outage.
_CACHE_STALE_TTL = 3600.0
_DATA_TIMEOUT = 6.0
# Ceilings on the page-data cache, whatever paths are asked for: about the site's
# own page count (≈100 companies and bonds x 2 languages, the stories, the lists)
# for pages that exist, and a smaller allowance for answers that a page does not.
_CACHE_MAX_ENTRIES = 2000
_CACHE_MAX_MISSES = 500


def _is_miss(value: Any) -> bool:
    """A loader's answer that the page does not exist: nothing, or a marked miss."""
    return not value or (isinstance(value, dict) and bool(value.get("missing")))


class _PageDataCache:
    """Loaded page data by key, bounded however many distinct keys are asked for.

    The keys come from the URL (a ticker, a story id), so whoever walks random
    paths chooses how many there are. Expiry alone bounded nothing: stale entries
    were only swept past 2000, and every one of them was still fresh. Now each
    insert evicts the least recently used entry past the ceiling. A miss is still
    cached, since a crawler re-probes the same dead link and each probe is a store
    read, but misses have their own smaller allowance, so random paths can neither
    grow memory nor push the real pages out.
    """

    def __init__(self, limit: int, miss_limit: int) -> None:
        self.limit, self.miss_limit = limit, miss_limit
        self._entries: OrderedDict[str, tuple[float, Any]] = OrderedDict()
        self._misses: OrderedDict[str, None] = OrderedDict()

    def get(self, key: str, now: float, stale_for: float = 0.0) -> tuple[float, Any] | None:
        entry = self._entries.get(key)
        if entry is None:
            return None
        grace = 0.0 if _is_miss(entry[1]) else stale_for
        if entry[0] + grace <= now:
            self._drop(key)
            return None
        self._entries.move_to_end(key)
        return entry

    def put(self, key: str, value: Any, expires_at: float) -> None:
        self._drop(key)
        self._entries[key] = (expires_at, value)
        if _is_miss(value):
            self._misses[key] = None
            while len(self._misses) > self.miss_limit:
                self._drop(next(iter(self._misses)))
        while len(self._entries) > self.limit:
            self._drop(next(iter(self._entries)))

    def _drop(self, key: str) -> None:
        self._entries.pop(key, None)
        self._misses.pop(key, None)

    def clear(self) -> None:
        self._entries.clear()
        self._misses.clear()

    def __len__(self) -> int:
        return len(self._entries)

    def __contains__(self, key: str) -> bool:
        return key in self._entries


_cache = _PageDataCache(_CACHE_MAX_ENTRIES, _CACHE_MAX_MISSES)
_pending: dict[str, asyncio.Task] = {}


class _Missing(Exception):
    """The data source says the page's company, bond or story does not exist."""


@dataclass
class PageMeta:
    title: str = DEFAULT_TITLE
    description: str = DEFAULT_DESCRIPTION
    canonical: str | None = None
    noindex: bool = False
    status: int = 200
    lang: str = DEFAULT_LANGUAGE
    # The unprefixed path of a page that exists in every language: render()
    # names each language's URL for it with hreflang.
    alternate: str | None = None
    og_type: str = "website"
    image: str | None = None
    jsonld: list[dict[str, Any]] = field(default_factory=list)
    body: str = ""


# --------------------------------------------------------------------------- helpers

def _esc(value: Any) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


def _web_url(value: Any) -> str | None:
    """The URL if it is an http(s) link, else None. Escaping keeps an attribute
    closed but does not stop a ``javascript:`` href from running when clicked."""
    url = str(value or "").strip()
    return url if re.match(r"https?://", url, re.IGNORECASE) else None


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


def _fmt_money(value: Any, lang: str = DEFAULT_LANGUAGE) -> str:
    """Sums in UZS, read the way a financial page in `lang` writes them."""
    number = _num(value)
    if number is None:
        return "—"
    trln, mlrd, mln, currency = _TX[lang]["money_units"].split("|")
    for scale, unit in ((1e12, trln), (1e9, mlrd), (1e6, mln)):
        if abs(number) >= scale:
            return f"{_fmt_num(number / scale, 2)} {unit} {currency}"
    return f"{_fmt_num(number)} {currency}"


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
    now = time.monotonic()
    hit = _cache.get(key, now, stale_for=_CACHE_STALE_TTL)
    if hit and hit[0] > now:
        return hit[1]
    task = _pending.get(key)
    if task is None:
        async def fill() -> Any:
            try:
                value = await loader()
                _cache.put(key, value, time.monotonic() + _CACHE_TTL)
                return value
            finally:
                _pending.pop(key, None)
        task = _pending[key] = asyncio.ensure_future(fill())
        task.add_done_callback(lambda t: t.cancelled() or t.exception())
    if hit:
        # Keep the last real content and its original dates while one refresh
        # runs. A successful refresh (including a confirmed miss) replaces it.
        return hit[1]
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


def _nav(lang: str = DEFAULT_LANGUAGE) -> str:
    tx = _TX[lang]
    links = [("/", tx["home"]), ("/market", tx["stocks"]), ("/news", tx["news"]),
             ("/catalog", tx["reports"]), ("/currency", tx["currency"])]
    out = " · ".join(f"<a href=\"{localized(p, lang)}\">{_esc(t)}</a>" for p, t in links)
    # Each language's snapshot links to the other, so a crawler that lands on
    # one finds every version.
    others = " · ".join(f"<a href=\"{localized('/', other)}\" hreflang=\"{other}\">{_LANGUAGE_NAMES[other]}</a>"
                        for other in LANGUAGES if other != lang)
    return f"<nav>{out}</nav><p>{others}</p>"


_LANGUAGE_NAMES = {"ru": "Русский", "uz": "O‘zbekcha"}


# --------------------------------------------------------------------------- pages

async def _company_page(ticker: str, lang: str = DEFAULT_LANGUAGE) -> PageMeta | None:
    from server.company.routes import api_securities_info
    from server.market.routes import api_market_financials, api_market_multiples

    async def load() -> dict[str, Any] | None:
        try:
            info = await api_securities_info(ticker, lang)
        except HTTPException as exc:
            # A store hiccup raises out of here, is not cached, and serves the
            # retryable shell: only the handler's own 404 makes the page missing.
            if exc.status_code == 404:
                return {"missing": True}
            raise
        fin, mult = await asyncio.gather(
            api_market_financials(ticker), api_market_multiples(_internal_request(), "board", ticker),
            return_exceptions=True)
        fin_row = ((_json_body(fin) if not isinstance(fin, BaseException) else {})
                   .get("financials") or {}).get(ticker)
        mult_items = (_json_body(mult) if not isinstance(mult, BaseException) else {}).get("items") or []
        return {"info": info, "fin": fin_row,
                "mult": next((r for r in mult_items if str(r.get("ticker")).upper() == ticker), None)}

    data = await _cached(f"company:{lang}:{ticker}", load)
    if not data:
        return None
    if data.get("missing"):
        raise _Missing(ticker)
    sec = (data["info"] or {}).get("security") or {}
    wiki = (data["info"] or {}).get("wiki") or {}
    if str(sec.get("type") or "") == "bond":
        return None
    tx = _TX[lang]
    name = _clean_name(sec.get("company_name") or sec.get("security_name") or ticker)
    preferred = sec.get("share_type") == "preferred" or sec.get("is_preferred") is True
    if preferred and tx["preferred_marker"] not in name.lower():
        name = f"{name} {tx['preferred_suffix']}"
    short = _clean_name(wiki.get("title")) or name
    sector = _SECTORS[lang].get(str(sec.get("sector") or ""), None)
    price, trade_date = _num(sec.get("last_price")), _fmt_date(sec.get("last_trade_date"))
    cap = _num(sec.get("market_cap"))
    mult, fin = data["mult"], data["fin"] or {}
    pe, pb, roe = _metric(mult, "pe"), _metric(mult, "pb"), _metric(mult, "roe")

    currency = tx["money_units"].split("|")[-1]
    facts = [
        (tx["ticker"], ticker), ("ISIN", sec.get("isin") or ""),
        (tx["security_type"], tx["preferred_share"] if preferred else tx["ordinary_share"]),
        (tx["sector"], sector or ""),
        (tx["last_price"], f"{_fmt_num(price, 2)} {currency}" + (f" ({trade_date})" if trade_date else "")
         if price else ""),
        (tx["market_cap"], _fmt_money(cap, lang) if cap else ""),
        (tx["shares_out"], _fmt_num(sec.get("shares_outstanding")) if sec.get("shares_outstanding") else ""),
        (tx["nominal"], f"{_fmt_num(sec.get('nominal'))} {currency}" if _num(sec.get("nominal")) else ""),
        ("P/E", _fmt_num(pe, 2) if pe is not None else ""),
        ("P/B", _fmt_num(pb, 2) if pb is not None else ""),
        ("ROE", f"{_fmt_num(roe, 1)}%" if roe is not None else ""),
        (tx["listing_date"], _fmt_date(sec.get("listing_date")) or ""),
    ]

    fin_rows: list[tuple[str, str]] = []
    annual = fin.get("annual") or (fin if fin.get("period_months") == 12 else None)
    if annual and annual.get("year"):
        y = annual["year"]
        money = lambda key: _fmt_money(annual.get(key), lang)  # noqa: E731
        fin_rows += [
            (tx["revenue_year"].format(y=y), money("revenue") if _num(annual.get("revenue")) else ""),
            (tx["net_income_year"].format(y=y), money("net_income") if _num(annual.get("net_income")) is not None else ""),
            (tx["assets_year"].format(y=y), money("total_assets") if _num(annual.get("total_assets")) else ""),
            (tx["equity_year"].format(y=y), money("total_equity") if _num(annual.get("total_equity")) else ""),
        ]
    if fin.get("year") and fin.get("period_months") and fin.get("period_months") != 12:
        label = tx["period"].format(m=fin["period_months"], y=fin["year"])
        prior = fin.get("prior") or {}
        for key, title in (("revenue", tx["revenue"]), ("net_income", tx["net_income"])):
            value = _num(fin.get(key))
            if value is None:
                continue
            text = _fmt_money(value, lang)
            base = _num(prior.get(key))
            if base and base > 0 and value is not None:
                text += f" ({'+' if value >= base else ''}{_fmt_num((value / base - 1) * 100, 1)}% {tx['yoy']})"
            fin_rows.append((tx["for_period"].format(title=title, label=label), text))

    lead_bits = [tx["company_lead"].format(short=short, ticker=ticker)]
    if price:
        lead_bits.append(tx["price_on"].format(price=_fmt_num(price, 2))
                         + (tx["on_date"].format(date=trade_date) if trade_date else "") + ".")
    if cap:
        lead_bits.append(tx["cap_lead"].format(cap=_fmt_money(cap, lang)))
    if pe is not None:
        lead_bits.append(f"P/E {_fmt_num(pe, 2)}.")
    lead = " ".join(lead_bits)

    base_path = f"/company/{ticker}"
    path = localized(base_path, lang)
    body = (
        f"<article><h1>{_esc(name)} ({_esc(ticker)})</h1><p>{_esc(lead)}</p>"
        + (f"<p>{_esc(wiki.get('extract'))}</p>" if wiki.get("extract") else "")
        + f"<h2>{_esc(tx['key_figures'])}</h2>" + _table(facts)
        + ((f"<h2>{_esc(tx['fin_report'])}</h2>" + _table(fin_rows)) if _table(fin_rows) else "")
        + f"<p><a href=\"{localized('/chart/' + _esc(ticker), lang)}\">{_esc(tx['chart_of'].format(ticker=ticker))}</a> · "
          f"<a href=\"{localized('/market', lang)}\">{_esc(tx['all_stocks'])}</a></p></article>"
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
        title=f"{tx['company_title'].format(short=short, ticker=ticker)} | {SITE_NAME}",
        description=_clip(lead + tx["company_tail"]),
        canonical=path, og_type="website", lang=lang, alternate=base_path,
        image=f"{SITE_URL}{sec['logo_url']}" if str(sec.get("logo_url") or "").startswith("/") else None,
        jsonld=[org, _breadcrumbs((tx["home"], localized("/", lang)), (tx["stocks"], localized("/market", lang)),
                                  (short, path))],
        body=body,
    )


async def _bonds_board() -> list[dict[str, Any]]:
    from server.bonds.routes import api_bonds

    async def load() -> list[dict[str, Any]]:
        return _json_body(await api_bonds(_internal_request())).get("items") or []
    return await _cached("bonds", load)


async def _bond_page(ticker: str, lang: str = DEFAULT_LANGUAGE) -> PageMeta | None:
    board = await _bonds_board()
    row = next((r for r in board if str(r.get("ticker")).upper() == ticker), None)
    if not row:
        # An empty board says nothing about this bond; a full one without it does.
        if board:
            raise _Missing(ticker)
        return None
    tx = _TX[lang]
    currency = tx["money_units"].split("|")[-1]
    ref = row.get("reference") or {}
    issuer = _clean_name(row.get("issuer") or row.get("name") or ticker)
    ytm = row.get("ytm") or {}
    ytm_value = _num(ytm.get("value")) if ytm.get("status") == "ok" else None
    rate, maturity = _num(ref.get("coupon_rate")), _fmt_date(ref.get("maturity_date"))
    facts = [
        (tx["ticker"], ticker), ("ISIN", row.get("isin") or ""), (tx["issuer"], issuer),
        (tx["price"], f"{_fmt_num(row.get('price'), 2)} {currency}" if _num(row.get("price")) else ""),
        (tx["quote"], tx["of_nominal"].format(pct=_fmt_num(_metric(row, "price_pct"), 2))
         if _metric(row, "price_pct") is not None else ""),
        (tx["last_trade"], _fmt_date(row.get("last_trade_date")) or ""),
        (tx["nominal"], f"{_fmt_num(ref.get('nominal'))} {currency}" if _num(ref.get("nominal")) else ""),
        (tx["coupon"], tx["per_year"].format(rate=_fmt_num(rate, 2)) if rate is not None else ""),
        (tx["maturity"], maturity or ""),
        (tx["ytm"], f"{_fmt_num(ytm_value, 2)}%" if ytm_value is not None else ""),
    ]
    lead = tx["bond_lead"].format(ticker=ticker, issuer=issuer)
    if rate is not None:
        lead += tx["bond_coupon"].format(rate=_fmt_num(rate, 2))
    if maturity:
        lead += tx["bond_maturity"].format(date=maturity)
    base_path = f"/bond/{ticker}"
    path = localized(base_path, lang)
    return PageMeta(
        title=f"{tx['bond_title'].format(ticker=ticker, issuer=issuer)} | {SITE_NAME}",
        description=_clip(lead), canonical=path, lang=lang, alternate=base_path,
        jsonld=[_breadcrumbs((tx["home"], localized("/", lang)), (tx["bonds"], localized("/market", lang)),
                             (ticker, path))],
        body=f"<article><h1>{_esc(tx['bond_h1'].format(ticker=ticker, issuer=issuer))}</h1><p>{_esc(lead)}</p>"
             + _table(facts) + f"<p><a href=\"{localized('/market', lang)}\">{_esc(tx['all_bonds'])}</a></p></article>",
    )


async def _news_page(news_id: str) -> PageMeta | None:
    if not news_id.isdigit():
        raise _Missing(news_id)
    import news_store

    async def load() -> dict[str, Any] | None:
        return await asyncio.get_running_loop().run_in_executor(None, news_store.get_news_item, int(news_id))
    item = await _cached(f"news:{news_id}", load)
    if not item:
        raise _Missing(news_id)
    title = _clean_name(item.get("title_ru") or item.get("title"))
    summary = str(item.get("summary_ru") or item.get("snippet") or "").strip()
    detail = str(item.get("detail_ru") or "").strip()
    publication = _news_publication(item.get("published_at"))
    source_url = _web_url(item.get("url"))
    path = f"/news/{news_id}"
    paragraphs = "".join(f"<p>{_esc(p)}</p>" for p in (detail or summary).split("\n") if p.strip())
    tickers = [str(t) for t in item.get("tickers") or [] if re.fullmatch(r"[A-Z0-9]+", str(t))]
    ticker_links = "".join(f"<li><a href=\"/company/{t}\">{t}</a></li>" for t in tickers)
    description = _clip(summary or detail or title)
    publisher = {"@type": "Organization", "name": SITE_NAME, "url": SITE_URL,
                 "logo": f"{SITE_URL}{LOGO_PATH}"}
    article = {
        "@context": "https://schema.org", "@type": "NewsArticle", "headline": title,
        "url": f"{SITE_URL}{path}", "mainEntityOfPage": f"{SITE_URL}{path}",
        "description": description, "inLanguage": DEFAULT_LANGUAGE, "isAccessibleForFree": True,
        "publisher": publisher,
    }
    if publication:
        article["datePublished"] = publication[1]
    # Credit the platform only for text it prepared. The original outlet is
    # identified separately as the cited source, never as our summary's author.
    prepared = bool(detail or str(item.get("summary_ru") or "").strip())
    if prepared:
        article["author"] = {"@type": "Organization", "name": SITE_NAME, "url": SITE_URL}
    image = _web_url(item.get("image_url"))
    if image:
        article["image"] = image
    if source_url:
        article["isBasedOn"] = source_url
        citation = {"@type": "CreativeWork", "url": source_url,
                    "name": _clean_name(item.get("title") or item.get("source") or title)}
        if item.get("source"):
            citation["publisher"] = {"@type": "Organization", "name": item["source"]}
        article["citation"] = citation
    if tickers:
        article["about"] = [{"@type": "Organization", "name": t, "tickerSymbol": t,
                             "url": f"{SITE_URL}/company/{t}"} for t in tickers]
    return PageMeta(
        title=f"{title} | {SITE_NAME}", description=description,
        canonical=path, og_type="article", image=image,
        jsonld=[article, _breadcrumbs((_TX[DEFAULT_LANGUAGE]["home"], "/"),
                                      (_TX[DEFAULT_LANGUAGE]["news"], "/news"), (title, path))],
        body=(f"<article><h1>{_esc(title)}</h1>"
              + _news_time(item.get("published_at"))
              + paragraphs
              + ("<p>Изложение подготовлено UZStock по публикации источника.</p>" if prepared else "")
              + (f"<p>Эмитенты:</p><ul>{ticker_links}</ul>" if tickers else "")
              + _news_source_link(item)
              + '<p><a href="/news">Все новости</a></p>'
              + "</article>"),
    )


def _news_time(value: Any) -> str:
    publication = _news_publication(value)
    if publication is None:
        return ""
    stamp = publication[1]
    visible = (_fmt_date(stamp) or "") + (" " + stamp.split("T", 1)[1] if "T" in stamp else "")
    return f'<p><time datetime="{_esc(stamp)}">{_esc(visible)}</time></p>'


def _news_source_link(item: dict[str, Any]) -> str:
    url = _web_url(item.get("url"))
    if not url:
        return ""
    label = "Источник" + (f": {item['source']}" if item.get("source") else "")
    return f'<p><a href="{_esc(url)}" rel="nofollow noopener">{_esc(label)}</a></p>'


async def _news_index_page(lang: str) -> PageMeta:
    meta = _static_page("/news", lang)
    if lang != DEFAULT_LANGUAGE:
        return meta
    import news_store

    async def load() -> list[dict[str, Any]]:
        return await asyncio.get_running_loop().run_in_executor(
            None, lambda: news_store.get_news_feed(limit=200, days=180, order="recent", section="general"))

    items = await _cached("news-index", load)
    rows, entries = [], []
    seen: set[str] = set()
    for item in items:
        news_id = str(item.get("id") or "")
        title = _clean_name(item.get("title_ru") or item.get("title"))
        if not news_id.isdecimal() or news_id in seen or not title:
            continue
        seen.add(news_id)
        path = f"/news/{news_id}"
        summary = str(item.get("summary_ru") or item.get("snippet") or "").strip()
        rows.append(
            f'<li><article><h2><a href="{path}">{_esc(title)}</a></h2>'
            + _news_time(item.get("published_at"))
            + (f"<p>{_esc(_clip(summary, 240))}</p>" if summary else "")
            + _news_source_link(item) + "</article></li>")
        entries.append({"@type": "ListItem", "position": len(entries) + 1,
                        "url": f"{SITE_URL}{path}", "name": title})
    meta.body = (f"<h1>{_esc(meta.title.split(' | ')[0])}</h1><p>{_esc(meta.description)}</p>"
                 + "<ol>" + "".join(rows) + "</ol>")
    meta.jsonld = [{"@context": "https://schema.org", "@type": "CollectionPage",
                    "url": f"{SITE_URL}/news", "name": meta.title.split(" | ")[0],
                    "inLanguage": DEFAULT_LANGUAGE,
                    "mainEntity": {"@type": "ItemList", "numberOfItems": len(entries),
                                   "itemListElement": entries}}]
    return meta


async def _ai_report_page(ticker: str, meta: PageMeta) -> PageMeta:
    """A shared AI-report link previews the report's own headline and verdict.

    The page stays the company page (same canonical, nothing new to index);
    only the card a messenger draws for the link names what was shared.
    """
    from issuer_analysis_api import issuer_ai_report

    async def load() -> dict[str, Any] | None:
        try:
            return await asyncio.to_thread(issuer_ai_report, ticker, standard="nsbu", period=None,
                                           scope="separate", lang="ru", summary=True)
        except Exception:  # unknown issuer, or no analysis yet
            return None

    report = await _cached(f"ai-report:{ticker}", load)
    if not report or report.get("status") != "available" or not report.get("headline"):
        return meta
    period = f" · {report['period_label']}" if report.get("period_label") else ""
    meta.title = f"AI-финансовый отчёт {ticker}{period} | {SITE_NAME}"
    meta.description = _clip(" ".join(filter(None, (report.get("headline"), report.get("verdict_line")))), 300)
    return meta


async def _stock_board() -> list[dict[str, Any]]:
    from server.market.routes import api_market_stocks

    async def load() -> list[dict[str, Any]]:
        return _json_body(await api_market_stocks(_internal_request(), "stock")).get("stocks") or []
    return await _cached("stocks", load)


def _listed(rows: list[dict[str, Any]]) -> list[tuple[str, dict[str, Any]]]:
    """(ticker, row) for each row whose ticker can sit in a URL."""
    out = []
    for row in rows:
        ticker = str(row.get("ticker") or "").strip().upper()
        if re.fullmatch(r"[A-Z0-9]+", ticker):
            out.append((ticker, row))
    return out


def _by_cap(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(rows, key=lambda r: (-(_num(r.get("market_cap")) or 0), str(r.get("ticker"))))


def _stocks_table(rows: list[dict[str, Any]], lang: str) -> str:
    """Every listed company, linked to its own page: the list a search for
    "акции компаний Узбекистана" expects, and the internal links that tell
    Google the company pages matter."""
    from company_catalog import COMPANY_SECTORS

    tx, sectors = _TX[lang], _SECTORS[lang]
    head = "".join(f"<th scope=\"col\">{_esc(h)}</th>" for h in (
        tx["company"], tx["ticker"], tx["sector"], tx["price_uzs"], tx["trade_date"], tx["market_cap"]))
    body = []
    for ticker, row in _listed(rows):
        name = _clean_name(row.get("name") or ticker)
        price = _num(row.get("last_price"))
        cap = _num(row.get("market_cap"))
        cells = (
            f"<a href=\"{_esc(localized('/company/' + ticker, lang))}\">{_esc(name)}</a>", _esc(ticker),
            _esc(sectors.get(COMPANY_SECTORS.get(ticker, ""), "")),
            _fmt_num(price, 2) if price else "—", _esc(_fmt_date(row.get("last_trade_date")) or "—"),
            _esc(_fmt_money(cap, lang)) if cap else "—",
        )
        body.append("<tr>" + "".join(f"<td>{c}</td>" for c in cells) + "</tr>")
    return f"<table><thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table>" if body else ""


def _bonds_table(rows: list[dict[str, Any]], lang: str) -> str:
    tx = _TX[lang]
    head = "".join(f"<th scope=\"col\">{_esc(h)}</th>" for h in (
        tx["ticker"], tx["issuer"], tx["coupon"], tx["maturity_short"]))
    body = []
    for ticker, row in _listed(rows):
        ref = row.get("reference") or {}
        rate = _num(ref.get("coupon_rate"))
        cells = (
            f"<a href=\"{_esc(localized('/bond/' + ticker, lang))}\">{_esc(ticker)}</a>",
            _esc(_clean_name(row.get("issuer") or row.get("name") or "")),
            _esc(tx["per_year"].format(rate=_fmt_num(rate, 2))) if rate is not None else "—",
            _esc(_fmt_date(ref.get("maturity_date")) or "—"),
        )
        body.append("<tr>" + "".join(f"<td>{c}</td>" for c in cells) + "</tr>")
    return f"<table><thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table>" if body else ""


async def _settled(*loaders: Awaitable[Any]) -> list[Any]:
    """Each loader's value, or an empty list where it failed or was slow: a
    list that cannot be read leaves the page's own title and text standing."""
    out = []
    for value in await asyncio.gather(*loaders, return_exceptions=True):
        if isinstance(value, BaseException):
            http.logger.warning("seo: list snapshot failed", exc_info=value)
            value = []
        out.append(value or [])
    return out


def _static_page(path: str, lang: str) -> PageMeta:
    title, description = _PAGES[lang][path]
    meta = PageMeta(title=title, description=description, canonical=localized(path, lang),
                    lang=lang, alternate=path)
    if path == "/":
        meta.jsonld = [
            {"@context": "https://schema.org", "@type": "WebSite", "name": SITE_NAME,
             "url": f"{SITE_URL}{localized('/', lang)}", "inLanguage": lang},
            {"@context": "https://schema.org", "@type": "Organization", "name": SITE_NAME,
             "url": SITE_URL, "logo": f"{SITE_URL}{LOGO_PATH}"},
        ]
    return meta


async def _market_page(lang: str) -> PageMeta:
    tx = _TX[lang]
    meta = _static_page("/market", lang)
    stocks, bonds = await _settled(_stock_board(), _bonds_board())
    stocks_html, bonds_html = _stocks_table(_by_cap(stocks), lang), _bonds_table(bonds, lang)
    if not stocks_html and not bonds_html:
        return meta
    meta.body = (
        f"<h1>{_esc(meta.title.split(' | ')[0])}</h1>"
        + f"<p>{_esc(tx['market_intro'].format(count=len(_listed(stocks))) if stocks_html else meta.description)}</p>"
        + stocks_html
        + (f"<h2>{_esc(tx['bonds_heading'])}</h2>{bonds_html}" if bonds_html else "")
    )
    return meta


async def _latest_news() -> list[dict[str, Any]]:
    import news_store

    async def load() -> list[dict[str, Any]]:
        return await asyncio.get_running_loop().run_in_executor(
            None, lambda: news_store.get_news_feed(limit=8, days=60, order="recent"))
    return await _cached("home-news", load)


async def _home_page(lang: str) -> PageMeta:
    tx = _TX[lang]
    meta = _static_page("/", lang)

    async def no_news() -> list[Any]:
        return []
    # News is written in Russian only; the Uzbek page does not borrow it.
    stocks, news = await _settled(_stock_board(), _latest_news() if lang == DEFAULT_LANGUAGE else no_news())
    top = _stocks_table(_by_cap(stocks)[:15], lang)
    items = "".join(
        f"<li><a href=\"/news/{_esc(n['id'])}\">{_esc(_clean_name(n.get('title_ru') or n.get('title')))}</a></li>"
        for n in news if n.get("id") is not None and (n.get("title_ru") or n.get("title")))
    if not top and not items:
        return meta
    meta.body = (
        f"<h1>{_esc(meta.title.split(' | ')[0])}</h1><p>{_esc(meta.description)}</p>"
        + (f"<h2>{_esc(tx['largest'])}</h2>{top}"
           f"<p><a href=\"{localized('/market', lang)}\">{_esc(tx['all_stocks'])}</a></p>" if top else "")
        + (f"<h2>{_esc(tx['latest_news'])}</h2><ul>{items}</ul>" if items else "")
    )
    return meta


async def page_meta(full_path: str, query: dict[str, str] | None = None) -> PageMeta:
    lang, path = split_language("/" + (full_path or "").strip("/"))
    tx = _TX[lang]
    if path.startswith(_PRIVATE_PREFIXES):
        return PageMeta(title=_PAGES[lang]["/"][0], description=_PAGES[lang]["/"][1], noindex=True, lang=lang)
    # Comparison URLs describe interactive selections. Serve their deep links
    # without indexing every possible company/period configuration.
    if path == "/compare":
        title = "Kompaniyalarni solishtirish" if lang == "uz" else "Сравнение компаний"
        return PageMeta(title=f"{title} | {SITE_NAME}", noindex=True, lang=lang)
    path = _ALIASES.get(path, path)
    if not (path in _STATIC_PAGES or path.startswith(_ENTITY_PREFIXES)):
        return _not_found(lang)
    meta: PageMeta | None = None
    try:
        if path == "/":
            meta = await _home_page(lang)
        elif path == "/market":
            meta = await _market_page(lang)
        elif path == "/news":
            meta = await _news_index_page(lang)
        elif path.startswith("/company/"):
            ticker = path[len("/company/"):].split("/")[0].upper()
            meta = await _company_page(ticker, lang)
            # The AI report is written in Russian; other languages keep the company card.
            if meta is not None and lang == DEFAULT_LANGUAGE and (query or {}).get("report") == "ai":
                try:
                    meta = await _ai_report_page(ticker, meta)
                except Exception:
                    # Optional preview text must not discard an already valid
                    # company snapshot when the report store is slow or down.
                    http.logger.warning("seo: AI preview for %s failed", ticker, exc_info=True)
        elif path.startswith("/bond/"):
            meta = await _bond_page(path[len("/bond/"):].split("/")[0].upper(), lang)
        elif path.startswith("/chart/"):
            ticker = path[len("/chart/"):].split("/")[0].upper()
            meta = PageMeta(title=f"{tx['chart_title'].format(ticker=ticker)} | {SITE_NAME}",
                            description=tx["chart_description"].format(ticker=ticker),
                            canonical=localized(f"/chart/{ticker}", lang), lang=lang,
                            alternate=f"/chart/{ticker}")
        # News and corporate events exist in Russian only: under any language
        # prefix they name the Russian page as canonical, so nothing is indexed twice.
        elif path.startswith("/news/announcement/"):
            meta = PageMeta(title=f"{_TX[DEFAULT_LANGUAGE]['event_title']} | {SITE_NAME}", canonical=path)
        elif path.startswith("/news/"):
            meta = await _news_page(path[len("/news/"):].split("/")[0])
    except _Missing:
        return _not_found(lang)
    except Exception:
        http.logger.warning("seo: snapshot for %s failed", path, exc_info=True)
        if path == "/news":
            return _unavailable(path, lang)
        meta = None
    if meta is None and path in _STATIC_PAGES:
        meta = _static_page(path, lang)
    return _with_body(meta) if meta is not None else _unavailable(path, lang)


def _unavailable(path: str, lang: str) -> PageMeta:
    """A failed data read is neither a missing page nor homepage content."""
    tx = _TX[lang]
    parts = path.strip("/").split("/")
    identifier = parts[1] if len(parts) > 1 else ""
    if parts[0] in {"company", "bond", "chart"}:
        identifier = identifier.upper()
        path = f"/{parts[0]}/{identifier}"
    canonical = path if parts[0] == "news" else localized(path, lang)
    return _with_body(PageMeta(
        title=f"{identifier + ' — ' if identifier else ''}{tx['unavailable_title']} | {SITE_NAME}",
        description=tx["unavailable_description"], canonical=canonical,
        status=503, lang=lang))


def _with_body(meta: PageMeta) -> PageMeta:
    if not meta.body:
        meta.body = f"<h1>{_esc(meta.title.split(' | ')[0])}</h1><p>{_esc(meta.description)}</p>"
    meta.body = (
        "<div class=\"seo-snapshot\" style=\"max-width:960px;margin:0 auto;padding:16px;"
        "font-family:system-ui,sans-serif;line-height:1.5\">" + meta.body + _nav(meta.lang) + "</div>"
    )
    return meta


def _not_found(lang: str = DEFAULT_LANGUAGE) -> PageMeta:
    tx = _TX[lang]
    return _with_body(PageMeta(
        title=f"{tx['not_found_title']} | {SITE_NAME}", description=tx["not_found_description"],
        noindex=True, status=404, lang=lang))


def render(template: str, meta: PageMeta) -> str:
    head = [f"<title>{_esc(meta.title)}</title>",
            f"<meta name=\"description\" content=\"{_esc(meta.description)}\" />"]
    if meta.noindex:
        head.append("<meta name=\"robots\" content=\"noindex, nofollow\" />")
    if meta.canonical:
        url = f"{SITE_URL}{meta.canonical}"
        head += [f"<link rel=\"canonical\" href=\"{_esc(url)}\" />",
                 f"<meta property=\"og:url\" content=\"{_esc(url)}\" />"]
    if meta.alternate and not meta.noindex:
        head += [f"<link rel=\"alternate\" hreflang=\"{lang}\" href=\"{_esc(SITE_URL + localized(meta.alternate, lang))}\" />"
                 for lang in LANGUAGES]
        head.append(f"<link rel=\"alternate\" hreflang=\"x-default\" "
                    f"href=\"{_esc(SITE_URL + localized(meta.alternate, DEFAULT_LANGUAGE))}\" />")
    head += [
        f"<meta property=\"og:site_name\" content=\"{SITE_NAME}\" />",
        f"<meta property=\"og:type\" content=\"{_esc(meta.og_type)}\" />",
        f"<meta property=\"og:title\" content=\"{_esc(meta.title)}\" />",
        f"<meta property=\"og:description\" content=\"{_esc(meta.description)}\" />",
        f"<meta property=\"og:locale\" content=\"{_OG_LOCALE[meta.lang]}\" />",
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
    out = re.sub(r'<html lang="[^"]*"', f'<html lang="{meta.lang}"', out, count=1)
    if meta.body:
        out = out.replace('<div id="root"></div>', f'<div id="root">{meta.body}</div>', 1)
    return out


# --------------------------------------------------------------------------- robots / sitemap

def robots_txt() -> str:
    rules = "Allow: /\nDisallow: /api/\n" + "".join(
        f"Disallow: {localized(prefix, lang)}\n" for lang in LANGUAGES for prefix in _PRIVATE_PREFIXES)
    return (
        "User-agent: *\n"
        + rules
        + "\n"
        # Named so nobody wonders whether a blanket rule covers them: these are
        # the crawlers behind ChatGPT, Claude, Perplexity and Gemini answers.
        "User-agent: GPTBot\nUser-agent: OAI-SearchBot\nUser-agent: ChatGPT-User\n"
        "User-agent: ClaudeBot\nUser-agent: Claude-SearchBot\nUser-agent: Claude-User\n"
        "User-agent: PerplexityBot\nUser-agent: Google-Extended\n"
        + rules
        + "\n"
        f"Sitemap: {SITE_URL}/sitemap.xml\n"
        f"Sitemap: {SITE_URL}/news-sitemap.xml\n"
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
        entries += [(localized(path, lang), lastmod, freq)
                    for lang in URL_LANGUAGES for path, lastmod, freq in list(entries)]
        # News is written in Russian only, so it is listed once.
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


def _news_publication(value: Any) -> tuple[datetime, str] | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        published = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if published.tzinfo is None:
        # Legacy feeds and date-only sources do not retain a timezone. Use
        # their known calendar date; never invent a precise publication time.
        published = published.replace(hour=0, minute=0, second=0, microsecond=0,
                                      tzinfo=timezone.utc)
        text = published.date().isoformat()
    else:
        text = published.isoformat().replace("+00:00", "Z")
    return published, text


async def news_sitemap_xml() -> str:
    import news_store

    async def load() -> list[dict[str, Any]]:
        # Use the public feed so source visibility and relevance rules also
        # apply here. Three days allows for timestamps with timezone offsets;
        # the exact two-day window is checked below on every request.
        return await asyncio.get_running_loop().run_in_executor(
            None, lambda: news_store.get_news_feed(limit=200, days=3, order="recent"))

    items = await _cached("news-sitemap-items", load)
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=2)
    lines = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" '
             'xmlns:news="http://www.google.com/schemas/sitemap-news/0.9">']
    seen: set[str] = set()
    for item in items:
        news_id = str(item.get("id") or "")
        title = _clean_name(item.get("title_ru") or item.get("title"))
        publication = _news_publication(item.get("published_at"))
        if (not news_id.isdecimal() or news_id in seen or not title
                or publication is None or not cutoff <= publication[0] <= now):
            continue
        seen.add(news_id)
        lines.append(
            f"  <url><loc>{html.escape(f'{SITE_URL}/news/{news_id}')}</loc><news:news>"
            f"<news:publication><news:name>{html.escape(SITE_NAME)}</news:name>"
            f"<news:language>{DEFAULT_LANGUAGE}</news:language></news:publication>"
            f"<news:publication_date>{publication[1]}</news:publication_date>"
            f"<news:title>{html.escape(title)}</news:title></news:news></url>")
    lines.append("</urlset>")
    return "\n".join(lines) + "\n"


@router.get("/robots.txt", include_in_schema=False)
async def robots_route() -> PlainTextResponse:
    return PlainTextResponse(robots_txt(), headers={"Cache-Control": "public, max-age=3600"})


@router.get("/sitemap.xml", include_in_schema=False)
async def sitemap_route() -> Response:
    return Response(await sitemap_xml(), media_type="application/xml",
                    headers={"Cache-Control": "public, max-age=3600"})


@router.get("/news-sitemap.xml", include_in_schema=False)
async def news_sitemap_route() -> Response:
    try:
        xml = await news_sitemap_xml()
    except Exception:
        http.logger.warning("seo: news sitemap unavailable", exc_info=True)
        return PlainTextResponse("News sitemap temporarily unavailable", status_code=503,
                                 headers={"Retry-After": "60", "Cache-Control": "no-store"})
    return Response(xml, media_type="application/xml",
                    headers={"Cache-Control": "public, max-age=300"})


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

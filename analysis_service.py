from __future__ import annotations

import asyncio
import json
import math
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from functools import partial

from openai import OpenAI

from analyzer import (
    ANALYSIS_PROMPT,
    PROFILE_PROMPT,
    UZ_BENCHMARKS,
    build_html,
    compare_to_industry,
    compute_metrics,
    detect_industry,
    df_to_annual,
    df_to_quarterly,
    parse_response,
    slim_for_prompt,
    slim_metrics_for_prompt,
)
from cache import cache as analysis_cache
from main import get_data
from openinfo_collector import collect_company_data


OPENAI_API_KEY = os.getenv("OPENAI_API_KEY") or os.getenv("api_key")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5.4-mini").strip() or "gpt-5.4-mini"
OPENAI_REASONING_EFFORT = os.getenv("OPENAI_REASONING_EFFORT", "low").strip().lower() or "low"
ANALYSIS_POLICY_VERSION = "public-information-v2-market-data"

if not OPENAI_API_KEY:
    raise ValueError("OPENAI_API_KEY is required for the API service")

client = OpenAI(api_key=OPENAI_API_KEY)

WEB_RESEARCH_NOTE = (
    "Веб-поиск отключён для этой версии API. "
    "Используй только финансовую отчетность, рассчитанные метрики и ликвидность. "
    "Если каких-то данных не хватает, прямо скажи об этом и не выдумывай факты."
)

PROFILE_STYLE_NOTE = (
    "Пиши кратко, фактически и без воды. "
    "Никаких вступлений, повторов и рекламных формулировок. "
    "Если факт не подтверждён данными, не придумывай его."
)

ANALYSIS_STYLE_NOTE = (
    "Ответ должен быть плотным по смыслу и коротким. "
    "Ставь цифры, выводы и риски, а не общие рассуждения. "
    "Убирай канцелярит, маркетинг и длинные вступления. "
    "Каждая секция должна содержать только то, что реально помогает принять решение."
)

PUBLIC_ANALYSIS_POLICY = """
Публичный информационный контур анализа:
- Разрешено: фактический разбор отчетности, расчетных метрик, ликвидности бумаги, котировок, графиков цен, объемов торгов, эмитентов, облигаций, новостей, листинга/делистинга, режимов торгов, тарифов, терминов фондового рынка и общерыночной статистики, если эти данные явно переданы в текущем наборе.
- Если котировки, графики цен, объемы торгов, облигации, новости, листинг/делистинг, режимы торгов, тарифы, термины или общерыночная статистика не переданы, прямо напиши: "Нет данных в текущем наборе"; не придумывай их.
- Запрещено: персональные данные, прогнозная аналитика, инвестиционные рекомендации, индивидуальные аналитические выводы и юридические заключения.
- Не используй формулировки "покупать", "продавать", "держать", "набирать позицию", "размер позиции", "целевая цена", "ожидаемая доходность".
- Вердикт должен быть информационным статусом качества отчетности и риска, а не рекомендацией к сделке.
""".strip()

PUBLIC_ANALYSIS_POLICY_META = {
    "version": ANALYSIS_POLICY_VERSION,
    "scope": "public_information",
    "allowed": [
        "quotes",
        "price_charts",
        "trading_volumes",
        "dividends",
        "report_documents",
        "issuers",
        "bonds",
        "news",
        "listing_delisting",
        "trading_modes",
        "tariffs",
        "market_terms",
        "market_statistics",
        "financial_statements",
        "calculated_metrics",
    ],
    "excluded": [
        "personal_data",
        "forecast_analytics",
        "investment_recommendations",
        "individual_analytical_conclusions",
        "legal_opinions",
    ],
}

LANGUAGE_HINTS = {
    "ru": {
        "profile": (
            "Пиши весь содержательный текст по-русски. "
            "Сохраняй деловой, фактический тон. "
            "Не добавляй англоязычных вставок без необходимости."
        ),
        "analysis": (
            "Пиши весь содержательный текст по-русски. "
            "Метки секций оставляй ровно в том виде, как в шаблоне. "
            "Не переводи названия секций."
        ),
        "label": "Русский",
    },
    "en": {
        "profile": (
            "Write all substantive text in English. "
            "Keep the tone professional, factual, and concise. "
            "Do not add Russian phrases."
        ),
        "analysis": (
            "Write all substantive text in English. "
            "Keep the section tags exactly as written in the template. "
            "Do not translate the tag names."
        ),
        "label": "English",
    },
    "uz": {
        "profile": (
            "Barcha mazmunli matnni o'zbek tilida, lotin yozuvida yozing. "
            "Uslub professional, faktlarga asoslangan va qisqa bo'lsin. "
            "Ruscha yoki inglizcha iboralarni faqat zarur bo'lsa ishlating."
        ),
        "analysis": (
            "Barcha mazmunli matnni o'zbek tilida, lotin yozuvida yozing. "
            "Bo'lim teglari shablondagi ko'rinishda aynan qolishi kerak. "
            "Teg nomlarini tarjima qilmang."
        ),
        "label": "O'zbek",
    },
}


def _safe_float(value):
    if value is None:
        return None
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)):
        if isinstance(value, float) and math.isnan(value):
            return None
        return float(value)
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(parsed):
        return None
    return parsed


def _as_pct(value, digits: int = 2):
    parsed = _safe_float(value)
    if parsed is None:
        return None
    return round(parsed * 100, digits)


def _latest_item(items: list) -> dict:
    if not items:
        return {}
    for item in reversed(items):
        if isinstance(item, dict):
            return item
    return {}


def _growth_pct(current, previous):
    curr = _safe_float(current)
    prev = _safe_float(previous)
    if curr is None or prev in (None, 0):
        return None
    return round((curr - prev) / abs(prev) * 100, 2)


def _build_fibonacci_levels(points: list[dict]) -> dict:
    cleaned = []
    for point in points or []:
        high = _safe_float(point.get("high"))
        low = _safe_float(point.get("low"))
        close = _safe_float(point.get("close"))
        date_value = point.get("date")
        if high is None or low is None:
            continue
        cleaned.append({"date": date_value, "high": high, "low": low, "close": close})

    if len(cleaned) < 2:
        return {"status": "not_enough_price_history"}

    swing_high = max(cleaned, key=lambda item: item["high"])
    swing_low = min(cleaned, key=lambda item: item["low"])
    high = swing_high["high"]
    low = swing_low["low"]
    if high <= low:
        return {"status": "flat_price_range"}

    price_range = high - low
    latest_close = next(
        (item["close"] for item in reversed(cleaned) if item.get("close") is not None),
        None,
    )
    levels = {
        "0.0": round(high, 4),
        "23.6": round(high - price_range * 0.236, 4),
        "38.2": round(high - price_range * 0.382, 4),
        "50.0": round(high - price_range * 0.5, 4),
        "61.8": round(high - price_range * 0.618, 4),
        "78.6": round(high - price_range * 0.786, 4),
        "100.0": round(low, 4),
    }
    return {
        "status": "ok",
        "swing_high": {"date": swing_high.get("date"), "price": round(high, 4)},
        "swing_low": {"date": swing_low.get("date"), "price": round(low, 4)},
        "latest_close": round(latest_close, 4) if latest_close is not None else None,
        "levels": levels,
    }


def _compact_market_context(company_data: dict | None) -> dict:
    if not company_data or not company_data.get("ok"):
        return {
            "status": "not_available",
            "error": (company_data or {}).get("error"),
        }

    security = company_data.get("security") or {}
    market = company_data.get("market") or {}
    price_history = market.get("price_history") or {}
    points = price_history.get("points") or []
    sorted_points = sorted(points, key=lambda item: str(item.get("date") or ""))
    recent_points = [
        {
            "date": point.get("date"),
            "open": _safe_float(point.get("open")),
            "close": _safe_float(point.get("close")),
            "high": _safe_float(point.get("high")),
            "low": _safe_float(point.get("low")),
            "trading_volume": _safe_float(point.get("trading_volume")),
            "trading_value": _safe_float(point.get("trading_value")),
        }
        for point in sorted_points[-30:]
    ]

    reports = (company_data.get("reports") or {}).get("items") or []
    report_documents = [
        {
            "published_at": item.get("published_at"),
            "report_form": item.get("report_form"),
            "period_type": item.get("period_type"),
            "title": item.get("title"),
            "pdf_available": bool(item.get("pdf_url")),
            "excel_available": bool(item.get("excel_url")),
            "pdf_url": item.get("pdf_url"),
            "excel_url": item.get("excel_url"),
        }
        for item in reports[:10]
    ]

    dividends = (company_data.get("dividends") or {}).get("items") or []
    dividend_items = [
        {
            "decision_date": item.get("decision_date"),
            "pub_date": item.get("pub_date"),
            "ticker": item.get("ticker"),
            "common_share_amount": _safe_float(item.get("common_share_amount")),
            "common_share_percent": _safe_float(item.get("common_share_percent")),
            "privileged_share_amount": _safe_float(item.get("priviliged_share_amount")),
            "privileged_share_percent": _safe_float(item.get("priviliged_share_percent")),
            "link": item.get("link"),
        }
        for item in dividends[:5]
    ]

    return {
        "status": "ok",
        "company": company_data.get("company") or {},
        "security": {
            "ticker": security.get("ticker"),
            "isin_code": security.get("isin_code"),
            "issuer_short_name": security.get("issuer_short_name"),
            "stock_type": security.get("stock_type"),
            "market_id": security.get("market_id"),
            "board_id": security.get("board_id"),
        },
        "market_summary": market.get("summary") or {},
        "price_history_source": price_history.get("source_url"),
        "recent_price_history": recent_points,
        "fibonacci_levels": _build_fibonacci_levels(sorted_points),
        "dividends": {
            "count": (company_data.get("dividends") or {}).get("count", 0),
            "items": dividend_items,
        },
        "report_documents": {
            "count": (company_data.get("reports") or {}).get("count", 0),
            "items": report_documents,
        },
        "accounting_api_summary": (company_data.get("accounting") or {}).get("summary") or {},
    }


def _build_ifrs_snapshot(
    company_name: str,
    annual_data: list,
    quarterly_data: list,
    metrics: dict,
    industry: dict | None,
    liquidity_data: dict | None,
    language: str,
) -> dict:
    latest = _latest_item(annual_data)
    prev = annual_data[-2] if len(annual_data) >= 2 else {}
    latest_q = _latest_item(quarterly_data)

    revenue = _safe_float(latest.get("revenue"))
    gross_profit = _safe_float(latest.get("gross_profit"))
    ebit = _safe_float(latest.get("ebit"))
    net_income = _safe_float(latest.get("net_income"))
    total_assets = _safe_float(latest.get("total_assets"))
    equity = _safe_float(latest.get("equity"))
    current_assets = _safe_float(latest.get("current_assets"))
    current_liabilities = _safe_float(latest.get("current_liabilities"))
    cash = _safe_float(latest.get("cash"))
    long_term_debt = _safe_float(latest.get("long_term_debt"))
    inventory = _safe_float(latest.get("inventory"))
    receivables = _safe_float(latest.get("accounts_receivable"))
    payables = _safe_float(latest.get("accounts_payable"))
    retained_earnings = _safe_float(latest.get("retained_earnings"))
    interest_expense = _safe_float(latest.get("interest_expense"))

    working_capital = None
    if current_assets is not None and current_liabilities is not None:
        working_capital = round(current_assets - current_liabilities, 2)

    debt_to_equity = None
    if long_term_debt is not None and equity not in (None, 0):
        debt_to_equity = round(long_term_debt / equity, 3)

    debt_to_assets = None
    if long_term_debt is not None and total_assets not in (None, 0):
        debt_to_assets = round(long_term_debt / total_assets, 3)

    cash_to_debt = None
    if cash is not None and long_term_debt not in (None, 0):
        cash_to_debt = round(cash / long_term_debt, 3)

    current_ratio = None
    if current_assets is not None and current_liabilities not in (None, 0):
        current_ratio = round(current_assets / current_liabilities, 3)

    latest_revenue = revenue
    prev_revenue = _safe_float(prev.get("revenue")) if prev else None
    latest_gross_margin = _as_pct(latest.get("gross_profit_margin"))
    latest_ebit_margin = _as_pct(latest.get("ebit_margin"))
    latest_net_margin = _as_pct(latest.get("net_profit_margin"))
    latest_roe = _as_pct(latest.get("return_on_equity"))
    latest_roa = _as_pct(latest.get("return_on_assets"))

    trend_block = metrics.get("trends", {}) if isinstance(metrics, dict) else {}
    momentum_block = metrics.get("momentum", {}) if isinstance(metrics, dict) else {}
    piotroski = metrics.get("piotroski_f_score", {}) if isinstance(metrics, dict) else {}
    altman = metrics.get("altman_z_score", {}) if isinstance(metrics, dict) else {}
    buffett = metrics.get("buffett_criteria", {}) if isinstance(metrics, dict) else {}
    dcf = metrics.get("dcf", {}) if isinstance(metrics, dict) else {}
    graham = metrics.get("graham_number", {}) if isinstance(metrics, dict) else {}
    icr = metrics.get("interest_coverage", {}) if isinstance(metrics, dict) else {}

    green_flags: list[str] = []
    red_flags: list[str] = []

    def add_flag(bucket: list[str], text: str):
        if text not in bucket:
            bucket.append(text)

    revenue_yoy = _growth_pct(revenue, prev_revenue)
    if revenue_yoy is not None:
        if revenue_yoy >= 10:
            add_flag(green_flags, f"Выручка выросла на {revenue_yoy}% г/г")
        elif revenue_yoy <= 0:
            add_flag(red_flags, f"Выручка снизилась на {abs(revenue_yoy)}% г/г")

    if latest_net_margin is not None:
        if latest_net_margin >= 10:
            add_flag(green_flags, f"Чистая маржа {latest_net_margin}%")
        elif latest_net_margin < 0:
            add_flag(red_flags, f"Чистая маржа {latest_net_margin}%")

    if current_ratio is not None:
        if current_ratio >= 1.5:
            add_flag(green_flags, f"Текущая ликвидность {current_ratio}")
        elif current_ratio < 1:
            add_flag(red_flags, f"Текущая ликвидность {current_ratio}")

    if debt_to_equity is not None:
        if debt_to_equity <= 0.8:
            add_flag(green_flags, f"Долг/капитал {debt_to_equity}")
        elif debt_to_equity >= 2:
            add_flag(red_flags, f"Долг/капитал {debt_to_equity}")

    piotroski_score = piotroski.get("score")
    if isinstance(piotroski_score, (int, float)):
        if piotroski_score >= 7:
            add_flag(green_flags, f"Piotroski {piotroski_score}/9")
        elif piotroski_score <= 3:
            add_flag(red_flags, f"Piotroski {piotroski_score}/9")

    altman_score = altman.get("score")
    if isinstance(altman_score, (int, float)):
        if altman_score > 2.5:
            add_flag(green_flags, f"Altman Z {altman_score}")
        elif altman_score < 1.8:
            add_flag(red_flags, f"Altman Z {altman_score}")

    if icr.get("ratio") is not None:
        if icr["ratio"] > 5:
            add_flag(green_flags, f"Покрытие процентов {icr['ratio']}")
        elif icr["ratio"] < 2:
            add_flag(red_flags, f"Покрытие процентов {icr['ratio']}")

    if momentum_block.get("css") == "bullish":
        add_flag(green_flags, "Краткосрочный импульс положительный")
    elif momentum_block.get("css") == "bearish":
        add_flag(red_flags, "Краткосрочный импульс отрицательный")

    return {
        "company": company_name.strip() if company_name else "",
        "language": _normalize_language(language),
        "language_label": LANGUAGE_HINTS[_normalize_language(language)]["label"],
        "currency": "UZS (млн)",
        "periods": {
            "annual": (
                f"{annual_data[0].get('year')}–{annual_data[-1].get('year')}"
                if annual_data else None
            ),
            "quarterly": (
                f"{quarterly_data[0].get('period')}–{quarterly_data[-1].get('period')}"
                if quarterly_data else None
            ),
        },
        "income_statement": {
            "revenue": revenue,
            "revenue_yoy_pct": revenue_yoy,
            "gross_profit": gross_profit,
            "gross_margin_pct": latest_gross_margin,
            "ebit": ebit,
            "ebit_margin_pct": latest_ebit_margin,
            "net_income": net_income,
            "net_margin_pct": latest_net_margin,
            "quarterly_revenue": _safe_float(latest_q.get("revenue")),
            "quarterly_net_income": _safe_float(latest_q.get("net_income")),
            "quarterly_growth": latest_q.get("qoq_growth") if isinstance(latest_q, dict) else None,
        },
        "balance_sheet": {
            "total_assets": total_assets,
            "equity": equity,
            "cash": cash,
            "working_capital": working_capital,
            "current_assets": current_assets,
            "current_liabilities": current_liabilities,
            "current_ratio": current_ratio,
            "long_term_debt": long_term_debt,
            "debt_to_equity": debt_to_equity,
            "debt_to_assets": debt_to_assets,
            "cash_to_debt": cash_to_debt,
            "inventory": inventory,
            "receivables": receivables,
            "payables": payables,
            "retained_earnings": retained_earnings,
            "interest_expense": interest_expense,
        },
        "quality": {
            "roe_pct": latest_roe,
            "roa_pct": latest_roa,
            "interest_coverage": icr.get("ratio"),
            "piotroski": {
                "score": piotroski.get("score"),
                "max": piotroski.get("max"),
                "verdict": piotroski.get("verdict"),
            },
            "altman": {
                "score": altman.get("score"),
                "zone": altman.get("zone") or altman.get("verdict"),
            },
            "buffett": {
                "passed": buffett.get("passed"),
                "total": buffett.get("total"),
                "verdict": buffett.get("verdict"),
            },
            "dcf": {
                "intrinsic_value_bn": dcf.get("intrinsic_value_bn"),
                "signal": dcf.get("signal"),
                "verdict": dcf.get("verdict"),
            },
            "graham": {
                "fair_value_proxy": graham.get("estimated_fair_value_proxy") or graham.get("graham_number"),
                "upside_pct": graham.get("upside_pct"),
                "verdict": graham.get("verdict"),
            },
        },
        "trends": {
            "revenue": trend_block.get("revenue"),
            "profit": trend_block.get("profit"),
            "margin": trend_block.get("margin"),
            "debt": trend_block.get("debt"),
            "overall_score": trend_block.get("overall_score"),
            "overall_label": trend_block.get("overall_label"),
            "momentum": momentum_block,
        },
        "industry": industry or {},
        "liquidity": liquidity_data or {},
        "valuation_summary": {
            "score": metrics.get("total_score", {}).get("score") if isinstance(metrics, dict) else None,
            "grade": metrics.get("total_score", {}).get("grade") if isinstance(metrics, dict) else None,
            "summary": metrics.get("total_score", {}).get("summary") if isinstance(metrics, dict) else None,
        },
        "series": {
            "annual": [
                {
                    "year": row.get("year"),
                    "revenue": _safe_float(row.get("revenue")),
                    "gross_profit": _safe_float(row.get("gross_profit")),
                    "ebit": _safe_float(row.get("ebit")),
                    "net_income": _safe_float(row.get("net_income")),
                    "equity": _safe_float(row.get("equity")),
                    "total_assets": _safe_float(row.get("total_assets")),
                    "current_ratio": _safe_float(row.get("current_ratio")),
                    "debt_to_equity_ratio": _safe_float(row.get("debt_to_equity_ratio")),
                    "net_profit_margin": _safe_float(row.get("net_profit_margin")),
                }
                for row in annual_data
                if isinstance(row, dict)
            ],
            "quarterly": [
                {
                    "period": row.get("period"),
                    "revenue": _safe_float(row.get("revenue")),
                    "gross_profit": _safe_float(row.get("gross_profit")),
                    "ebit": _safe_float(row.get("ebit")),
                    "net_income": _safe_float(row.get("net_income")),
                }
                for row in quarterly_data
                if isinstance(row, dict)
            ],
        },
        "flags": {
            "green": green_flags,
            "red": red_flags,
        },
        "decision_inputs": [
            "Прибыльность и маржи",
            "Ликвидность и рабочий капитал",
            "Долговая нагрузка и покрытие процентов",
            "Качество прибыли (Piotroski / Altman / Buffett)",
            "Тренд выручки и квартальный импульс",
        ],
    }


def _normalize_language(language: str | None) -> str:
    value = (language or "ru").strip().lower()
    return value if value in LANGUAGE_HINTS else "ru"


def _language_hint(language: str | None, mode: str) -> str:
    lang = _normalize_language(language)
    return LANGUAGE_HINTS[lang][mode]


def _sanitize_reasoning_effort(value: str) -> str:
    allowed = {"none", "minimal", "low", "medium", "high", "xhigh"}
    return value if value in allowed else "low"


def api_call_with_retry(fn, max_retries: int = 6):
    for attempt in range(max_retries):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001
            status = getattr(exc, "status_code", None)
            response = getattr(exc, "response", None)
            if status is None and response is not None:
                status = getattr(response, "status_code", None)

            retriable = status in {429, 500, 502, 503, 504}
            if not retriable or attempt == max_retries - 1:
                raise

            wait = min(120, 10 * (2 ** attempt))
            headers = getattr(response, "headers", None)
            if headers:
                retry_after = headers.get("retry-after") or headers.get("Retry-After")
                if retry_after:
                    try:
                        wait = int(float(retry_after)) + 2
                    except (TypeError, ValueError):
                        pass

            print(f"   ⏳ OpenAI error (attempt {attempt + 1}/{max_retries}), waiting {wait}s...")
            time.sleep(wait)


def _responses_text(prompt: str, instructions: str, max_output_tokens: int) -> tuple[str, object]:
    def _call():
        return client.responses.create(
            model=OPENAI_MODEL,
            reasoning={"effort": _sanitize_reasoning_effort(OPENAI_REASONING_EFFORT)},
            instructions=instructions,
            input=prompt,
            max_output_tokens=max_output_tokens,
        )

    response = api_call_with_retry(_call)
    text = (getattr(response, "output_text", "") or "").strip()
    if not text:
        raise ValueError("OpenAI returned an empty response")
    return text, response


def build_summary(result: dict) -> dict:
    sections = result.get("sections") or {}
    metrics = result.get("metrics") or {}

    score = metrics.get("total_score", {}) if isinstance(metrics, dict) else {}
    verdict = sections.get("ВЕРДИКТ") or sections.get("VERDICT") or ""
    itog = sections.get("ИТОГ") or sections.get("CONCLUSION") or sections.get("ВЫВОД") or ""

    return {
        "verdict": verdict,
        "itog": itog,
        "score": score.get("score"),
        "grade": score.get("grade"),
        "score_summary": score.get("summary"),
        "annual_period": result.get("annual_period", ""),
        "quarterly_period": result.get("quarterly_period", ""),
        "cost": result.get("cost", 0.0),
        "company_name": result.get("company_name", ""),
        "from_cache": bool(result.get("from_cache")),
        "model": result.get("model", OPENAI_MODEL),
    }


COMPARISON_FIELDS = [
    {"key": "score", "label": "Общий score", "unit": "/100", "better": "higher"},
    {"key": "grade", "label": "Класс", "unit": "", "better": "higher"},
    {"key": "revenue", "label": "Выручка", "unit": "UZS млн", "better": "higher"},
    {"key": "revenue_growth_pct", "label": "Рост выручки", "unit": "%", "better": "higher"},
    {"key": "net_income", "label": "Чистая прибыль", "unit": "UZS млн", "better": "higher"},
    {"key": "net_income_growth_pct", "label": "Рост чистой прибыли", "unit": "%", "better": "higher"},
    {"key": "net_profit_margin_pct", "label": "Чистая маржа", "unit": "%", "better": "higher"},
    {"key": "roe_pct", "label": "ROE", "unit": "%", "better": "higher"},
    {"key": "roa_pct", "label": "ROA", "unit": "%", "better": "higher"},
    {"key": "debt_ratio_pct", "label": "Долг/активы", "unit": "%", "better": "lower"},
    {"key": "debt_to_equity_ratio", "label": "Debt/Equity", "unit": "x", "better": "lower"},
    {"key": "current_ratio", "label": "Current ratio", "unit": "x", "better": "higher"},
    {"key": "piotroski_score", "label": "Piotroski", "unit": "/9", "better": "higher"},
    {"key": "altman_score", "label": "Altman Z", "unit": "", "better": "higher"},
    {"key": "latest_price", "label": "Последняя цена", "unit": "UZS", "better": "neutral"},
    {"key": "day_change_percent", "label": "Изменение за день", "unit": "%", "better": "neutral"},
    {"key": "period_change_percent", "label": "Изменение за период", "unit": "%", "better": "neutral"},
    {"key": "avg_daily_trading_value", "label": "Средний дневной оборот", "unit": "UZS", "better": "higher"},
    {"key": "dividend_count", "label": "Дивидендные события", "unit": "шт.", "better": "higher"},
    {"key": "report_document_count", "label": "Отчеты PDF/Excel", "unit": "шт.", "better": "higher"},
]

COMPARISON_CATEGORY_METRICS = {
    "overall": ["score", "piotroski_score", "altman_score"],
    "profitability": ["net_profit_margin_pct", "roe_pct", "roa_pct"],
    "growth": ["revenue_growth_pct", "net_income_growth_pct"],
    "balance": ["current_ratio", "debt_ratio_pct", "debt_to_equity_ratio", "altman_score"],
    "market": ["avg_daily_trading_value", "period_change_percent"],
    "reporting": ["report_document_count", "dividend_count"],
}

COMPARISON_TABLES = {
    "overview": ["score", "grade", "latest_year", "ticker"],
    "profitability": ["revenue", "net_income", "net_profit_margin_pct", "roe_pct", "roa_pct"],
    "growth": ["revenue_growth_pct", "net_income_growth_pct", "period_change_percent"],
    "balance": ["debt_ratio_pct", "debt_to_equity_ratio", "current_ratio", "quick_ratio", "altman_score"],
    "market": ["latest_price", "day_change_percent", "avg_daily_trading_value", "total_trading_value"],
    "documents": ["dividend_count", "report_document_count", "pdf_report_count", "excel_report_count"],
}


def _round_metric(value, digits: int = 2):
    parsed = _safe_float(value)
    if parsed is None:
        return None
    return round(parsed, digits)


def _best_by(rows: list[dict], key: str, reverse: bool = True) -> dict | None:
    candidates = [row for row in rows if _safe_float(row.get(key)) is not None]
    if not candidates:
        return None
    return sorted(candidates, key=lambda row: _safe_float(row.get(key)), reverse=reverse)[0]


def _leader_payload(row: dict | None, key: str) -> dict | None:
    if not row:
        return None
    return {
        "company": row.get("company_name"),
        "ticker": row.get("ticker"),
        "metric": key,
        "value": row.get(key),
    }


def _field_by_key() -> dict[str, dict]:
    return {field["key"]: field for field in COMPARISON_FIELDS}


def _normalize_value(value, min_value: float, max_value: float, better: str) -> float | None:
    parsed = _safe_float(value)
    if parsed is None:
        return None
    if max_value == min_value:
        return 50.0
    if better == "lower":
        normalized = (max_value - parsed) / (max_value - min_value) * 100
    else:
        normalized = (parsed - min_value) / (max_value - min_value) * 100
    return round(max(0, min(100, normalized)), 2)


def _rank_metric(rows: list[dict], key: str, better: str) -> dict[str, int]:
    ranked = [
        row for row in rows
        if _safe_float(row.get(key)) is not None
    ]
    if not ranked:
        return {}
    reverse = better != "lower"
    ranked.sort(key=lambda row: _safe_float(row.get(key)), reverse=reverse)
    ranks = {}
    previous_value = None
    previous_rank = 0
    for index, row in enumerate(ranked, start=1):
        current_value = _safe_float(row.get(key))
        rank = previous_rank if current_value == previous_value else index
        ranks[row.get("input") or row.get("company_name")] = rank
        previous_value = current_value
        previous_rank = rank
    return ranks


def _build_normalized_comparison(rows: list[dict]) -> dict:
    normalized_fields = []
    row_map = {
        row.get("input") or row.get("company_name"): {
            "company_name": row.get("company_name"),
            "ticker": row.get("ticker"),
            "metrics": {},
        }
        for row in rows
    }

    for field in COMPARISON_FIELDS:
        key = field["key"]
        if field.get("better") == "neutral":
            continue
        values = [_safe_float(row.get(key)) for row in rows]
        values = [value for value in values if value is not None]
        if not values:
            continue
        min_value = min(values)
        max_value = max(values)
        ranks = _rank_metric(rows, key, field.get("better", "higher"))
        normalized_fields.append({
            **field,
            "min": round(min_value, 4),
            "max": round(max_value, 4),
        })
        for row in rows:
            row_key = row.get("input") or row.get("company_name")
            row_map[row_key]["metrics"][key] = {
                "raw": row.get(key),
                "normalized": _normalize_value(
                    row.get(key),
                    min_value,
                    max_value,
                    field.get("better", "higher"),
                ),
                "rank": ranks.get(row_key),
            }

    return {
        "method": "min_max_0_100",
        "description": (
            "Все числовые показатели приведены к шкале 0-100. "
            "Для метрик higher большее значение лучше; для lower меньшее значение лучше."
        ),
        "fields": normalized_fields,
        "rows": list(row_map.values()),
    }


def _category_score(row_metrics: dict, keys: list[str]) -> float | None:
    values = []
    for key in keys:
        metric = row_metrics.get(key) or {}
        normalized = _safe_float(metric.get("normalized"))
        if normalized is not None:
            values.append(normalized)
    if not values:
        return None
    return round(sum(values) / len(values), 2)


def _build_category_scores(normalized: dict) -> list[dict]:
    score_rows = []
    for row in normalized.get("rows", []):
        metrics = row.get("metrics") or {}
        categories = {
            category: _category_score(metrics, keys)
            for category, keys in COMPARISON_CATEGORY_METRICS.items()
        }
        available = [value for value in categories.values() if value is not None]
        composite = round(sum(available) / len(available), 2) if available else None
        score_rows.append({
            "company_name": row.get("company_name"),
            "ticker": row.get("ticker"),
            "composite_score": composite,
            **categories,
        })
    return score_rows


def _build_comparison_tables(rows: list[dict], normalized: dict, category_scores: list[dict]) -> dict:
    fields = _field_by_key()
    normalized_by_company = {
        row.get("company_name"): row.get("metrics") or {}
        for row in normalized.get("rows", [])
    }
    tables = {}
    for table_name, keys in COMPARISON_TABLES.items():
        columns = [
            {"key": "company_name", "label": "Компания"},
            {"key": "ticker", "label": "Тикер"},
        ]
        columns.extend(
            fields.get(key, {"key": key, "label": key, "unit": "", "better": "neutral"})
            for key in keys
            if key not in {"ticker"}
        )
        table_rows = []
        for row in rows:
            metrics = normalized_by_company.get(row.get("company_name"), {})
            table_row = {
                "company_name": row.get("company_name"),
                "ticker": row.get("ticker"),
            }
            for key in keys:
                if key == "ticker":
                    continue
                table_row[key] = {
                    "raw": row.get(key),
                    "normalized": (metrics.get(key) or {}).get("normalized"),
                    "rank": (metrics.get(key) or {}).get("rank"),
                }
            table_rows.append(table_row)
        tables[table_name] = {"columns": columns, "rows": table_rows}

    tables["category_scores"] = {
        "columns": [
            {"key": "company_name", "label": "Компания"},
            {"key": "ticker", "label": "Тикер"},
            {"key": "composite_score", "label": "Сводный балл", "unit": "/100"},
            {"key": "profitability", "label": "Прибыльность", "unit": "/100"},
            {"key": "growth", "label": "Рост", "unit": "/100"},
            {"key": "balance", "label": "Баланс", "unit": "/100"},
            {"key": "market", "label": "Рынок", "unit": "/100"},
            {"key": "reporting", "label": "Раскрытие", "unit": "/100"},
        ],
        "rows": category_scores,
    }
    return tables


def _build_comparison_charts(rows: list[dict], category_scores: list[dict]) -> list[dict]:
    labels = [
        {"key": "overall", "label": "Общая оценка"},
        {"key": "profitability", "label": "Прибыльность"},
        {"key": "growth", "label": "Рост"},
        {"key": "balance", "label": "Баланс"},
        {"key": "market", "label": "Рынок"},
        {"key": "reporting", "label": "Отчеты"},
    ]
    radar_datasets = [
        {
            "label": row.get("ticker") or row.get("company_name"),
            "company_name": row.get("company_name"),
            "data": [
                row.get("overall"),
                row.get("profitability"),
                row.get("growth"),
                row.get("balance"),
                row.get("market"),
                row.get("reporting"),
            ],
        }
        for row in category_scores
    ]
    company_axis = [
        {"company_name": row.get("company_name"), "ticker": row.get("ticker")}
        for row in rows
    ]
    return [
        {
            "id": "normalized_radar",
            "type": "radar",
            "title": "Сопоставимый профиль 0-100",
            "labels": labels,
            "datasets": radar_datasets,
        },
        {
            "id": "score_bar",
            "type": "bar",
            "title": "Общий score и сводный нормализованный балл",
            "x": company_axis,
            "series": [
                {"key": "score", "label": "Score", "data": [row.get("score") for row in rows]},
                {"key": "composite_score", "label": "Сводный 0-100", "data": [row.get("composite_score") for row in category_scores]},
            ],
        },
        {
            "id": "profitability_grouped_bar",
            "type": "grouped_bar",
            "title": "Прибыльность",
            "x": company_axis,
            "series": [
                {"key": "net_profit_margin_pct", "label": "Чистая маржа, %", "data": [row.get("net_profit_margin_pct") for row in rows]},
                {"key": "roe_pct", "label": "ROE, %", "data": [row.get("roe_pct") for row in rows]},
                {"key": "roa_pct", "label": "ROA, %", "data": [row.get("roa_pct") for row in rows]},
            ],
        },
        {
            "id": "balance_grouped_bar",
            "type": "grouped_bar",
            "title": "Баланс и риск",
            "x": company_axis,
            "series": [
                {"key": "debt_ratio_pct", "label": "Долг/активы, %", "data": [row.get("debt_ratio_pct") for row in rows]},
                {"key": "current_ratio", "label": "Current ratio", "data": [row.get("current_ratio") for row in rows]},
                {"key": "altman_score", "label": "Altman Z", "data": [row.get("altman_score") for row in rows]},
            ],
        },
        {
            "id": "market_bar",
            "type": "bar",
            "title": "Рыночная ликвидность",
            "x": company_axis,
            "series": [
                {"key": "avg_daily_trading_value", "label": "Средний дневной оборот", "data": [row.get("avg_daily_trading_value") for row in rows]},
                {"key": "period_change_percent", "label": "Изменение за период, %", "data": [row.get("period_change_percent") for row in rows]},
            ],
        },
        {
            "id": "documents_bar",
            "type": "stacked_bar",
            "title": "Доступность отчетов",
            "x": company_axis,
            "series": [
                {"key": "pdf_report_count", "label": "PDF", "data": [row.get("pdf_report_count") for row in rows]},
                {"key": "excel_report_count", "label": "Excel", "data": [row.get("excel_report_count") for row in rows]},
            ],
        },
    ]


def _build_comparative_ai_summary(
    rows: list[dict],
    leaders: dict,
    category_scores: list[dict],
    language: str,
) -> dict:
    prompt_payload = {
        "rows": [
            {
                key: row.get(key)
                for key in [
                    "company_name", "ticker", "score", "grade", "revenue", "revenue_growth_pct",
                    "net_income", "net_income_growth_pct", "net_profit_margin_pct", "roe_pct",
                    "roa_pct", "debt_ratio_pct", "debt_to_equity_ratio", "current_ratio",
                    "piotroski_score", "altman_score", "avg_daily_trading_value",
                    "period_change_percent", "dividend_count", "report_document_count",
                    "risk_flags",
                ]
            }
            for row in rows
        ],
        "leaders": leaders,
        "category_scores": category_scores,
    }
    prompt = (
        f"Language: {LANGUAGE_HINTS[language]['label']}.\n"
        "Write a compact comparative AI summary for 2-3 public issuers. "
        "Use only the JSON data below. Do not give investment recommendations, price targets or forecasts. "
        "Explain differences by facts and numbers. Return plain text with 4-7 short bullet-like lines.\n\n"
        f"{json.dumps(prompt_payload, ensure_ascii=False, indent=2)}"
    )
    instructions = (
        "You compare issuers using only provided metrics. "
        "Be factual, concise, professional, and do not invent missing data. "
        "No buy/sell/hold recommendations."
    )
    try:
        text, response = _responses_text(prompt, instructions, max_output_tokens=1200)
        usage = getattr(response, "usage", None)
        return {
            "ok": True,
            "text": text,
            "model": OPENAI_MODEL,
            "input_tokens": getattr(usage, "input_tokens", 0) if usage is not None else None,
            "output_tokens": getattr(usage, "output_tokens", 0) if usage is not None else None,
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "text": None,
            "error": str(exc),
        }


def _comparison_summary(rows: list[dict], leaders: dict, language: str) -> dict:
    leader = leaders.get("overall_leader") or {}
    profitability = leaders.get("profitability_leader") or {}
    balance = leaders.get("balance_quality_leader") or {}
    liquidity = leaders.get("market_liquidity_leader") or {}
    if language == "en":
        short = (
            f"Overall leader: {leader.get('company') or 'n/a'}. "
            f"Best profitability: {profitability.get('company') or 'n/a'}. "
            f"Best balance quality: {balance.get('company') or 'n/a'}. "
            f"Best market liquidity: {liquidity.get('company') or 'n/a'}."
        )
    elif language == "uz":
        short = (
            f"Umumiy lider: {leader.get('company') or 'n/a'}. "
            f"Rentabellik bo'yicha: {profitability.get('company') or 'n/a'}. "
            f"Balans sifati bo'yicha: {balance.get('company') or 'n/a'}. "
            f"Bozor likvidligi bo'yicha: {liquidity.get('company') or 'n/a'}."
        )
    else:
        short = (
            f"По общей оценке лидирует: {leader.get('company') or 'нет данных'}. "
            f"По прибыльности сильнее выглядит: {profitability.get('company') or 'нет данных'}. "
            f"По качеству баланса: {balance.get('company') or 'нет данных'}. "
            f"По рыночной ликвидности: {liquidity.get('company') or 'нет данных'}."
        )
    return {
        "short": short,
        "methodology": (
            "Сравнение детерминированное: финансовые метрики считаются из отчетности, "
            "рыночные данные берутся из OpenInfo, лидеры выбираются только по доступным числам."
        ),
        "compared_count": len(rows),
    }


def _compare_one_company(query: str) -> dict:
    annual_df, quarter_df, liquidity_df, fetched_name = get_data(query)
    annual_data = df_to_annual(annual_df)
    quarterly_data = df_to_quarterly(quarter_df)
    metrics = compute_metrics(annual_data, quarterly_data)
    liquidity_data = (
        liquidity_df.iloc[0].to_dict()
        if liquidity_df is not None and not liquidity_df.empty
        else None
    )
    if liquidity_data:
        metrics["market_liquidity"] = liquidity_data

    resolved_name = fetched_name or query
    latest = _latest_item(annual_data)
    previous = annual_data[-2] if len(annual_data) >= 2 else {}
    market_data = None
    try:
        market_data = collect_company_data(
            query,
            history_months=6,
            include_raw_reports=False,
            include_document_previews=False,
            validate_documents=False,
        )
    except Exception as exc:  # noqa: BLE001
        market_data = {"ok": False, "error": str(exc)}

    market_context = _compact_market_context(market_data)
    market_summary = market_context.get("market_summary") or {}
    security = market_context.get("security") or {}
    total_score = metrics.get("total_score") or {}
    piotroski = metrics.get("piotroski_f_score") or {}
    altman = metrics.get("altman_z_score") or {}
    report_docs = market_context.get("report_documents") or {}
    report_items = report_docs.get("items") or []

    debt_ratio = _round_metric(latest.get("debt_ratio"))
    current_ratio = _round_metric(latest.get("current_ratio"))
    quick_ratio = _round_metric(latest.get("quick_ratio"))
    debt_to_equity = _round_metric(latest.get("debt_to_equity_ratio"))
    balance_quality_score = 0.0
    if current_ratio is not None:
        balance_quality_score += min(current_ratio, 3) * 10
    if quick_ratio is not None:
        balance_quality_score += min(quick_ratio, 3) * 8
    if debt_ratio is not None:
        balance_quality_score -= debt_ratio / 2
    if debt_to_equity is not None:
        balance_quality_score -= debt_to_equity * 5

    risk_flags = []
    if _safe_float(altman.get("score")) is not None and _safe_float(altman.get("score")) < 1.8:
        risk_flags.append("low_altman_z")
    if debt_ratio is not None and debt_ratio > 60:
        risk_flags.append("high_debt_ratio")
    if _safe_float(market_summary.get("avg_daily_trading_value")) in (None, 0):
        risk_flags.append("low_or_missing_market_liquidity")
    if _safe_float(market_summary.get("period_change_percent")) is not None and _safe_float(market_summary.get("period_change_percent")) < -20:
        risk_flags.append("large_price_drawdown")

    return {
        "input": query,
        "company_name": resolved_name,
        "ticker": security.get("ticker"),
        "isin_code": security.get("isin_code"),
        "latest_year": latest.get("year"),
        "score": _round_metric(total_score.get("score")),
        "grade": total_score.get("grade"),
        "score_summary": total_score.get("summary"),
        "revenue": _round_metric(latest.get("revenue")),
        "revenue_growth_pct": _growth_pct(latest.get("revenue"), previous.get("revenue")),
        "net_income": _round_metric(latest.get("net_income")),
        "net_income_growth_pct": _growth_pct(latest.get("net_income"), previous.get("net_income")),
        "net_profit_margin_pct": _round_metric(latest.get("net_profit_margin")),
        "gross_profit_margin_pct": _round_metric(latest.get("gross_profit_margin")),
        "roe_pct": _round_metric(latest.get("return_on_equity")),
        "roa_pct": _round_metric(latest.get("return_on_assets")),
        "debt_ratio_pct": debt_ratio,
        "debt_to_equity_ratio": debt_to_equity,
        "current_ratio": current_ratio,
        "quick_ratio": quick_ratio,
        "balance_quality_score": round(balance_quality_score, 2),
        "piotroski_score": _round_metric(piotroski.get("score")),
        "altman_score": _round_metric(altman.get("score")),
        "altman_zone": altman.get("zone") or altman.get("verdict"),
        "latest_price": _round_metric(market_summary.get("latest_price")),
        "latest_trade_datetime": market_summary.get("latest_trade_datetime"),
        "day_change_percent": _round_metric(market_summary.get("day_change_percent")),
        "period_change_percent": _round_metric(market_summary.get("period_change_percent")),
        "avg_daily_trading_value": _round_metric(market_summary.get("avg_daily_trading_value")),
        "total_trading_value": _round_metric(market_summary.get("total_trading_value")),
        "dividend_count": (market_context.get("dividends") or {}).get("count"),
        "report_document_count": report_docs.get("count"),
        "pdf_report_count": sum(1 for item in report_items if item.get("pdf_available")),
        "excel_report_count": sum(1 for item in report_items if item.get("excel_available")),
        "risk_flags": risk_flags,
        "market_context": market_context,
    }


def build_company_comparison(
    companies: list[str],
    language: str = "ru",
    include_ai_summary: bool = True,
) -> dict:
    language = _normalize_language(language)
    cleaned = []
    seen = set()
    for company in companies:
        value = (company or "").strip()
        key = value.lower()
        if value and key not in seen:
            cleaned.append(value)
            seen.add(key)
    if not 2 <= len(cleaned) <= 3:
        raise ValueError("Compare requires 2 or 3 unique companies")

    rows = []
    errors = []
    with ThreadPoolExecutor(max_workers=len(cleaned)) as executor:
        futures = {executor.submit(_compare_one_company, company): company for company in cleaned}
        for future in as_completed(futures):
            company = futures[future]
            try:
                rows.append(future.result())
            except Exception as exc:  # noqa: BLE001
                errors.append({"company": company, "error": str(exc)})

    rows.sort(key=lambda row: cleaned.index(row.get("input")) if row.get("input") in cleaned else 999)
    if len(rows) < 2:
        raise ValueError(f"Not enough comparable companies. Errors: {errors}")

    overall_ranking = sorted(
        rows,
        key=lambda row: _safe_float(row.get("score")) if _safe_float(row.get("score")) is not None else -1,
        reverse=True,
    )
    leaders = {
        "overall_leader": _leader_payload(_best_by(rows, "score"), "score"),
        "profitability_leader": _leader_payload(_best_by(rows, "net_profit_margin_pct"), "net_profit_margin_pct"),
        "roe_leader": _leader_payload(_best_by(rows, "roe_pct"), "roe_pct"),
        "balance_quality_leader": _leader_payload(_best_by(rows, "balance_quality_score"), "balance_quality_score"),
        "market_liquidity_leader": _leader_payload(_best_by(rows, "avg_daily_trading_value"), "avg_daily_trading_value"),
        "lowest_debt_ratio": _leader_payload(_best_by(rows, "debt_ratio_pct", reverse=False), "debt_ratio_pct"),
    }
    normalized_metrics = _build_normalized_comparison(rows)
    category_scores = _build_category_scores(normalized_metrics)
    normalized_ranking = sorted(
        category_scores,
        key=lambda row: _safe_float(row.get("composite_score")) if _safe_float(row.get("composite_score")) is not None else -1,
        reverse=True,
    )
    tables = _build_comparison_tables(rows, normalized_metrics, category_scores)
    charts = _build_comparison_charts(rows, category_scores)
    comparative_ai_summary = (
        _build_comparative_ai_summary(rows, leaders, category_scores, language)
        if include_ai_summary
        else {"ok": False, "text": None, "skipped": True}
    )

    return {
        "ok": True,
        "language": language,
        "input_companies": cleaned,
        "comparison": {
            "fields": COMPARISON_FIELDS,
            "rows": rows,
            "normalized_metrics": normalized_metrics,
            "category_scores": category_scores,
            "tables": tables,
            "charts": charts,
            "leaders": leaders,
            "ranking": [
                {
                    "rank": index + 1,
                    "company": row.get("company_name"),
                    "ticker": row.get("ticker"),
                    "score": row.get("score"),
                    "grade": row.get("grade"),
                }
                for index, row in enumerate(overall_ranking)
            ],
            "normalized_ranking": [
                {
                    "rank": index + 1,
                    "company": row.get("company_name"),
                    "ticker": row.get("ticker"),
                    "composite_score": row.get("composite_score"),
                }
                for index, row in enumerate(normalized_ranking)
            ],
            "summary": _comparison_summary(rows, leaders, language),
            "comparative_ai_summary": comparative_ai_summary,
            "errors": errors,
        },
    }


def _company_profile_prompt(company_name: str, annual_data: list, quarterly_data: list, liquidity_data: dict | None, language: str = "ru") -> str:
    slim = slim_for_prompt(annual_data, quarterly_data)
    fin_short = {
        "annual": [
            {
                k: v
                for k, v in r.items()
                if k in {"year", "revenue", "net_income", "total_assets", "equity", "net_profit_margin", "yoy_growth"}
            }
            for r in slim["annual"]
        ],
        "latest_q": slim["quarterly"][-1] if slim["quarterly"] else {},
        "liquidity": liquidity_data or {},
    }
    prompt = PROFILE_PROMPT.format(
        company=company_name,
        web_research=WEB_RESEARCH_NOTE,
        financials_json=json.dumps(fin_short, ensure_ascii=False),
    )
    lang = _normalize_language(language)
    return f"Язык ответа: {LANGUAGE_HINTS[lang]['label']}.\n\n{prompt}"


def build_company_profile(company_name: str, annual_data: list, quarterly_data: list,
                          liquidity_data: dict | None = None,
                          language: str | None = "ru") -> str:
    lang = _normalize_language(language)
    prompt = _company_profile_prompt(company_name, annual_data, quarterly_data, liquidity_data, lang)
    print(f"   📋 Generating profile ({LANGUAGE_HINTS[lang]['label']})...")

    instructions = (
        "Ты пишешь краткий профиль компании для инвестиционного отчета. "
        "Без markdown-заголовков, вступлений и лишних пояснений. "
        "Опирайся только на финансовые данные и заметку о веб-поиске; не выдумывай факты. "
        f"{_language_hint(lang, 'profile')}"
    )
    profile, response = _responses_text(f"{PROFILE_STYLE_NOTE}\n\n{prompt}", instructions, max_output_tokens=1200)

    usage = getattr(response, "usage", None)
    if usage is not None:
        in_tok = getattr(usage, "input_tokens", 0) or 0
        out_tok = getattr(usage, "output_tokens", 0) or 0
        print(f"   ✅ Profile ready (in={in_tok}, out={out_tok})")
    return profile


def _analysis_prompt(
    company_name: str,
    company_profile: str,
    annual_data: list,
    quarterly_data: list,
    liquidity_data: dict | None,
    language: str = "ru",
) -> tuple[str, dict, dict, str, str]:
    slim = slim_for_prompt(annual_data, quarterly_data)

    annual_period = (
        f"{slim['annual'][0]['year']}–{slim['annual'][-1]['year']}"
        if slim["annual"] else "нет данных"
    )
    quarterly_period = (
        f"{slim['quarterly'][0]['period']}–{slim['quarterly'][-1]['period']}"
        if slim["quarterly"] else "квартальные данные недоступны"
    )

    metrics = compute_metrics(annual_data, quarterly_data)
    if liquidity_data:
        metrics["market_liquidity"] = liquidity_data

    industry = detect_industry(company_name, WEB_RESEARCH_NOTE, company_profile)
    ind_compare = compare_to_industry(metrics, industry)
    metrics["industry"] = ind_compare
    if "dcf" in metrics and industry.get("wacc"):
        metrics["dcf"]["wacc_used_sector"] = round(industry["wacc"] * 100, 1)

    web_brief = WEB_RESEARCH_NOTE[:1400]
    prompt_metrics = slim_metrics_for_prompt(metrics)

    industry_context_str = (
        f"Отрасль: {industry.get('sector_name', 'не определена')}\n"
        f"Результат vs бенчмарк: {ind_compare.get('verdict', '')}\n"
        f"Хороших показателей: {ind_compare.get('good_count', 0)}/5, "
        f"Слабых: {ind_compare.get('weak_count', 0)}/5\n"
        f"Примечание: {ind_compare.get('capex_note', '')}"
    ) if industry else "Отрасль не определена — используй общие нормы UZ"

    prompt = ANALYSIS_PROMPT.format(
        uz_benchmarks=UZ_BENCHMARKS.format(industry_context=industry_context_str),
        currency=slim["currency"],
        company=company_name,
        company_profile=company_profile,
        web_brief=web_brief,
        metrics_json=json.dumps(prompt_metrics, ensure_ascii=False, indent=1),
        liquidity_json=json.dumps(liquidity_data or {"status": "нет данных"}, ensure_ascii=False, indent=1),
        annual_period=annual_period,
        annual_json=json.dumps(slim["annual"], ensure_ascii=False),
        quarterly_period=quarterly_period,
        quarterly_json=json.dumps(slim["quarterly"], ensure_ascii=False),
    )
    lang = _normalize_language(language)
    return f"Язык ответа: {LANGUAGE_HINTS[lang]['label']}.\n\n{ANALYSIS_STYLE_NOTE}\n\n{prompt}", metrics, ind_compare, annual_period, quarterly_period


def _analysis_prompt_v2(
    company_name: str,
    company_profile: str,
    annual_data: list,
    quarterly_data: list,
    liquidity_data: dict | None,
    language: str = "ru",
    company_data: dict | None = None,
) -> tuple[str, dict, dict, str, str, dict, dict]:
    slim = slim_for_prompt(annual_data, quarterly_data)

    annual_period = (
        f"{slim['annual'][0]['year']}–{slim['annual'][-1]['year']}"
        if slim["annual"] else "нет данных"
    )
    quarterly_period = (
        f"{slim['quarterly'][0]['period']}–{slim['quarterly'][-1]['period']}"
        if slim["quarterly"] else "квартальные данные недоступны"
    )

    metrics = compute_metrics(annual_data, quarterly_data)
    if liquidity_data:
        metrics["market_liquidity"] = liquidity_data

    industry = detect_industry(company_name, WEB_RESEARCH_NOTE, company_profile)
    ind_compare = compare_to_industry(metrics, industry)
    metrics["industry"] = ind_compare
    if "dcf" in metrics and industry.get("wacc"):
        metrics["dcf"]["wacc_used_sector"] = round(industry["wacc"] * 100, 1)

    prompt_metrics = slim_metrics_for_prompt(metrics)
    industry_context_str = (
        f"Отрасль: {industry.get('sector_name', 'не определена')}\n"
        f"Результат vs бенчмарк: {ind_compare.get('verdict', '')}\n"
        f"Хороших показателей: {ind_compare.get('good_count', 0)}/5, "
        f"Слабых: {ind_compare.get('weak_count', 0)}/5\n"
        f"Примечание: {ind_compare.get('capex_note', '')}"
    ) if industry else "Отрасль не определена — используй общие нормы UZ"

    lang = _normalize_language(language)
    ifrs_snapshot = _build_ifrs_snapshot(
        company_name=company_name,
        annual_data=annual_data,
        quarterly_data=quarterly_data,
        metrics=metrics,
        industry=ind_compare,
        liquidity_data=liquidity_data,
        language=lang,
    )
    market_context = _compact_market_context(company_data)
    if market_context.get("status") == "ok":
        metrics["market_context"] = {
            "security": market_context.get("security"),
            "market_summary": market_context.get("market_summary"),
            "fibonacci_levels": market_context.get("fibonacci_levels"),
            "dividend_count": (market_context.get("dividends") or {}).get("count"),
            "report_document_count": (market_context.get("report_documents") or {}).get("count"),
        }

    prompt = f"""
Ты — инвестиционный аналитик, который пишет короткую и строгую записку по отчётности.
Твоя задача — не пересказывать данные, а объяснить экономический смысл для инвестора.

Язык ответа: {LANGUAGE_HINTS[lang]['label']}

Жёсткие правила:
{PUBLIC_ANALYSIS_POLICY}

- Use PUBLIC MARKET DATA for quotes, price history, trading volumes, dividends, report documents and Fibonacci levels. If it is not available, say the market data is missing.

- Используй только данные из отчётности, расчётных метрик, IFRS snapshot и PUBLIC MARKET DATA ниже.
- Если чего-то не хватает, прямо скажи "Недостаточно данных".
- Никаких общих фраз, маркетинга, воды, литературных сравнений и лишних вступлений.
- Каждое важное утверждение должно опираться на цифру, динамику или явно названный показатель.
- Сравнивай компанию прежде всего с нормами UZ-рынка, а не с глобальными западными стандартами.
- Сначала прибыльность и качество прибыли, потом ликвидность, затем долговая нагрузка, затем оценка и только потом вывод.
- Техническая секция [ФИБОНАЧЧИ] допускается только если есть реальные рыночные уровни; иначе напиши "Недостаточно рыночных данных".
- Не выдумывай денежный поток, EPS, количество акций или цену, если этих данных нет.

Фокус анализа по МСФО:
1) Выручка и её динамика
2) Валовая прибыль и валовая маржа
3) EBIT и операционная маржа
4) Чистая прибыль и чистая маржа
5) Рабочий капитал, текущая ликвидность и денежная позиция
6) Долг, покрытие процентов и устойчивость баланса
7) ROE, ROA и качество роста
8) Piotroski, Altman, Buffett, DCF и Graham как подтверждение, а не как единственный аргумент

Компания:
{company_name}

Валюта и масштаб:
{slim["currency"]}

IFRS SNAPSHOT:
{json.dumps(ifrs_snapshot, ensure_ascii=False, indent=2)}

PUBLIC MARKET DATA:
{json.dumps(market_context, ensure_ascii=False, indent=2)}

Промежуточная отрасль и бенчмарк:
{industry_context_str}

Краткие расчётные метрики:
{json.dumps(prompt_metrics, ensure_ascii=False, indent=2)}

Ликвидность бумаги:
{json.dumps(liquidity_data or {"status": "нет данных"}, ensure_ascii=False, indent=2)}

Годовые данные:
{json.dumps(slim["annual"], ensure_ascii=False, indent=2)}

Квартальные данные:
{json.dumps(slim["quarterly"], ensure_ascii=False, indent=2)}

Формат ответа:
[СКОРИНГ]
Оценка: XX/100
Класс: A/B/C/D
Расшифровка: 2-3 коротких предложения без воды, но с числами.

[ДОСЬЕ]
3-4 предложения о том, чем зарабатывает компания и какой у неё экономический профиль.

[ЧТО_С_ДЕНЬГАМИ]
Сначала объясни, растёт ли выручка и маржа.
Потом объясни, зарабатывает ли компания на операционной деятельности.
Потом оцени ликвидность, рабочий капитал и долговую нагрузку.
Нельзя повторять одни и те же мысли разными словами.

[ТРЕНД]
Покажи направление по выручке, прибыли, маржам и долгу за 3-5 лет.
Если тренд смешанный, так и напиши.

[ФИБОНАЧЧИ]
Если нет рыночных уровней, напиши только: "Недостаточно рыночных данных".

[ОЦЕНКА_ЦЕНЫ]
Оцени, выглядит ли компания дешёвой или дорогой по DCF, Graham, Piotroski, Altman и Buffett.
Никакой абстракции без цифр.

[КАТАЛИЗАТОРЫ]
Назови 2-4 фактических фактора, которые уже видны в данных и влияют на текущую оценку риска или качества отчетности.
Не прогнозируй будущие события и не обещай изменение цены.

[СИЛЬНЫЕ_СТОРОНЫ]
Только сильные стороны с числами и кратким смыслом.

[СЛАБЫЕ_СТОРОНЫ]
Только слабые стороны с числами и кратким смыслом.

[РЫНОЧНЫЕ_ДАННЫЕ]
Проверь публичный контур: котировки, графики цен, объемы торгов, облигации, новости, листинг/делистинг, режимы торгов, тарифы, термины и общерыночная статистика.
По каждому типу данных коротко укажи: "есть в текущем наборе" или "нет данных в текущем наборе".
Не добавляй прогнозную аналитику.

[ВЕРДИКТ]
Выбери один информационный статус: СИЛЬНАЯ ОТЧЕТНОСТЬ / УМЕРЕННАЯ ОТЧЕТНОСТЬ / СЛАБАЯ ОТЧЕТНОСТЬ / ПОВЫШЕННЫЙ РИСК / НЕДОСТАТОЧНО ДАННЫХ.
Кратко объясни статус через цифры. Не давай рекомендацию к покупке, продаже или удержанию.

[ОГРАНИЧЕНИЯ_ПУБЛИЧНОГО_КОНТУРА]
Коротко укажи, что анализ не содержит персональных данных, прогнозной аналитики, инвестиционных рекомендаций, индивидуальных аналитических выводов и юридических заключений.
Если каких-то публичных рыночных данных не хватает, перечисли это как ограничение данных.

[ИТОГ]
4-6 предложений простым и профессиональным языком.
Без воды. Без терминов без объяснения. Не превращай итог в инвестиционную рекомендацию.
""".strip()

    return (
        f"Язык ответа: {LANGUAGE_HINTS[lang]['label']}.\n\n{ANALYSIS_STYLE_NOTE}\n\n{prompt}",
        metrics,
        ind_compare,
        annual_period,
        quarterly_period,
        ifrs_snapshot,
        market_context,
    )


def run_analysis(company_name: str, company_profile: str, annual_data: list,
                 quarterly_data: list, liquidity_data: dict | None = None,
                 language: str | None = "ru",
                 company_data: dict | None = None) -> tuple:
    lang = _normalize_language(language)
    prompt, metrics, ind_compare, annual_period, quarterly_period, ifrs_snapshot, market_context = _analysis_prompt_v2(
        company_name,
        company_profile,
        annual_data,
        quarterly_data,
        liquidity_data,
        lang,
        company_data,
    )

    print(
        f"   📊 Metrics: Piotroski={metrics.get('piotroski_f_score', {}).get('score', '?')}/9, "
        f"Altman={metrics.get('altman_z_score', {}).get('score', '?')}, "
        f"Industry={ind_compare.get('sector_name', '?')}, "
        f"Score={metrics.get('total_score', {}).get('score', '?')}/100"
    )
    print(f"   📤 Running analysis ({LANGUAGE_HINTS[lang]['label']})...")

    instructions = (
        "Ты строго следуешь формату ответа. "
        "КАЖДАЯ секция ОБЯЗАТЕЛЬНО начинается с метки в квадратных скобках: [СКОРИНГ], [ДОСЬЕ], [ТРЕНД] и т. д. "
        "Не используй markdown заголовки (##). Не пропускай ни одну секцию. "
        "Пиши сухо, по цифрам и фактам, без воды, повторов и длинных вступлений. "
        "Если данных недостаточно — напиши 'Недостаточно данных' внутри секции, но секцию не пропускай. "
        f"{_language_hint(lang, 'analysis')}"
    )
    raw, response = _responses_text(prompt, instructions, max_output_tokens=8000)

    usage = getattr(response, "usage", None)
    input_tokens = getattr(usage, "input_tokens", 0) or 0
    output_tokens = getattr(usage, "output_tokens", 0) or 0
    cost = (input_tokens / 1_000_000 * 0.25) + (output_tokens / 1_000_000 * 2.0)
    print(f"   ✅ in={input_tokens} out={output_tokens} | ~${cost:.4f}")

    return raw, annual_period, quarterly_period, cost, metrics, ifrs_snapshot, market_context


async def run_company_analysis(company_name: str, force_refresh: bool = False, language: str = "ru") -> dict:
    company_name = (company_name or "").strip()
    if not company_name:
        raise ValueError("company_name cannot be empty")
    language = _normalize_language(language)

    if not force_refresh:
        cached = analysis_cache.get(company_name, language=language)
        if cached and cached.get("analysis_policy_version") == ANALYSIS_POLICY_VERSION:
            cached["from_cache"] = True
            cached["source"] = "cache"
            cached.setdefault("model", OPENAI_MODEL)
            cached.setdefault("language", language)
            cached.setdefault("language_label", LANGUAGE_HINTS[language]["label"])
            cached.setdefault("ifrs_snapshot", {})
            cached.setdefault("market_data", {})
            cached.setdefault("market_context", {})
            cached.setdefault("analysis_policy", PUBLIC_ANALYSIS_POLICY_META)
            return cached

    loop = asyncio.get_running_loop()
    financials_future = loop.run_in_executor(
        None, partial(get_data, company_name)
    )
    company_data_future = loop.run_in_executor(
        None,
        partial(
            collect_company_data,
            company_name,
            history_months=6,
            include_raw_reports=False,
            include_document_previews=False,
            validate_documents=False,
        ),
    )
    annual_df, quarter_df, liquidity_df, fetched_name = await financials_future
    try:
        company_data = await company_data_future
    except Exception as exc:  # noqa: BLE001
        print(f"   Market data collection failed for '{company_name}': {exc}")
        company_data = {"ok": False, "error": str(exc)}
    if annual_df is None or quarter_df is None:
        raise ValueError(f"Данные не найдены для «{company_name}»")

    annual_data = await loop.run_in_executor(None, df_to_annual, annual_df)
    quarterly_data = await loop.run_in_executor(None, df_to_quarterly, quarter_df)
    liquidity_data = (
        liquidity_df.iloc[0].to_dict()
        if liquidity_df is not None and not liquidity_df.empty
        else None
    )
    resolved_name = fetched_name or company_name

    company_profile = await loop.run_in_executor(
        None, partial(build_company_profile, resolved_name, annual_data, quarterly_data, liquidity_data, language)
    )
    raw_analysis, annual_period, quarterly_period, cost, metrics, ifrs_snapshot, market_context = await loop.run_in_executor(
        None,
        partial(
            run_analysis,
            resolved_name,
            company_profile,
            annual_data,
            quarterly_data,
            liquidity_data,
            language,
            company_data,
        ),
    )
    web_research = WEB_RESEARCH_NOTE
    html_report = await loop.run_in_executor(
        None,
        partial(
            build_html,
            resolved_name,
            company_profile,
            web_research,
            raw_analysis,
            annual_period,
            quarterly_period,
            cost,
            metrics,
        ),
    )

    result = {
        "company_input": company_name,
        "company_name": resolved_name,
        "ticker": ((company_data.get("security") or {}).get("ticker") if isinstance(company_data, dict) else None),
        "html_report": html_report,
        "raw_analysis": raw_analysis,
        "sections": parse_response(raw_analysis),
        "annual_period": annual_period,
        "quarterly_period": quarterly_period,
        "cost": cost,
        "metrics": metrics,
        "ifrs_snapshot": ifrs_snapshot,
        "liquidity": liquidity_data,
        "market_data": company_data,
        "market_context": market_context,
        "from_cache": False,
        "source": "fresh",
        "model": OPENAI_MODEL,
        "language": language,
        "language_label": LANGUAGE_HINTS[language]["label"],
        "analysis_policy_version": ANALYSIS_POLICY_VERSION,
        "analysis_policy": PUBLIC_ANALYSIS_POLICY_META,
    }
    try:
        analysis_cache.set(company_name, result, language=language)
    except Exception as exc:  # noqa: BLE001
        print(f"   ⚠️ Cache write failed for '{resolved_name}': {exc}")
    return result

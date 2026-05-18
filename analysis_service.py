from __future__ import annotations

import asyncio
import json
import math
import os
import time
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


OPENAI_API_KEY = os.getenv("OPENAI_API_KEY") or os.getenv("api_key")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5.4-mini").strip() or "gpt-5.4-mini"
OPENAI_REASONING_EFFORT = os.getenv("OPENAI_REASONING_EFFORT", "low").strip().lower() or "low"

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
) -> tuple[str, dict, dict, str, str, dict]:
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

    prompt = f"""
Ты — инвестиционный аналитик, который пишет короткую и строгую записку по отчётности.
Твоя задача — не пересказывать данные, а объяснить экономический смысл для инвестора.

Язык ответа: {LANGUAGE_HINTS[lang]['label']}

Жёсткие правила:
- Используй только данные из отчётности, расчётных метрик и IFRS snapshot ниже.
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
Назови 2-4 фактора, которые реально могут сдвинуть оценку.

[СИЛЬНЫЕ_СТОРОНЫ]
Только сильные стороны с числами и кратким смыслом.

[СЛАБЫЕ_СТОРОНЫ]
Только слабые стороны с числами и кратким смыслом.

[ПРОГНОЗ]
Сценарий на 12 месяцев: что должно случиться, чтобы оценка улучшилась или ухудшилась.

[ВЕРДИКТ]
Выбери один вариант: ПОКУПАТЬ / ДЕРЖАТЬ / НАБЛЮДАТЬ / ОСТОРОЖНО / ВОЗДЕРЖАТЬСЯ.
Кратко объясни почему.

[СОВЕТЫ]
Дай короткие практические советы по размеру позиции и ожиданиям по риску.

[ИТОГ]
4-6 предложений простым и профессиональным языком.
Без воды. Без терминов без объяснения.
""".strip()

    return (
        f"Язык ответа: {LANGUAGE_HINTS[lang]['label']}.\n\n{ANALYSIS_STYLE_NOTE}\n\n{prompt}",
        metrics,
        ind_compare,
        annual_period,
        quarterly_period,
        ifrs_snapshot,
    )


def run_analysis(company_name: str, company_profile: str, annual_data: list,
                 quarterly_data: list, liquidity_data: dict | None = None,
                 language: str | None = "ru") -> tuple:
    lang = _normalize_language(language)
    prompt, metrics, ind_compare, annual_period, quarterly_period, ifrs_snapshot = _analysis_prompt_v2(
        company_name,
        company_profile,
        annual_data,
        quarterly_data,
        liquidity_data,
        lang,
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

    return raw, annual_period, quarterly_period, cost, metrics, ifrs_snapshot


async def run_company_analysis(company_name: str, force_refresh: bool = False, language: str = "ru") -> dict:
    company_name = (company_name or "").strip()
    if not company_name:
        raise ValueError("company_name cannot be empty")
    language = _normalize_language(language)

    if not force_refresh:
        cached = analysis_cache.get(company_name, language=language)
        if cached:
            cached["from_cache"] = True
            cached["source"] = "cache"
            cached.setdefault("model", OPENAI_MODEL)
            cached.setdefault("language", language)
            cached.setdefault("language_label", LANGUAGE_HINTS[language]["label"])
            cached.setdefault("ifrs_snapshot", {})
            return cached

    loop = asyncio.get_running_loop()
    annual_df, quarter_df, liquidity_df, fetched_name = await loop.run_in_executor(
        None, partial(get_data, company_name)
    )
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
    raw_analysis, annual_period, quarterly_period, cost, metrics, ifrs_snapshot = await loop.run_in_executor(
        None, partial(run_analysis, resolved_name, company_profile, annual_data, quarterly_data, liquidity_data, language)
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
        "html_report": html_report,
        "raw_analysis": raw_analysis,
        "sections": parse_response(raw_analysis),
        "annual_period": annual_period,
        "quarterly_period": quarterly_period,
        "cost": cost,
        "metrics": metrics,
        "ifrs_snapshot": ifrs_snapshot,
        "liquidity": liquidity_data,
        "from_cache": False,
        "source": "fresh",
        "model": OPENAI_MODEL,
        "language": language,
        "language_label": LANGUAGE_HINTS[language]["label"],
    }
    try:
        analysis_cache.set(company_name, result, language=language)
    except Exception as exc:  # noqa: BLE001
        print(f"   ⚠️ Cache write failed for '{resolved_name}': {exc}")
    return result

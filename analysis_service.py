from __future__ import annotations

import asyncio
import json
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


def run_analysis(company_name: str, company_profile: str, annual_data: list,
                 quarterly_data: list, liquidity_data: dict | None = None,
                 language: str | None = "ru") -> tuple:
    lang = _normalize_language(language)
    prompt, metrics, ind_compare, annual_period, quarterly_period = _analysis_prompt(
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

    return raw, annual_period, quarterly_period, cost, metrics


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
    raw_analysis, annual_period, quarterly_period, cost, metrics = await loop.run_in_executor(
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
        "liquidity": liquidity_data,
        "from_cache": False,
        "source": "fresh",
        "model": OPENAI_MODEL,
        "language": language,
        "language_label": LANGUAGE_HINTS[language]["label"],
    }
    analysis_cache.set(company_name, result, language=language)
    return result

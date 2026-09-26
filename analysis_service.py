"""Company analysis workflows: collection, cache lookup, and orchestration.

Public rendering entry points remain available for existing callers; their
implementations live in reporting and do not depend on this service."""

from __future__ import annotations
import asyncio
import json
from financial_analysis.html import build_html
from financial_analysis.metrics import compute_metrics
from financial_analysis.frames import df_to_annual, df_to_quarterly
from financial_analysis.sections import parse_response
from cache import cache as analysis_cache
from concurrent.futures import ThreadPoolExecutor, as_completed
from functools import partial
from main import get_data
from collectors.openinfo.runner import collect_company_data
from reporting.ai import (
    OPENAI_API_KEY,
    OPENAI_REASONING_EFFORT,
    _responses_text,
    api_call_with_retry,
    client,
    logger,
)
from reporting.article.builder import _build_article_report
from reporting.article.signals import _annualization_factor_from_label
from reporting.comparison_metrics import (
    COMPARISON_CATEGORY_METRICS,
    COMPARISON_FIELDS,
    COMPARISON_TABLES,
    _balance_quality_score,
    _best_by,
    _build_category_scores,
    _build_comparison_charts,
    _build_comparison_tables,
    _build_normalized_comparison,
    _comparison_summary,
    _leader_payload,
    _round_metric,
)
from reporting.disclaimer import REPORT_DISCLAIMER, report_disclaimer
from reporting.exports import (
    build_analysis_excel,
    build_analysis_pdf,
    build_comparison_excel,
    build_comparison_pdf,
)
from reporting.localization import LANGUAGE_HINTS, _language_hint, _normalize_language
from reporting.market_context import _compact_market_context
from reporting.numbers import _growth_pct, _latest_item, _safe_float
from reporting.prompts import (
    ANALYSIS_STYLE_NOTE,
    PROFILE_STYLE_NOTE,
    PUBLIC_ANALYSIS_POLICY,
    PUBLIC_ANALYSIS_POLICY_META,
    WEB_RESEARCH_NOTE,
    _analysis_prompt_v2,
    _company_profile_prompt,
)
from reporting.report_tables import _enrich_sections_with_report_tables
from reporting.risk import _compute_observations, _compute_risk_profile
from reporting.settings import (
    ABSOLUTE_EXCEL_REPORT_LIMIT,
    ANALYSIS_POLICY_VERSION,
    ARTICLE_ANALYSIS_ROW_LIMIT,
    ARTICLE_EXCEL_APPENDIX_MAX_COLUMNS,
    ARTICLE_EXCEL_APPENDIX_MAX_ROWS,
    ARTICLE_EXCEL_APPENDIX_MAX_TABLES,
    ARTICLE_REPORT_VERSION,
    DEFAULT_EXCEL_REPORT_LIMIT,
    EXCEL_PROMPT_MAX_REPORTS,
    EXCEL_PROMPT_MAX_ROWS_PER_SHEET,
    EXCEL_PROMPT_MAX_SHEETS_PER_REPORT,
    OPENAI_MODEL,
    REPORT_DOCUMENTS_PROMPT_LIMIT,
    REPORT_TABLES_VERSION,
)


def _normalize_excel_report_limit(value: int | None, include_all: bool = False) -> int:
    default = ABSOLUTE_EXCEL_REPORT_LIMIT if include_all else DEFAULT_EXCEL_REPORT_LIMIT
    raw = default if value is None else value
    try:
        parsed = int(raw)
    except (TypeError, ValueError):
        parsed = default
    return max(0, min(ABSOLUTE_EXCEL_REPORT_LIMIT, parsed))


_REPORT_FORM_MAP = {
    "IFRS": "MSFO",
    "NAS": "NSBU",
    "Audit": "Audition",
}


def _normalize_report_form(report_form: str | None) -> str:
    key = str(report_form or "IFRS").strip()
    return _REPORT_FORM_MAP.get(key, "MSFO")


def _normalize_report_comparison(
    report_analysis_type: str | None = None,
    report_quarter: int | None = None,
    report_current_year: int | None = None,
    report_previous_year: int | None = None,
    report_form: str | None = None,
) -> dict:
    mode = str(report_analysis_type or "latest").strip().lower()
    if mode in {"quarter", "quarterly"}:
        mode = "quarterly"
    elif mode in {"annual", "year", "yearly"}:
        mode = "annual"
    else:
        mode = "latest"

    comparison = {
        "mode": mode,
        "quarter": None,
        "current_year": None,
        "previous_year": None,
        "report_form": _normalize_report_form(report_form),
    }
    if mode == "latest":
        return comparison

    current_year = int(report_current_year or 0)
    previous_year = int(report_previous_year or 0)
    if current_year < 1900 or previous_year < 1900:
        raise ValueError("Для выбранного режима укажите два года для сравнения.")
    if current_year == previous_year:
        raise ValueError("Годы для сравнения должны отличаться.")

    comparison["current_year"] = current_year
    comparison["previous_year"] = previous_year
    if mode == "quarterly":
        quarter = int(report_quarter or 0)
        if quarter not in {1, 2, 3, 4}:
            raise ValueError("Для квартального анализа выберите квартал от 1 до 4.")
        comparison["quarter"] = quarter
    return comparison


def _comparison_cache_suffix(report_comparison: dict | None) -> str:
    comparison = report_comparison or {}
    mode = comparison.get("mode") or "latest"
    form = comparison.get("report_form") or "MSFO"
    form_suffix = f"_{form.lower()}"
    if mode == "quarterly":
        return f"_quarterly_q{comparison.get('quarter')}_{comparison.get('current_year')}_{comparison.get('previous_year')}{form_suffix}"
    if mode == "annual":
        return f"_annual_{comparison.get('current_year')}_{comparison.get('previous_year')}{form_suffix}"
    return form_suffix


def _analysis_cache_mode(
    include_all_excel_reports: bool,
    excel_report_limit: int,
    report_comparison: dict | None = None,
) -> str:
    default_limit = _normalize_excel_report_limit(None, include_all=False)
    if include_all_excel_reports:
        return f"deep_excel_all_{excel_report_limit}{_comparison_cache_suffix(report_comparison)}"
    if excel_report_limit != default_limit:
        return f"excel_limit_{excel_report_limit}{_comparison_cache_suffix(report_comparison)}"
    return f"default{_comparison_cache_suffix(report_comparison)}"


def _serialize_sections_for_report(sections: dict) -> str:
    if not isinstance(sections, dict):
        return ""
    blocks = []
    for key, body in sections.items():
        blocks.append(f"[{key}]\n{str(body or '').strip()}".strip())
    return "\n\n".join(blocks).strip()


def _cap_words(text: str, max_words: int = 200) -> str:
    """Enforce the ТЗ AI-summary word cap; only truncates when clearly exceeded."""
    if not text:
        return text
    words = text.split()
    if len(words) <= max_words:
        return text
    return " ".join(words[:max_words]).rstrip(" ,;:") + "…"


def build_summary(result: dict) -> dict:
    sections = result.get("sections") or {}
    metrics = result.get("metrics") or {}

    score = metrics.get("total_score", {}) if isinstance(metrics, dict) else {}
    verdict = sections.get("ВЕРДИКТ") or sections.get("VERDICT") or ""
    itog = sections.get("ИТОГ") or sections.get("CONCLUSION") or sections.get("ВЫВОД") or ""

    return {
        "verdict": _cap_words(verdict, 200),
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

    # Extract raw financial values for ratio calculations
    revenue = _safe_float(latest.get("revenue")) or 0
    net_income = _safe_float(latest.get("net_income")) or 0
    equity = _safe_float(latest.get("equity")) or 0
    total_assets = _safe_float(latest.get("total_assets")) or 0
    current_assets = _safe_float(latest.get("current_assets")) or 0
    current_liab = _safe_float(latest.get("current_liabilities")) or 0
    long_term_debt = _safe_float(latest.get("long_term_debt")) or 0
    inventory = _safe_float(latest.get("inventory")) or 0
    gross_profit = _safe_float(latest.get("gross_profit")) or 0
    # For banks, use explicit total_liabilities if available
    total_liabilities_raw = _safe_float(latest.get("total_liabilities"))
    total_liabilities = total_liabilities_raw if total_liabilities_raw else (total_assets - equity if total_assets and equity else 0)

    # Get ratios from DataFrame, or calculate from raw values if missing
    debt_ratio = _round_metric(latest.get("debt_ratio"))
    if debt_ratio is None and total_assets > 0 and total_liabilities > 0:
        debt_ratio = _round_metric((total_liabilities / total_assets) * 100)

    current_ratio = _round_metric(latest.get("current_ratio"))
    if current_ratio is None and current_liab > 0 and current_assets > 0:
        current_ratio = _round_metric(current_assets / current_liab)

    quick_ratio = _round_metric(latest.get("quick_ratio"))
    if quick_ratio is None and current_liab > 0 and current_assets > 0:
        quick_ratio = _round_metric((current_assets - inventory) / current_liab)

    debt_to_equity = _round_metric(latest.get("debt_to_equity_ratio"))
    if debt_to_equity is None and equity > 0:
        # For banks, use total_liabilities; for others, use long_term_debt
        debt_for_ratio = total_liabilities if total_liabilities > 0 else long_term_debt
        if debt_for_ratio > 0:
            debt_to_equity = _round_metric(debt_for_ratio / equity)

    # Calculate profitability ratios if not in DataFrame
    net_profit_margin = _round_metric(latest.get("net_profit_margin"))
    if net_profit_margin is None and revenue > 0:
        net_profit_margin = _round_metric((net_income / revenue) * 100)

    gross_profit_margin = _round_metric(latest.get("gross_profit_margin"))
    if gross_profit_margin is None and revenue > 0 and gross_profit > 0:
        gross_profit_margin = _round_metric((gross_profit / revenue) * 100)

    roe = _round_metric(latest.get("return_on_equity"))
    if roe is None and equity > 0 and net_income != 0:
        roe = _round_metric((net_income / equity) * 100)

    roa = _round_metric(latest.get("return_on_assets"))
    if roa is None and total_assets > 0 and net_income != 0:
        roa = _round_metric((net_income / total_assets) * 100)

    risk_flags = []
    if _safe_float(altman.get("score")) is not None and _safe_float(altman.get("score")) < 1.8:
        risk_flags.append("low_altman_z")
    if debt_ratio is not None and debt_ratio > 60:
        risk_flags.append("high_debt_ratio")
    if _safe_float(market_summary.get("avg_daily_trading_value")) in (None, 0):
        risk_flags.append("low_or_missing_market_liquidity")
    if _safe_float(market_summary.get("period_change_percent")) is not None and _safe_float(market_summary.get("period_change_percent")) < -20:
        risk_flags.append("large_price_drawdown")

    # Use previous year values for growth calculations
    prev_revenue = _safe_float(previous.get("revenue"))
    prev_net_income = _safe_float(previous.get("net_income"))

    balance_quality_score = _balance_quality_score(
        debt_ratio, current_ratio, quick_ratio, debt_to_equity
    )

    return {
        "input": query,
        "company_name": resolved_name,
        "ticker": security.get("ticker"),
        "isin_code": security.get("isin_code"),
        "latest_year": latest.get("year"),
        "score": _round_metric(total_score.get("score")),
        "grade": total_score.get("grade"),
        "score_summary": total_score.get("summary"),
        "revenue": _round_metric(revenue) if revenue else None,
        "revenue_growth_pct": _growth_pct(revenue, prev_revenue),
        "net_income": _round_metric(net_income) if net_income else None,
        "net_income_growth_pct": _growth_pct(net_income, prev_net_income),
        "net_profit_margin_pct": net_profit_margin,
        "gross_profit_margin_pct": gross_profit_margin,
        "roe_pct": roe,
        "roa_pct": roa,
        "debt_ratio_pct": debt_ratio,
        "debt_to_equity_ratio": debt_to_equity,
        "current_ratio": current_ratio,
        "quick_ratio": quick_ratio,
        "balance_quality_score": round(balance_quality_score, 2) if balance_quality_score is not None else None,
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
    if not 2 <= len(cleaned) <= 5:
        raise ValueError("Compare requires 2 to 5 unique companies")

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
    # Reduced max_output_tokens from 1200 to 600 for faster response
    profile, response = _responses_text(f"{PROFILE_STYLE_NOTE}\n\n{prompt}", instructions, max_output_tokens=600)

    usage = getattr(response, "usage", None)
    if usage is not None:
        in_tok = getattr(usage, "input_tokens", 0) or 0
        out_tok = getattr(usage, "output_tokens", 0) or 0
        print(f"   ✅ Profile ready (in={in_tok}, out={out_tok})")
    return profile


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
        "Ты старший финансовый аналитик. Строго следуешь формату ответа. "
        "КАЖДАЯ секция начинается с метки в квадратных скобках: [СКОРИНГ], [ДОСЬЕ], [ЧТО_С_ДЕНЬГАМИ] и т. д. "
        "Сразу после метки — блок «Кратко» (каждое поле на отдельной строке):\n"
        "    Кратко\n"
        "    Тон: <позитивный | умеренный | тревожный | критичный | нет_данных>\n"
        "    Скор: XX/100  (ТОЛЬКО в [СКОРИНГ]; в остальных секциях строку пропусти)\n"
        "    Плюсы:\n"
        "    - ...\n"
        "    Минусы:\n"
        "    - ...\n"
        "    Для тебя: ...\n"
        "    (пустая строка)\n"
        "    <полный аналитический текст секции — минимум 3 абзаца>\n\n"
        "В блоке «Кратко» ЗАПРЕЩЕНЫ аббревиатуры (ROE, ROA, NIM, CIR, LDR, CAR, D/E…). "
        "Используй бытовые аналоги: «на каждый сум вложенного капитала — 28 копеек прибыли». "
        "В основном тексте аббревиатуры разрешены — при первом упоминании давай расшифровку в скобках 3–6 слов.\n\n"
        "В [ЧТО_С_ДЕНЬГАМИ] и [ТРЕНД]: после «Кратко» — обязательная Markdown-таблица "
        "(подпись «Таблица 1 — …» на отдельной строке), затем 3–5 аналитических абзацев. "
        "В [ЭФФЕКТИВНОСТЬ]: обязательная сводная таблица коэффициентов "
        "(Показатель | Значение | Ориентир / норма | Оценка), затем разбор по группам. "
        "Таблицы строить только из реальных данных IFRS snapshot / метрик. Цифры не выдумывать.\n\n"
        "Для банков в [ЧТО_С_ДЕНЬГАМИ] обязательно рассчитай и запиши с формулой: "
        "LTD, ликвидные активы 1-й линии / активы, Coverage ratio (текущий и предыдущий период), "
        "нагрузку резервирования. В [ЭФФЕКТИВНОСТЬ] — все 5 групп коэффициентов (ликвидность, "
        "рентабельность, качество активов, достаточность капитала, операционная эффективность). "
        "Квартальные ROA/ROE/NIM аннуализируй с учётом накопленного периода (×4/номер квартала: Q1 ×4, Q2 ×2, Q3 ×4/3; годовой не аннуализируется) и указывай оба значения.\n\n"
        "В [СИЛЬНЫЕ_СТОРОНЫ] и [СЛАБЫЕ_СТОРОНЫ]: минимум 3 пункта каждый, "
        "формат «• Сильная сторона №N — [Что]: [Показатель с числом] — [Значимость 1–2 предл.]».\n\n"
        "В [ИТОГ]: ХЕРО-АБЗАЦ 4–6 предложений (язык 9-классника, без термина без перевода), "
        "финал «стоит ли вкладываться и почему»; затем СИЛЬНЫЕ СТОРОНЫ (≥3) и РИСКИ (≥3) с числами.\n\n"
        "В [ВЕРДИКТ] и [ИТОГ] используй только факты и коэффициенты, уже рассчитанные в анализе. "
        "Каждый вывод строй как «цифра → влияние → итог» и сопоставляй прибыль, ликвидность и капитал между собой. "
        "Запрещено приписывать изменения экономике, рынку, менеджменту, стратегии, регулированию или иной причине, "
        "если такой факт прямо не передан во входных данных. Неподтверждённую причину называй неизвестной. "
        "Не используй шаблонные фразы о следующем отчёте, будущей динамике или необходимости наблюдать.\n\n"
        "Не используй markdown-заголовки (##). Не пропускай секции. "
        "Не повторяй тезис дважды разными словами. "
        "НЕ упоминай Piotroski F-Score, Altman Z-Score, Buffett, Graham. "
        f"{_language_hint(lang, 'analysis')}"
    )
    raw, response = _responses_text(prompt, instructions, max_output_tokens=10000)

    usage = getattr(response, "usage", None)
    input_tokens = getattr(usage, "input_tokens", 0) or 0
    output_tokens = getattr(usage, "output_tokens", 0) or 0
    cost = (input_tokens / 1_000_000 * 0.25) + (output_tokens / 1_000_000 * 2.0)
    print(f"   ✅ in={input_tokens} out={output_tokens} | ~${cost:.4f}")

    return raw, annual_period, quarterly_period, cost, metrics, ifrs_snapshot, market_context


def _sector_nsbu_result(
    company_input: str,
    resolved_name: str,
    company_data: dict | None,
    language: str,
    cache_mode: str,
    excel_report_mode: dict,
    report_comparison: dict,
) -> dict:
    """Adapt the verified sector report to the legacy ``/api/analyze`` shape.

    The previous path asked the language model to calculate ratios and forced a
    universal fourteen-section investment template.  This adapter keeps the
    public API stable while making the sector-selected, NSBU-first facts the
    only source of narrative and risk statements.
    """
    from issuer_financials import resolve_issuer
    from sector_report_service import public_report, sector_report

    security = (company_data or {}).get("security") or {}
    identifier = security.get("ticker") or company_input or resolved_name
    issuer = resolve_issuer(str(identifier))

    requested_period = None
    current_year = report_comparison.get("current_year")
    quarter = report_comparison.get("quarter")
    if current_year:
        requested_period = f"{current_year}Q{quarter}" if quarter else str(current_year)
    report = public_report(sector_report(issuer, "nsbu", requested_period, "separate", language))
    paragraphs = list(report.get("paragraphs") or [])
    risks = list(report.get("risks") or [])
    data_quality = list(report.get("data_quality") or [])

    money = "\n\n".join(paragraphs[1:4] or paragraphs)
    risk_text = "\n".join(
        f"• {item.get('title')}: {item.get('actual_value')} {item.get('unit') or ''}".rstrip()
        for item in risks
    )
    if not risk_text:
        risk_text = (
            "Материальные риски не публикуются без показателя, порога и источника."
            if language == "ru" else
            "Ko‘rsatkich, mezon va manbasiz muhim xavf e’lon qilinmaydi."
            if language == "uz" else
            "No material risk is published without a metric, threshold and source."
        )
    limitation_text = "\n".join(
        f"• {item.get('message')}" for item in data_quality
    ) or (
        "Дополнительные отраслевые факты показаны только при отдельном официальном раскрытии."
        if language == "ru" else
        "Qo‘shimcha tarmoq faktlari faqat alohida rasmiy oshkor etilganda ko‘rsatiladi."
        if language == "uz" else
        "Supplemental sector facts are shown only when separately disclosed by an official source."
    )
    sections = {
        "ВЕРДИКТ": report.get("headline") or "",
        "ЧТО_С_ДЕНЬГАМИ": money,
        "СЛАБЫЕ_СТОРОНЫ": risk_text,
        "ОГРАНИЧЕНИЯ_ПУБЛИЧНОГО_КОНТУРА": limitation_text,
        "ИТОГ": "\n\n".join([report.get("headline") or "", paragraphs[-1] if paragraphs else ""]).strip(),
    }
    raw_analysis = _serialize_sections_for_report(sections)
    facts = report.get("verified_facts") or []
    # Do not return the old unverified financial/source dump alongside the new
    # verified contract. Only trading and instrument context belong here.
    trading_data = {key: (company_data or {}).get(key) for key in ("ok", "company", "security", "market", "dividends")}
    trading_context = _compact_market_context(trading_data)
    metrics = {
        "sector_template_code": report.get("sector_template_code"),
        "template_version": report.get("template_version"),
        "verified_facts": facts,
        "ratios": report.get("ratios") or [],
        "total_score": {},
    }
    result = {
        "company_input": company_input,
        "company_name": resolved_name,
        "ticker": issuer.get("ticker"),
        "analysis_contract": "sector_nsbu",
        "analysis_status": report.get("status"),
        "sector_template_code": report.get("sector_template_code"),
        "template_version": report.get("template_version"),
        "html_report": None,
        "raw_analysis": raw_analysis,
        "sections": sections,
        "report_tables": {},
        "report_tables_version": REPORT_TABLES_VERSION,
        "article_report": None,
        "article_report_version": ARTICLE_REPORT_VERSION,
        "annual_period": report.get("period") if "Q" not in str(report.get("period") or "") else "",
        "quarterly_period": report.get("period") if "Q" in str(report.get("period") or "") else "",
        "cost": 0.0,
        "metrics": metrics,
        "ifrs_snapshot": {},
        "risk_profile": {"items": risks, "method": "sector_rules"},
        "observations": data_quality,
        "liquidity": None,
        "market_data": trading_data,
        "market_context": trading_context,
        "excel_report_mode": excel_report_mode,
        "report_comparison": report_comparison,
        "cache_mode": cache_mode,
        "from_cache": False,
        "source": "fresh",
        "model": "deterministic-sector-rules",
        "language": language,
        "language_label": LANGUAGE_HINTS[language]["label"],
        "analysis_policy_version": ANALYSIS_POLICY_VERSION,
        "analysis_policy": PUBLIC_ANALYSIS_POLICY_META,
        "verified_facts": facts,
        "sector_report": report,
        "capital_analysis": report.get("capital_analysis"),
        "profit_quality": report.get("profit_quality"),
        "replacement_blocks": report.get("replacement_blocks"),
        "analytical_signals": report.get("analytical_signals"),
        "analytical_issues": report.get("analytical_issues"),
        "verdict": report.get("verdict"),
        "data_quality": data_quality,
        "balance_check": report.get("balance_check"),
    }
    try:
        analysis_cache.set(company_input, result, language=language, mode=cache_mode)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to cache sector NSBU analysis for %s: %s", company_input, exc)
    return result


async def run_company_analysis(
    company_name: str,
    force_refresh: bool = False,
    language: str = "ru",
    include_all_excel_reports: bool = False,
    excel_report_limit: int | None = None,
    report_analysis_type: str | None = None,
    report_quarter: int | None = None,
    report_current_year: int | None = None,
    report_previous_year: int | None = None,
    report_form: str | None = None,
) -> dict:
    company_name = (company_name or "").strip()
    if not company_name:
        raise ValueError("company_name cannot be empty")
    language = _normalize_language(language)
    report_comparison = _normalize_report_comparison(
        report_analysis_type,
        report_quarter,
        report_current_year,
        report_previous_year,
        report_form,
    )
    comparison_requires_excel = report_comparison.get("mode") != "latest"
    if comparison_requires_excel:
        include_all_excel_reports = True
    excel_report_limit = _normalize_excel_report_limit(
        ABSOLUTE_EXCEL_REPORT_LIMIT if comparison_requires_excel else excel_report_limit,
        include_all=include_all_excel_reports,
    )
    excel_report_mode = {
        "include_all": include_all_excel_reports,
        "limit": excel_report_limit,
        "report_comparison": report_comparison,
    }
    cache_mode = _analysis_cache_mode(include_all_excel_reports, excel_report_limit, report_comparison)
    # The legacy company-name cache has no source/rule or market-date identity.
    allow_cache = False

    if allow_cache:
        cached = analysis_cache.get(company_name, language=language, mode=cache_mode)
        if cached and cached.get("analysis_policy_version") == ANALYSIS_POLICY_VERSION:
            cached["from_cache"] = True
            cached["source"] = "cache"
            cached["cache_mode"] = cache_mode
            cached.setdefault("model", OPENAI_MODEL)
            cached.setdefault("language", language)
            cached.setdefault("language_label", LANGUAGE_HINTS[language]["label"])
            cached.setdefault("ifrs_snapshot", {})
            cached.setdefault("market_data", {})
            cached.setdefault("market_context", {})
            cached.setdefault("analysis_policy", PUBLIC_ANALYSIS_POLICY_META)
            cached.setdefault("excel_report_mode", excel_report_mode)
            if cached.get("analysis_contract") == "sector_nsbu":
                cached["report_comparison"] = report_comparison
                return cached
            enriched_sections, report_tables = _enrich_sections_with_report_tables(
                cached.get("sections") or {},
                cached.get("metrics") or {},
                cached.get("ifrs_snapshot") or {},
                language,
            )
            cached["sections"] = enriched_sections
            cached["raw_analysis"] = _serialize_sections_for_report(enriched_sections) or cached.get("raw_analysis")
            cached["report_tables"] = report_tables
            cached["report_tables_version"] = REPORT_TABLES_VERSION
            cached["article_report"] = _build_article_report(
                company_name=cached.get("company_name") or company_name,
                ticker=cached.get("ticker"),
                annual_period=cached.get("annual_period") or "",
                quarterly_period=cached.get("quarterly_period") or "",
                sections=enriched_sections,
                metrics=cached.get("metrics") or {},
                ifrs_snapshot=cached.get("ifrs_snapshot") or {},
                company_data=cached.get("market_data") or {},
                language=language,
                report_comparison=report_comparison,
            )
            cached["article_report_version"] = ARTICLE_REPORT_VERSION
            cached["report_comparison"] = report_comparison
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
            include_excel_reports=excel_report_limit > 0,
            include_all_excel_reports=include_all_excel_reports,
            excel_report_limit=excel_report_limit,
            validate_documents=False,
        ),
    )
    annual_df, quarter_df, liquidity_df, fetched_name = await financials_future
    try:
        company_data = await company_data_future
    except Exception as exc:  # noqa: BLE001
        print(f"   Market data collection failed for '{company_name}': {exc}")
        company_data = {"ok": False, "error": str(exc)}

    # The corrective sector specification makes the verified NSBU report the
    # sole regular-analysis path.  It selects the legal organization type before
    # calculating metrics and never asks the LLM to manufacture arithmetic or
    # fill a missing sector template with generic prose.
    resolved_name = fetched_name or company_name
    return _sector_nsbu_result(
        company_input=company_name,
        resolved_name=resolved_name,
        company_data=company_data,
        language=language,
        cache_mode=cache_mode,
        excel_report_mode=excel_report_mode,
        report_comparison=report_comparison,
    )

    # Legacy implementation retained below for historical exports; the regular
    # API path returns above.  It is intentionally unreachable until those
    # exports are migrated to the sector contract.
    if annual_df is None or quarter_df is None:
        raise ValueError(f"Данные не найдены для «{company_name}»")

    # Parallelize data transformations
    annual_future = loop.run_in_executor(None, df_to_annual, annual_df)
    quarterly_future = loop.run_in_executor(None, df_to_quarterly, quarter_df)
    annual_data, quarterly_data = await asyncio.gather(annual_future, quarterly_future)

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
    parsed_sections = parse_response(raw_analysis)
    enriched_sections, report_tables = _enrich_sections_with_report_tables(
        parsed_sections,
        metrics,
        ifrs_snapshot,
        language,
    )
    report_analysis = _serialize_sections_for_report(enriched_sections) or raw_analysis
    article_report = _build_article_report(
        company_name=resolved_name,
        ticker=((company_data.get("security") or {}).get("ticker") if isinstance(company_data, dict) else None),
        annual_period=annual_period,
        quarterly_period=quarterly_period,
        sections=enriched_sections,
        metrics=metrics,
        ifrs_snapshot=ifrs_snapshot,
        company_data=company_data,
        language=language,
        report_comparison=report_comparison,
    )
    web_research = WEB_RESEARCH_NOTE
    html_report = await loop.run_in_executor(
        None,
        partial(
            build_html,
            resolved_name,
            company_profile,
            web_research,
            report_analysis,
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
        "raw_analysis": report_analysis,
        "sections": enriched_sections,
        "report_tables": report_tables,
        "report_tables_version": REPORT_TABLES_VERSION,
        "article_report": article_report,
        "article_report_version": ARTICLE_REPORT_VERSION,
        "annual_period": annual_period,
        "quarterly_period": quarterly_period,
        "cost": cost,
        "metrics": metrics,
        "ifrs_snapshot": ifrs_snapshot,
        "risk_profile": _compute_risk_profile(ifrs_snapshot, metrics, liquidity_data, language),
        "observations": _compute_observations(ifrs_snapshot, metrics, language),
        "liquidity": liquidity_data,
        "market_data": company_data,
        "market_context": market_context,
        "excel_report_mode": excel_report_mode,
        "report_comparison": report_comparison,
        "cache_mode": cache_mode,
        "from_cache": False,
        "source": "fresh",
        "model": OPENAI_MODEL,
        "language": language,
        "language_label": LANGUAGE_HINTS[language]["label"],
        "analysis_policy_version": ANALYSIS_POLICY_VERSION,
        "analysis_policy": PUBLIC_ANALYSIS_POLICY_META,
    }
    try:
        analysis_cache.set(company_name, result, language=language, mode=cache_mode)
    except Exception as exc:  # noqa: BLE001
        print(f"   ⚠️ Cache write failed for '{resolved_name}': {exc}")
    return result

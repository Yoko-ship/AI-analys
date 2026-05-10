from __future__ import annotations

import asyncio
from functools import partial

from analyzer import (
    build_company_profile,
    build_html,
    df_to_annual,
    df_to_quarterly,
    parse_response,
    research_company_online,
    run_analysis,
)
from cache import cache as analysis_cache
from main import get_data


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
    }


async def run_company_analysis(company_name: str, force_refresh: bool = False) -> dict:
    company_name = (company_name or "").strip()
    if not company_name:
        raise ValueError("company_name cannot be empty")

    if not force_refresh:
        cached = analysis_cache.get(company_name)
        if cached:
            cached["from_cache"] = True
            cached["source"] = "cache"
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

    web_research = await loop.run_in_executor(None, research_company_online, resolved_name)
    company_profile = await loop.run_in_executor(
        None,
        partial(build_company_profile, resolved_name, annual_data, quarterly_data, web_research, liquidity_data),
    )
    raw_analysis, annual_period, quarterly_period, cost, metrics = await loop.run_in_executor(
        None,
        partial(run_analysis, resolved_name, company_profile, web_research, annual_data, quarterly_data, liquidity_data),
    )
    html_report = await loop.run_in_executor(
        None,
        partial(build_html, resolved_name, company_profile, web_research, raw_analysis, annual_period, quarterly_period, cost, metrics),
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
    }
    analysis_cache.set(company_name, result)
    return result

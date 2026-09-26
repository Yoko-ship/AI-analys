"""Legacy analysis commands and provider orchestration. Pure rules live in financial_analysis."""
from __future__ import annotations

from db import get_output_path
from dotenv import load_dotenv
from main import get_data
from pathlib import Path
import financial_analysis.benchmarks as financial_analysis_benchmarks
import financial_analysis.frames as financial_analysis_frames
import financial_analysis.html as financial_analysis_html
import financial_analysis.metrics as financial_analysis_metrics
import financial_analysis.prompt_data as financial_analysis_prompt_data
import financial_analysis.prompts as financial_analysis_prompts
import json
import os
import time
from financial_analysis.prompts import ANALYSIS_PROMPT
from financial_analysis.frames import ANNUAL_RATIOS
from financial_analysis.frames import BANK_TITLES
from financial_analysis.benchmarks import DEBT_BURDEN_LEVELS
from financial_analysis.html import HTML_TEMPLATE
from financial_analysis.benchmarks import INDUSTRY_BENCHMARKS
from financial_analysis.benchmarks import INDUSTRY_DEFAULT
from financial_analysis.frames import KEEP_TITLES
from financial_analysis.prompts import PROFILE_PROMPT
from financial_analysis.prompts import UZ_BENCHMARKS
from financial_analysis.prompts import WEB_RESEARCH_PROMPT
from financial_analysis.sections import _ALIAS_MAP
from financial_analysis.frames import _NORMALIZED_FIELD_MAP
from financial_analysis.sections import _SECTION_ALIASES
from financial_analysis.frames import _TITLE_NUMBERING_RE
from financial_analysis.frames import _get_field_mapping
from financial_analysis.frames import _normalize_title
from financial_analysis.html import build_catalysts_html
from financial_analysis.html import build_forecast_html
from financial_analysis.html import build_html
from financial_analysis.html import build_liquidity_html
from financial_analysis.html import build_metrics_html
from financial_analysis.html import build_tips_html
from financial_analysis.html import build_trends_html
from financial_analysis.benchmarks import compare_to_industry
from financial_analysis.metrics import compute_metrics
from financial_analysis.technical import compute_technical_indicators
from financial_analysis.benchmarks import detect_industry
from financial_analysis.frames import df_to_annual
from financial_analysis.frames import df_to_quarterly
from financial_analysis.sections import parse_bullet
from financial_analysis.sections import parse_response
from financial_analysis.frames import slim_for_prompt
from financial_analysis.prompt_data import slim_metrics_for_prompt
from financial_analysis.html import swot_items_html
from financial_analysis.html import verdict_parts


try:
    import anthropic
except ImportError:  # pragma: no cover - dependency is available in production
    anthropic = None


load_dotenv()


API_KEY     = os.getenv("ANTHROPIC_API_KEY") or os.getenv("api_key")


OUTPUT_PATH = get_output_path()


MODEL_CHEAP = "claude-haiku-4-5-20251001"


MODEL_MAIN  = "claude-sonnet-4-6"


if not API_KEY:
    client = None
else:
    client = anthropic.Anthropic(api_key=API_KEY)


def api_call_with_retry(fn, max_retries=6):
    for attempt in range(max_retries):
        try:
            return fn()
        except anthropic.RateLimitError as e:
            if attempt == max_retries - 1:
                raise
            wait = min(120, 15 * (2 ** attempt))
            try:
                resp = getattr(e, "response", None)
                if resp and hasattr(resp, "headers"):
                    ra = resp.headers.get("retry-after")
                    if ra:
                        wait = int(ra) + 2
            except Exception:
                pass
            print(f"   ⏳ Rate limit (попытка {attempt+1}/{max_retries}), жду {wait}с...")
            time.sleep(wait)
        except anthropic.APIStatusError as e:
            if e.status_code in (529, 503) and attempt < max_retries - 1:
                wait = 20 * (attempt + 1)
                print(f"   ⏳ Сервер перегружен, жду {wait}с...")
                time.sleep(wait)
            else:
                raise


WEB_SEARCH_TOOL = {"type": "web_search_20250305", "name": "web_search"}


def research_company_online(company_name: str) -> str:
    messages = [{"role": "user", "content": financial_analysis_prompts.WEB_RESEARCH_PROMPT.format(company=company_name)}]
    print(f"🔍 Ищу «{company_name}» в интернете + новости-катализаторы (Haiku)...")

    for iteration in range(10):
        def _call(msgs=messages):
            return client.messages.create(
                model=MODEL_CHEAP,
                max_tokens=2500,
                temperature=0.1,
                tools=[WEB_SEARCH_TOOL],
                messages=msgs,
            )
        response = api_call_with_retry(_call)

        tool_uses  = [b for b in response.content if b.type == "tool_use"]
        text_parts = [b.text for b in response.content if b.type == "text"]

        if response.stop_reason == "end_turn" or not tool_uses:
            print(f"   ✅ Веб-исследование готово ({iteration+1} итераций)")
            return "\n".join(text_parts).strip()

        messages.append({"role": "assistant", "content": response.content})
        tool_results = []
        for tu in tool_uses:
            print(f"   🌐 {tu.input.get('query', '...')}")
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": tu.id,
                "content": "Результаты поиска получены.",
            })
        messages.append({"role": "user", "content": tool_results})
        time.sleep(0.5)

    print("   ⚠️ Лимит итераций веб-поиска")
    return "Веб-данные не получены."


def build_company_profile(company_name: str, annual_data: list,
                           quarterly_data: list, web_research: str,
                           liquidity_data: dict | None = None) -> str:
    slim = financial_analysis_frames.slim_for_prompt(annual_data, quarterly_data)
    fin_short = {
        "annual": [
            {k: v for k, v in r.items() if k in
             {"year","revenue","net_income","total_assets","equity","net_profit_margin","yoy_growth"}}
            for r in slim["annual"]
        ],
        "latest_q": slim["quarterly"][-1] if slim["quarterly"] else {},
        "liquidity": liquidity_data or {},
    }
    prompt = financial_analysis_prompts.PROFILE_PROMPT.format(
        company=company_name,
        web_research=web_research[:2500],
        financials_json=json.dumps(fin_short, ensure_ascii=False),
    )
    print("📋 Генерирую профиль (Haiku)...")

    def _call():
        return client.messages.create(
            model=MODEL_CHEAP,
            max_tokens=1500,   # увеличено: профиль иногда обрезался
            temperature=0.2,
            messages=[{"role": "user", "content": prompt}],
        )
    msg = api_call_with_retry(_call)
    profile = msg.content[0].text.strip()
    if msg.stop_reason == "max_tokens":
        print("   ⚠️ Профиль обрезан — увеличь max_tokens профиля")
    print(f"   ✅ Профиль готов ({msg.usage.output_tokens} токенов, stop={msg.stop_reason})")
    return profile


def run_analysis(company_name: str, company_profile: str, web_research: str,
                 annual_data: list, quarterly_data: list,
                 liquidity_data: dict | None = None) -> tuple:
    slim = financial_analysis_frames.slim_for_prompt(annual_data, quarterly_data)

    annual_period = (
        f"{slim['annual'][0]['year']}–{slim['annual'][-1]['year']}"
        if slim["annual"] else "нет данных"
    )
    quarterly_period = (
        f"{slim['quarterly'][0]['period']}–{slim['quarterly'][-1]['period']}"
        if slim["quarterly"] else "квартальные данные недоступны"
    )

    # Вычисляем экспертные метрики (бесплатно, чистый Python)
    metrics = financial_analysis_metrics.compute_metrics(annual_data, quarterly_data)
    if liquidity_data:
        metrics["market_liquidity"] = liquidity_data

    # Определяем отрасль и сравниваем с бенчмарками
    industry    = financial_analysis_benchmarks.detect_industry(company_name, web_research, company_profile)
    ind_compare = financial_analysis_benchmarks.compare_to_industry(metrics, industry)
    metrics["industry"] = ind_compare
    # Обновляем WACC в DCF под отраслевой если он уже посчитан
    if "dcf" in metrics and industry.get("wacc"):
        metrics["dcf"]["wacc_used_sector"] = round(industry["wacc"] * 100, 1)

    mom_str = metrics.get('momentum',{}).get('css','?')
    print(f"   📐 Метрики: Piotroski={metrics.get('piotroski_f_score',{}).get('score','?')}/9, "
          f"Altman={metrics.get('altman_z_score',{}).get('score','?')}, "
          f"Momentum={mom_str}, "
          f"Отрасль={ind_compare.get('sector_name','?')}, "
          f"Score={metrics.get('total_score',{}).get('score','?')}/100")

    web_brief = web_research[:1400] + ("..." if len(web_research) > 1400 else "")
    prompt_metrics = financial_analysis_prompt_data.slim_metrics_for_prompt(metrics)

    # Строим отраслевой контекст для промпта
    ind = metrics.get("industry", {})
    industry_context_str = (
        f"Отрасль: {ind.get('sector_name', 'не определена')}\n"
        f"Результат vs бенчмарк: {ind.get('verdict','')}\n"
        f"Хороших показателей: {ind.get('good_count',0)}/5, "
        f"Слабых: {ind.get('weak_count',0)}/5\n"
        f"Примечание: {ind.get('capex_note','')}"
    ) if ind else "Отрасль не определена — используй общие нормы UZ"

    prompt = financial_analysis_prompts.ANALYSIS_PROMPT.format(
        uz_benchmarks=financial_analysis_prompts.UZ_BENCHMARKS.format(industry_context=industry_context_str),
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

    approx_tokens = len(prompt) // 4
    print(f"📤 Анализ (Sonnet) — ~{approx_tokens} токенов входа...")

    def _call():
        return client.messages.create(
            model=MODEL_MAIN,
            max_tokens=12000,
            temperature=0.2,
            system=(
                "Ты строго следуешь формату ответа. "
                "КАЖДАЯ секция ОБЯЗАТЕЛЬНО начинается с метки в квадратных скобках: "
                "[ОБЩИЕ_СВЕДЕНИЯ], [ГОРИЗОНТАЛЬНЫЙ_АНАЛИЗ], [ВЕРТИКАЛЬНЫЙ_АНАЛИЗ], "
                "[АНАЛИЗ_ФИНРЕЗУЛЬТАТОВ], [КОЭФФИЦИЕНТНЫЙ_АНАЛИЗ], [СВОДНАЯ_ТАБЛИЦА], [ЗАКЛЮЧЕНИЕ], "
                "[СКОРИНГ], [ДОСЬЕ], [ЧТО_С_ДЕНЬГАМИ], [ТРЕНД], [ОЦЕНКА_СТОИМОСТИ], "
                "[ФИБОНАЧЧИ], [КАТАЛИЗАТОРЫ], [СИЛЬНЫЕ_СТОРОНЫ], [СЛАБЫЕ_СТОРОНЫ], "
                "[ПРОГНОЗ], [ВЕРДИКТ], [СОВЕТЫ], [ИТОГ]. "
                "ПОРЯДОК СТРОГО ТАКОЙ, КАК В ШАБЛОНЕ — сначала 7 основных разделов, затем вспомогательные. "
                "НЕ используй markdown заголовки (##). "
                "НЕ пропускай ни одну секцию. "
                "Если данных недостаточно — напиши 'Недостаточно данных' внутри секции, но секцию не пропускай. "
                "Все числа давай в формате «X XXX XXX» с пробелами в качестве разделителей разрядов."
            ),
            messages=[{"role": "user", "content": prompt}],
        )
    msg = api_call_with_retry(_call)
    raw = msg.content[0].text.strip()

    # Проверяем не обрезан ли ответ
    if msg.stop_reason == "max_tokens":
        print("   ⚠️  ВНИМАНИЕ: ответ обрезан по max_tokens! Некоторые секции могут быть пустыми.")
        # Дописываем минимальное заключение/вердикт если их нет
        if "[ЗАКЛЮЧЕНИЕ]" not in raw:
            raw += (
                "\n\n[ЗАКЛЮЧЕНИЕ]\n"
                "Итоговая оценка финансового состояния не может быть сформирована: "
                "анализ был прерван из-за ограничения по токенам.\n\n"
                "ИНВЕСТИЦИОННАЯ РЕКОМЕНДАЦИЯ:\n"
                "🟡 НАБЛЮДАТЬ — данные неполные, требуется дополнительный анализ.\n"
            )
        if "[ВЕРДИКТ]" not in raw:
            raw += (
                "\n\n[ВЕРДИКТ]\n"
                "МЕТКА: 🟡 НАБЛЮДАТЬ\n"
                "Обоснование: Анализ был прерван из-за ограничения токенов. "
                "Доступные данные не позволяют дать полный вердикт.\n\n"
                "[ИТОГ]\nАнализ был прерван из-за технического ограничения. "
                "Смотри профиль компании и метрики выше для оценки."
            )

    cost = (msg.usage.input_tokens / 1_000_000 * 3.0 +
            msg.usage.output_tokens / 1_000_000 * 15.0)
    print(f"   ✅ in={msg.usage.input_tokens} out={msg.usage.output_tokens} | stop={msg.stop_reason} | ~${cost:.4f}")

    return raw, annual_period, quarterly_period, cost, metrics


if __name__ == "__main__":
    total_cost = 0.0

    print("🌐 Собираю данные с сайта...")
    annual_df, quarter_df, liquidity_df, company_name = get_data()

    if annual_df is None or quarter_df is None:
        raise RuntimeError("❌ Не удалось получить данные.")

    print("🔧 Обрабатываю финансовые данные...")
    annual_data    = financial_analysis_frames.df_to_annual(annual_df)
    quarterly_data = financial_analysis_frames.df_to_quarterly(quarter_df)
    liquidity_data = (
        liquidity_df.iloc[0].to_dict()
        if liquidity_df is not None and not liquidity_df.empty
        else None
    )

    web_research = research_company_online(company_name)
    company_profile = build_company_profile(
        company_name, annual_data, quarterly_data, web_research, liquidity_data
    )

    raw_analysis, annual_period, quarterly_period, analysis_cost, metrics = run_analysis(
        company_name, company_profile, web_research, annual_data, quarterly_data, liquidity_data
    )
    total_cost += analysis_cost

    html_report = financial_analysis_html.build_html(
        company_name, company_profile, web_research,
        raw_analysis, annual_period, quarterly_period,
        cost=total_cost, metrics=metrics,
    )

    output_path = Path(OUTPUT_PATH)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        f.write(html_report)

    print(f"\n✅ Отчёт сохранён: {output_path}")
    print(f"💰 Стоимость: ~${total_cost:.3f}")

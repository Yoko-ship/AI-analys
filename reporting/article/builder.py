"""Build a complete article from supplied data without I/O or AI calls."""

from __future__ import annotations
from reporting.article.indicators import (
    _article_conclusion_blocks,
    _article_ratio_section_blocks,
    _key_indicators_article_table,
)
from reporting.article.narrative import _table_with_explanation
from reporting.article.periods import _select_article_comparison_indices
from reporting.article.ratios import _ratio_article_table
from reporting.article.rows import (
    _article_apply_preferred_value_cell,
    _article_row_kind,
    _article_rows_for_report,
    _bank_ratios_from_excel,
    _excel_rows_for_article,
)
from reporting.article.signals import (
    _article_comparison_phrase,
    _article_period_label_from_table,
    _article_period_phrase,
    _article_period_title,
)
from reporting.article.tables import (
    _excel_appendix_article_tables,
    _horizontal_article_table,
    _income_article_table,
    _multi_period_article_trend_table,
    _vertical_article_table,
)
from reporting.localization import _normalize_language
from reporting.numbers import _safe_float
from reporting.settings import ARTICLE_REPORT_VERSION


def _strip_tldr_for_article(text: str) -> str:
    lines = str(text or "").splitlines()
    if not lines:
        return ""
    first_index = next((idx for idx, line in enumerate(lines) if line.strip()), None)
    if first_index is None:
        return ""
    first = lines[first_index].strip().lower()
    if first not in {"кратко", "brief", "qisqacha", "tl;dr", "tldr"}:
        return str(text or "").strip()
    cursor = first_index + 1
    while cursor < len(lines):
        lowered = lines[cursor].strip().lower()
        cursor += 1
        if lowered.startswith(("для тебя:", "for you:", "siz uchun:")):
            while cursor < len(lines) and not lines[cursor].strip():
                cursor += 1
            break
    return "\n".join(lines[cursor:]).strip()


def _first_article_paragraph(sections: dict, *keys: str) -> str:
    for key in keys:
        text = _strip_tldr_for_article((sections or {}).get(key, ""))
        blocks = [block.strip() for block in text.split("\n\n") if block.strip()]
        if blocks:
            return " ".join(line.strip() for line in blocks[0].splitlines() if line.strip())
    return ""


def _table_count_from_article(sections: list[dict]) -> int:
    return sum(
        1
        for section in sections
        for block in section.get("blocks", [])
        if block.get("type") == "table"
    )


def _build_article_report(
    *,
    company_name: str,
    ticker: str | None,
    annual_period: str,
    quarterly_period: str,
    sections: dict,
    metrics: dict,
    ifrs_snapshot: dict,
    company_data: dict | None,
    language: str,
    report_comparison: dict | None = None,
) -> dict:
    lang = _normalize_language(language)
    comparison = report_comparison or {}
    report_form_filter = comparison.get("report_form") or None
    excel_rows = _excel_rows_for_article(company_data, report_form_filter)
    for row in excel_rows:
        row["article_kind"] = _article_row_kind(row)

    comparison_selection = _select_article_comparison_indices(excel_rows, report_comparison, lang)
    forced_current_index = comparison_selection.get("current_index")
    forced_previous_index = comparison_selection.get("previous_index")
    force_previous_row = bool(comparison_selection.get("force_previous_row"))
    selected_indices = {
        int(index)
        for index in (forced_current_index, forced_previous_index)
        if index is not None
    }
    if force_previous_row:
        for index in selected_indices:
            _article_apply_preferred_value_cell(excel_rows, index)
    analysis_excel_rows = [
        row for row in excel_rows if int(row.get("report_index") or 0) in selected_indices
    ] if force_previous_row and selected_indices else excel_rows

    asset_rows = [row for row in analysis_excel_rows if row.get("article_kind") == "assets"]
    liability_rows = [row for row in analysis_excel_rows if row.get("article_kind") == "liabilities_equity"]
    income_rows = [row for row in analysis_excel_rows if row.get("article_kind") == "income_statement"]

    total_assets = ((ifrs_snapshot or {}).get("balance_sheet") or {}).get("total_assets")
    total_liabilities = None
    balance = (ifrs_snapshot or {}).get("balance_sheet") or {}
    if balance.get("total_assets") is not None and balance.get("equity") is not None:
        assets_value = _safe_float(balance.get("total_assets"))
        equity_value = _safe_float(balance.get("equity"))
        if assets_value is not None and equity_value is not None:
            total_liabilities = assets_value - equity_value

    captions = {
        "assets_h": {"ru": "Таблица 1 — Горизонтальный анализ активов", "en": "Table 1 — Horizontal analysis of assets", "uz": "Jadval 1 — Aktivlarning gorizontal tahlili"},
        "liab_h": {"ru": "Таблица 2 — Горизонтальный анализ обязательств и капитала", "en": "Table 2 — Horizontal analysis of liabilities and equity", "uz": "Jadval 2 — Majburiyatlar va kapital gorizontal tahlili"},
        "assets_v": {"ru": "Таблица 3 — Вертикальный анализ активов (% от итога)", "en": "Table 3 — Vertical analysis of assets (% of total)", "uz": "Jadval 3 — Aktivlarning vertikal tahlili"},
        "liab_v": {"ru": "Таблица 4 — Вертикальный анализ пассивов (% от итога)", "en": "Table 4 — Vertical analysis of liabilities/equity", "uz": "Jadval 4 — Passivlarning vertikal tahlili"},
    }

    table_period_args = {
        "forced_current_index": forced_current_index,
        "forced_previous_index": forced_previous_index,
        "force_previous_row": force_previous_row,
    }
    assets_h = _horizontal_article_table("assets_horizontal", captions["assets_h"].get(lang, captions["assets_h"]["ru"]), asset_rows, lang, **table_period_args)
    liab_h = _horizontal_article_table("liabilities_horizontal", captions["liab_h"].get(lang, captions["liab_h"]["ru"]), liability_rows, lang, **table_period_args)
    assets_v = _vertical_article_table("assets_vertical", captions["assets_v"].get(lang, captions["assets_v"]["ru"]), asset_rows, lang, total_hint="итого актив", fallback_total=_safe_float(total_assets), **table_period_args)
    liab_v = _vertical_article_table("liabilities_vertical", captions["liab_v"].get(lang, captions["liab_v"]["ru"]), liability_rows, lang, total_hint="итого обязательств и собственного", fallback_total=_safe_float(total_assets), **table_period_args)
    income_table = _income_article_table(income_rows, lang, **table_period_args)
    # Compute bank-specific ratios that need raw Excel row data
    _bank = (ifrs_snapshot or {}).get("bank") or {}
    _is_bank = bool(_bank.get("is_bank"))
    _bank_extra: dict = {}
    if _is_bank and excel_rows:
        _snap_income = (ifrs_snapshot or {}).get("income_statement") or {}
        _snap_balance = (ifrs_snapshot or {}).get("balance_sheet") or {}
        bank_ratio_rows = _article_rows_for_report(excel_rows, forced_current_index) if force_previous_row else excel_rows
        _bank_extra = _bank_ratios_from_excel(
            bank_ratio_rows or excel_rows,
            total_assets=_safe_float(_snap_balance.get("total_assets")),
            interest_income=_safe_float(_snap_income.get("revenue")),
            interest_expense=_safe_float(_snap_balance.get("interest_expense")),
        )
    ratio_table = _ratio_article_table(metrics or {}, ifrs_snapshot or {}, lang, bank_extra=_bank_extra)
    ratio_blocks = _article_ratio_section_blocks(assets_h, liab_h, income_table, lang)
    trend_table = _multi_period_article_trend_table(excel_rows, lang)
    key_indicators_table = _key_indicators_article_table(assets_h, liab_h, income_table, lang)
    period_phrase = _article_period_phrase(_article_period_label_from_table(assets_h), lang)
    period_suffix = f" {period_phrase}" if period_phrase and lang == "ru" else ""
    appendix_tables = _excel_appendix_article_tables(company_data, lang)

    def p(text: str) -> dict:
        return {"type": "paragraph", "text": text}

    def t(table: dict | None, role: str) -> list[dict]:
        return _table_with_explanation(table, role, lang)

    section_copy = {
        "overview_fallback": {
            "ru": "Анализ построен на публичной отчётности, расчетных метриках и доступных Excel-раскрытиях эмитента.",
            "en": "The analysis is based on public reporting, calculated metrics and available Excel disclosures from the issuer.",
            "uz": "Tahlil emitentning ommaviy hisobotlari, hisoblangan metrikalari va mavjud Excel ma'lumotlariga asoslanadi.",
        },
        "horizontal_fallback": {
            "ru": "Горизонтальный анализ показывает изменение ключевых строк между текущим и предыдущим периодом.",
            "en": "Horizontal analysis shows how key reporting lines changed between the current and previous period.",
            "uz": "Gorizontal tahlil joriy va oldingi davrlar orasida asosiy hisobot satrlari qanday o'zgarganini ko'rsatadi.",
        },
        "vertical_intro": {
            "ru": "Вертикальный анализ показывает, какая часть активов и пассивов приходится на каждую крупную строку отчётности. Это помогает увидеть концентрацию баланса и зависимость от отдельных статей.",
            "en": "Vertical analysis shows what share of assets and liabilities belongs to each major reporting line. It helps reveal balance-sheet concentration and dependence on individual items.",
            "uz": "Vertikal tahlil aktiv va passivlarning qaysi ulushi har bir yirik hisobot satriga to'g'ri kelishini ko'rsatadi. Bu balans konsentratsiyasi va alohida moddalarga bog'liqlikni ko'rishga yordam beradi.",
        },
        "income_fallback": {
            "ru": "Раздел сопоставляет доходы, расходы и прибыльность между периодами.",
            "en": "This section compares income, expenses and profitability between periods.",
            "uz": "Bu bo'lim davrlar bo'yicha daromad, xarajat va rentabellikni solishtiradi.",
        },
        "trend_intro": {
            "ru": "Этот раздел нужен, чтобы не делать вывод по одному кварталу. Он показывает, повторяется ли тенденция в активах, депозитах, кредитах, капитале, прибыли и банковских коэффициентах.",
            "en": "This section prevents conclusions from being based on one quarter only. It shows whether the trend repeats across assets, deposits, loans, capital, profit and banking ratios.",
            "uz": "Bu bo'lim xulosani faqat bitta chorakka asoslamaslik uchun kerak. U aktivlar, depozitlar, kreditlar, kapital, foyda va bank koeffitsiyentlarida trend takrorlanishini ko'rsatadi.",
        },
        "ratio_fallback": {
            "ru": "Коэффициенты дополняют табличный разбор и показывают прибыльность, устойчивость баланса и качество операционной модели.",
            "en": "Ratios complement the table analysis and show profitability, balance-sheet resilience and operating-model quality.",
            "uz": "Koeffitsiyentlar jadval tahlilini to'ldiradi va rentabellik, balans barqarorligi hamda operatsion model sifatini ko'rsatadi.",
        },
        "key_intro": {
            "ru": "Эта таблица собирает главные коэффициенты в один слой: показатель, значение, ориентир и прямое влияние на анализ. Её удобно читать перед финальным выводом, потому что здесь видно, какие сигналы усиливают оценку, а какие требуют осторожности.",
            "en": "This table brings the main ratios into one layer: metric, value, benchmark and direct effect on the analysis. It is useful before the final conclusion because it shows which signals strengthen the assessment and which require caution.",
            "uz": "Bu jadval asosiy koeffitsiyentlarni bitta qatlamga jamlaydi: ko'rsatkich, qiymat, me'yor va tahlilga bevosita ta'sir. Uni yakuniy xulosadan oldin o'qish qulay, chunki qaysi signallar bahoni kuchaytirishi va qaysilari ehtiyotkorlik talab qilishini ko'rsatadi.",
        },
        "conclusion_fallback": {
            "ru": "Итоговая оценка зависит от качества прибыли, структуры баланса и полноты раскрытых данных.",
            "en": "The final assessment depends on profit quality, balance-sheet structure and the completeness of disclosed data.",
            "uz": "Yakuniy baho foyda sifati, balans tuzilmasi va oshkor qilingan ma'lumotlarning to'liqligiga bog'liq.",
        },
    }

    def copy(key: str) -> str:
        return (section_copy.get(key) or {}).get(lang) or (section_copy.get(key) or {}).get("en", "")

    appendix_intro = {
        "ru": "\u0414\u043e\u043f\u043e\u043b\u043d\u0438\u0442\u0435\u043b\u044c\u043d\u044b\u0435 XLSX-\u0441\u0442\u0440\u043e\u043a\u0438 \u043d\u0443\u0436\u043d\u044b, \u0447\u0442\u043e\u0431\u044b \u043d\u0435 \u0442\u0435\u0440\u044f\u0442\u044c \u0434\u0430\u043d\u043d\u044b\u0435, \u043a\u043e\u0442\u043e\u0440\u044b\u0435 \u043d\u0435 \u0432\u043e\u0448\u043b\u0438 \u0432 \u043e\u0441\u043d\u043e\u0432\u043d\u044b\u0435 \u0441\u0432\u043e\u0434\u043d\u044b\u0435 \u0442\u0430\u0431\u043b\u0438\u0446\u044b. \u0418\u0445 \u0441\u0442\u043e\u0438\u0442 \u0441\u043c\u043e\u0442\u0440\u0435\u0442\u044c \u043a\u0430\u043a \u0440\u0430\u0441\u0448\u0438\u0444\u0440\u043e\u0432\u043a\u0443: \u0435\u0441\u043b\u0438 \u0441\u0442\u0440\u043e\u043a\u0430 \u0441\u0443\u0449\u0435\u0441\u0442\u0432\u0435\u043d\u043d\u0430\u044f, \u043e\u043d\u0430 \u043f\u043e\u043c\u043e\u0433\u0430\u0435\u0442 \u043f\u043e\u043d\u044f\u0442\u044c, \u0438\u0437 \u0447\u0435\u0433\u043e \u0441\u043b\u043e\u0436\u0438\u043b\u0438\u0441\u044c \u0440\u0438\u0441\u043a, \u0434\u043e\u0445\u043e\u0434, \u043b\u0438\u043a\u0432\u0438\u0434\u043d\u043e\u0441\u0442\u044c \u0438\u043b\u0438 \u043a\u0430\u043f\u0438\u0442\u0430\u043b.",
        "en": "Additional XLSX rows are included so the report does not lose data that did not fit into the main summary tables. Read them as detail: material lines help explain what drives risk, income, liquidity or capital.",
        "uz": "Qo'shimcha XLSX qatorlari asosiy jadvallarga sig'magan ma'lumot yo'qolmasligi uchun beriladi. Ularni tafsilot sifatida o'qing: muhim qatorlar risk, daromad, likvidlik yoki kapital nimadan shakllanganini ko'rsatadi.",
    }.get(lang, "Additional XLSX rows are included so the report does not lose source data.")
    appendix_blocks = [
        p(appendix_intro),
        *({"type": "table", **table} for table in appendix_tables),
    ] if appendix_tables else []

    article_sections = [
        {
            "id": "overview",
            "number": "01",
            "title": {
                "ru": "Общие сведения об эмитенте и методология анализа",
                "en": "Issuer overview and analysis method",
                "uz": "Emitent haqida umumiy ma'lumot va tahlil usuli",
            }.get(lang),
            "blocks": [
                p(_first_article_paragraph(sections, "ДОСЬЕ") or copy("overview_fallback")),
                *([p(str(comparison_selection.get("description")))] if comparison_selection.get("description") else []),
                *([p(f"Отчётный фокус: {period_phrase}. Сравнение баланса построено по датам {_article_comparison_phrase(assets_h, lang)}, поэтому таблицы показывают не только величины, но и направление изменения за период.")] if period_phrase and lang == "ru" else []),
            ],
        },
        {
            "id": "horizontal_balance",
            "number": "02",
            "title": {
                "ru": _article_period_title("Горизонтальный анализ бухгалтерского баланса", assets_h, lang),
                "en": "Horizontal balance sheet analysis",
                "uz": "Balansning gorizontal tahlili",
            }.get(lang),
            "blocks": [
                p(_first_article_paragraph(sections, "ЧТО_С_ДЕНЬГАМИ") or copy("horizontal_fallback")),
                *t(assets_h, "assets_horizontal"),
                *t(liab_h, "liabilities_horizontal"),
            ],
        },
        {
            "id": "vertical_balance",
            "number": "03",
            "title": {
                "ru": _article_period_title("Вертикальный анализ бухгалтерского баланса", assets_v, lang),
                "en": "Vertical balance sheet analysis",
                "uz": "Balansning vertikal tahlili",
            }.get(lang),
            "blocks": [
                p(copy("vertical_intro")),
                *t(assets_v, "assets_vertical"),
                *t(liab_v, "liabilities_vertical"),
            ],
        },
        {
            "id": "income_statement",
            "number": "04",
            "title": {
                "ru": f"Анализ отчёта о финансовых результатах{period_suffix}",
                "en": "Income statement analysis",
                "uz": "Moliyaviy natijalar hisoboti tahlili",
            }.get(lang),
            "blocks": [
                p(_first_article_paragraph(sections, "ТРЕНД", "ЧТО_С_ДЕНЬГАМИ") or copy("income_fallback")),
                *t(income_table, "income_statement"),
            ],
        },
        *([{
            "id": "multi_period_trend",
            "number": "05",
            "title": {
                "ru": "Многоквартальное сравнение ключевых показателей",
                "en": "Multi-period key indicator comparison",
                "uz": "Asosiy ko'rsatkichlarning ko'p davrli taqqoslanishi",
            }.get(lang),
            "blocks": [
                p(copy("trend_intro")),
                *t(trend_table, "multi_period_trend"),
            ],
        }] if trend_table else []),
        {
            "id": "ratio_analysis",
            "number": "06" if trend_table else "05",
            "title": {
                "ru": "Коэффициентный анализ",
                "en": "Ratio analysis",
                "uz": "Koeffitsiyentlar tahlili",
            }.get(lang),
            "blocks": [
                p(_first_article_paragraph(sections, "ЭФФЕКТИВНОСТЬ", "ОЦЕНКА_ЦЕНЫ") or copy("ratio_fallback")),
                *ratio_blocks,
                *t(ratio_table, "ratio_summary"),
            ],
        },
        {
            "id": "key_indicators",
            "number": "07" if trend_table else "06",
            "title": {
                "ru": "Сводная таблица ключевых показателей",
                "en": "Key indicators summary",
                "uz": "Asosiy ko'rsatkichlar xulosasi",
            }.get(lang),
            "blocks": [
                p(copy("key_intro")),
                *t(key_indicators_table, "key_indicators"),
            ],
        },
        {
            "id": "conclusion",
            "number": "08" if trend_table else "07",
            "title": {
                "ru": f"Итоговая оценка финансового состояния {company_name}{period_suffix}".strip(),
                "en": "Final financial condition assessment",
                "uz": "Moliyaviy holat bo'yicha yakuniy baho",
            }.get(lang),
            "blocks": _article_conclusion_blocks(
                _first_article_paragraph(sections, "ИТОГ", "ВЕРДИКТ") or copy("conclusion_fallback"),
                assets_h,
                liab_h,
                income_table,
                ratio_table,
                lang,
            ),
        },
        *([{
            "id": "excel_appendix",
            "number": "09" if trend_table else "08",
            "title": {
                "ru": "\u0414\u043e\u043f\u043e\u043b\u043d\u0438\u0442\u0435\u043b\u044c\u043d\u044b\u0435 XLSX-\u0441\u0442\u0440\u043e\u043a\u0438",
                "en": "Additional XLSX rows",
                "uz": "Qo'shimcha XLSX qatorlari",
            }.get(lang),
            "blocks": appendix_blocks,
        }] if appendix_blocks else []),
    ]

    article_sections = [
        section for section in article_sections
        if any(block.get("type") != "table" or block.get("rows") for block in section.get("blocks", []))
    ]
    table_count = _table_count_from_article(article_sections)
    return {
        "version": ARTICLE_REPORT_VERSION,
        "source": "openinfo_excel" if excel_rows else "metrics_fallback",
        "meta": {
            "company": company_name,
            "ticker": ticker,
            "annual_period": annual_period,
            "quarterly_period": quarterly_period,
            "analysis_period": period_phrase,
            "analysis_comparison": _article_comparison_phrase(assets_h, lang),
            "report_comparison": comparison_selection,
            "table_count": table_count,
            "excel_row_count": len(excel_rows),
            "excel_source_table_count": len(appendix_tables),
        },
        "abstract": _first_article_paragraph(sections, "ИТОГ", "ВЕРДИКТ", "ДОСЬЕ"),
        "sections": article_sections,
    }

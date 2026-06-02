from __future__ import annotations

import asyncio
import json
import math
import os
import re
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
    compute_technical_indicators,
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
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5.5").strip() or "gpt-5.5"
OPENAI_REASONING_EFFORT = os.getenv("OPENAI_REASONING_EFFORT", "medium").strip().lower() or "medium"
ANALYSIS_POLICY_VERSION = "public-information-v9-deep-analysis-2026-05-31"
REPORT_TABLES_VERSION = "report-tables-v1"
ARTICLE_REPORT_VERSION = "article-report-v8"
ARTICLE_ANALYSIS_ROW_LIMIT = int(os.getenv("OPENINFO_ARTICLE_ANALYSIS_ROW_LIMIT", "40"))
ARTICLE_EXCEL_APPENDIX_MAX_TABLES = int(os.getenv("OPENINFO_ARTICLE_EXCEL_APPENDIX_MAX_TABLES", "12"))
ARTICLE_EXCEL_APPENDIX_MAX_ROWS = int(os.getenv("OPENINFO_ARTICLE_EXCEL_APPENDIX_MAX_ROWS", "30"))
ARTICLE_EXCEL_APPENDIX_MAX_COLUMNS = int(os.getenv("OPENINFO_ARTICLE_EXCEL_APPENDIX_MAX_COLUMNS", "8"))
DEFAULT_EXCEL_REPORT_LIMIT = int(os.getenv("OPENINFO_EXCEL_MAX_REPORTS", "3"))
ABSOLUTE_EXCEL_REPORT_LIMIT = int(os.getenv("OPENINFO_EXCEL_ABSOLUTE_MAX_REPORTS", "100"))
REPORT_DOCUMENTS_PROMPT_LIMIT = int(os.getenv("OPENINFO_REPORT_DOCUMENTS_PROMPT_LIMIT", "100"))
EXCEL_PROMPT_MAX_REPORTS = int(os.getenv("OPENINFO_EXCEL_PROMPT_MAX_REPORTS", "100"))
EXCEL_PROMPT_MAX_SHEETS_PER_REPORT = int(os.getenv("OPENINFO_EXCEL_PROMPT_MAX_SHEETS_PER_REPORT", "3"))
EXCEL_PROMPT_MAX_ROWS_PER_SHEET = int(os.getenv("OPENINFO_EXCEL_PROMPT_MAX_ROWS_PER_SHEET", "8"))

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


def _normalize_excel_report_limit(value: int | None, include_all: bool = False) -> int:
    default = ABSOLUTE_EXCEL_REPORT_LIMIT if include_all else DEFAULT_EXCEL_REPORT_LIMIT
    raw = default if value is None else value
    try:
        parsed = int(raw)
    except (TypeError, ValueError):
        parsed = default
    return max(0, min(ABSOLUTE_EXCEL_REPORT_LIMIT, parsed))


def _analysis_cache_mode(include_all_excel_reports: bool, excel_report_limit: int) -> str:
    default_limit = _normalize_excel_report_limit(None, include_all=False)
    if include_all_excel_reports:
        return f"deep_excel_all_{excel_report_limit}"
    if excel_report_limit != default_limit:
        return f"excel_limit_{excel_report_limit}"
    return "default"


def _as_pct(value, digits: int = 2):
    """Convert ratio→percent, tolerating sources that already deliver percent.

    openinfo /financial_indicators/ is inconsistent: return_on_equity comes as
    27.64 (already %), while net_profit_margin comes as 0.12 (fraction). A
    blind ×100 inflates ROE to 2764. If |value|>1 we assume the source is
    already in percent and pass it through; otherwise we scale.
    """
    parsed = _safe_float(value)
    if parsed is None:
        return None
    if abs(parsed) > 1:
        return round(parsed, digits)
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


def _format_report_number(value, language: str = "ru", digits: int = 0, signed: bool = False) -> str:
    number = _safe_float(value)
    if number is None:
        return "—"
    prefix = "+" if signed and number > 0 else ""
    text = f"{number:,.{digits}f}"
    if digits == 0:
        text = text.split(".")[0]
    text = text.replace(",", " ")
    if language != "en":
        text = text.replace(".", ",")
    return f"{prefix}{text}"


def _format_report_pct(value, language: str = "ru", digits: int = 1, signed: bool = False) -> str:
    number = _safe_float(value)
    if number is None:
        return "—"
    return f"{_format_report_number(number, language=language, digits=digits, signed=signed)}%"


def _markdown_cell(value) -> str:
    text = str(value if value not in (None, "") else "—").strip()
    return text.replace("|", "/").replace("\n", " ") or "—"


def _markdown_table(caption: str, headers: list[str], rows: list[list[str]]) -> str | None:
    if not rows:
        return None
    safe_headers = [_markdown_cell(header) for header in headers]
    safe_rows = [[_markdown_cell(cell) for cell in row] for row in rows]
    align = ["---"] + ["---:" for _ in safe_headers[1:]]
    lines = [
        caption,
        "",
        "| " + " | ".join(safe_headers) + " |",
        "| " + " | ".join(align) + " |",
    ]
    lines.extend("| " + " | ".join(row) + " |" for row in safe_rows)
    return "\n".join(lines)


def _report_table_labels(language: str) -> dict:
    lang = _normalize_language(language)
    if lang == "en":
        return {
            "horizontal_caption": "Table 1 — horizontal analysis of key reporting lines (UZS mln)",
            "trend_caption": "Table 2 — dynamics of revenue, profit and balance sheet (UZS mln)",
            "vertical_caption": "Table 3 — balance sheet structure (% of assets)",
            "line": "Line item",
            "current": "Current period",
            "previous": "Previous period",
            "change": "Change, UZS ths.",
            "change_pct": "Change, %",
            "year": "Year",
            "revenue": "Revenue",
            "net_income": "Net income",
            "assets": "Assets",
            "equity": "Equity",
            "net_margin": "Net margin",
            "amount": "Amount",
            "share": "Share",
        }
    if lang == "uz":
        return {
            "horizontal_caption": "Jadval 1 — asosiy hisobot satrlarining gorizontal tahlili (mln so'm)",
            "trend_caption": "Jadval 2 — tushum, foyda va balans dinamikasi (mln so'm)",
            "vertical_caption": "Jadval 3 — balans tuzilmasi (aktivlarga nisbatan, %)",
            "line": "Satr",
            "current": "Joriy davr",
            "previous": "Oldingi davr",
            "change": "O'zgarish, ming so'm",
            "change_pct": "O'zgarish, %",
            "year": "Yil",
            "revenue": "Tushum",
            "net_income": "Sof foyda",
            "assets": "Aktivlar",
            "equity": "O'z kapitali",
            "net_margin": "Sof marja",
            "amount": "Summa",
            "share": "Ulush",
        }
    return {
        "horizontal_caption": "Таблица 1 — горизонтальный анализ ключевых строк отчётности (млн сум)",
        "trend_caption": "Таблица 2 — динамика выручки, прибыли и баланса (млн сум)",
        "vertical_caption": "Таблица 3 — структура баланса (% от активов)",
        "line": "Статья",
        "current": "Текущий период",
        "previous": "Предыдущий период",
        "change": "Изм., тыс. сум",
        "change_pct": "Изм., %",
        "year": "Год",
        "revenue": "Выручка",
        "net_income": "Чистая прибыль",
        "assets": "Активы",
        "equity": "Капитал",
        "net_margin": "Чистая маржа",
        "amount": "Сумма",
        "share": "Доля",
    }


def _build_horizontal_report_table(metrics: dict, language: str) -> dict | None:
    labels = _report_table_labels(language)
    items = ((metrics or {}).get("horizontal_analysis") or {}).get("items") or {}
    rows = []
    for item in items.values():
        if not isinstance(item, dict):
            continue
        rows.append([
            item.get("label") or "—",
            _format_report_number(item.get("current"), language),
            _format_report_number(item.get("previous"), language),
            _format_report_number(item.get("change"), language, signed=True),
            _format_report_pct(item.get("pct"), language, signed=True),
        ])
    if not rows:
        return None
    headers = [labels["line"], labels["current"], labels["previous"], labels["change"], labels["change_pct"]]
    markdown = _markdown_table(labels["horizontal_caption"], headers, rows[:10])
    return {
        "id": "horizontal_key_lines",
        "caption": labels["horizontal_caption"],
        "headers": headers,
        "rows": rows[:10],
        "markdown": markdown,
        "source": "metrics.horizontal_analysis",
    }


def _build_trend_report_table(ifrs_snapshot: dict, language: str) -> dict | None:
    labels = _report_table_labels(language)
    annual = (((ifrs_snapshot or {}).get("series") or {}).get("annual") or [])[-5:]
    rows = []
    for row in annual:
        if not isinstance(row, dict):
            continue
        rows.append([
            row.get("year") or "—",
            _format_report_number(row.get("revenue"), language),
            _format_report_number(row.get("net_income"), language),
            _format_report_number(row.get("total_assets"), language),
            _format_report_number(row.get("equity"), language),
            _format_report_pct(_as_pct(row.get("net_profit_margin")), language),
        ])
    if len(rows) < 2:
        return None
    headers = [
        labels["year"],
        labels["revenue"],
        labels["net_income"],
        labels["assets"],
        labels["equity"],
        labels["net_margin"],
    ]
    markdown = _markdown_table(labels["trend_caption"], headers, rows)
    return {
        "id": "annual_financial_dynamics",
        "caption": labels["trend_caption"],
        "headers": headers,
        "rows": rows,
        "markdown": markdown,
        "source": "ifrs_snapshot.series.annual",
    }


def _build_vertical_balance_table(metrics: dict, language: str) -> dict | None:
    labels = _report_table_labels(language)
    items = ((((metrics or {}).get("vertical_analysis") or {}).get("balance_sheet") or {}).get("items") or {})
    rows = []
    for item in items.values():
        if not isinstance(item, dict):
            continue
        rows.append([
            item.get("label") or "—",
            _format_report_number(item.get("value"), language),
            _format_report_pct(item.get("pct_of_assets"), language),
        ])
    if not rows:
        return None
    headers = [labels["line"], labels["amount"], labels["share"]]
    markdown = _markdown_table(labels["vertical_caption"], headers, rows[:10])
    return {
        "id": "vertical_balance_structure",
        "caption": labels["vertical_caption"],
        "headers": headers,
        "rows": rows[:10],
        "markdown": markdown,
        "source": "metrics.vertical_analysis.balance_sheet",
    }


def _build_report_tables(metrics: dict, ifrs_snapshot: dict, language: str) -> dict[str, list[dict]]:
    tables: dict[str, list[dict]] = {}
    horizontal = _build_horizontal_report_table(metrics, language)
    vertical = _build_vertical_balance_table(metrics, language)
    trend = _build_trend_report_table(ifrs_snapshot, language)
    if horizontal:
        tables.setdefault("ЧТО_С_ДЕНЬГАМИ", []).append(horizontal)
    if vertical:
        tables.setdefault("ЧТО_С_ДЕНЬГАМИ", []).append(vertical)
    if trend:
        tables.setdefault("ТРЕНД", []).append(trend)
    return tables


def _section_has_markdown_table(text: str) -> bool:
    lines = [line.strip() for line in str(text or "").splitlines()]
    return any(line.startswith("|") and "---" in line for line in lines)


def _insert_after_tldr(text: str, payload: str) -> str:
    lines = str(text or "").splitlines()
    first = lines[0].strip().lower() if lines else ""
    if first not in {"кратко", "brief", "qisqacha", "tl;dr", "tldr"}:
        return f"{payload}\n\n{text}".strip()

    insert_at = None
    for idx, line in enumerate(lines):
        lowered = line.strip().lower()
        if lowered.startswith(("для тебя:", "for you:", "siz uchun:")):
            insert_at = idx + 1
            while insert_at < len(lines) and not lines[insert_at].strip():
                insert_at += 1
            break
    if insert_at is None:
        return f"{payload}\n\n{text}".strip()

    before = "\n".join(lines[:insert_at]).rstrip()
    after = "\n".join(lines[insert_at:]).lstrip()
    if after:
        return f"{before}\n\n{payload}\n\n{after}".strip()
    return f"{before}\n\n{payload}".strip()


def _enrich_sections_with_report_tables(
    sections: dict,
    metrics: dict,
    ifrs_snapshot: dict,
    language: str,
) -> tuple[dict, dict[str, list[dict]]]:
    if not isinstance(sections, dict):
        return sections, {}
    tables = _build_report_tables(metrics or {}, ifrs_snapshot or {}, language)
    if not tables:
        return sections, tables

    enriched = dict(sections)
    for section_key, section_tables in tables.items():
        if section_key not in enriched:
            continue
        current = str(enriched.get(section_key) or "")
        if _section_has_markdown_table(current):
            continue
        markdown_blocks = [table.get("markdown") for table in section_tables if table.get("markdown")]
        if markdown_blocks:
            enriched[section_key] = _insert_after_tldr(current, "\n\n".join(markdown_blocks))
    return enriched, tables


def _serialize_sections_for_report(sections: dict) -> str:
    if not isinstance(sections, dict):
        return ""
    blocks = []
    for key, body in sections.items():
        blocks.append(f"[{key}]\n{str(body or '').strip()}".strip())
    return "\n\n".join(blocks).strip()


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


def _excel_rows_for_article(company_data: dict | None) -> list[dict]:
    if not isinstance(company_data, dict):
        return []
    reports = ((company_data.get("excel_reports") or {}).get("items") or [])
    rows: list[dict] = []
    for report_index, report in enumerate(reports):
        for sheet in report.get("sheets") or []:
            sheet_name = str(sheet.get("sheet") or "")
            statement_section = None
            reporting_date = None
            for row in sorted(sheet.get("table_rows") or [], key=lambda item: int(item.get("row") or 0)):
                label = str(row.get("label") or "").strip()
                if not label:
                    continue
                lowered = label.lower()
                if "дата отчетности" in lowered:
                    for value in row.get("values") or []:
                        match = re.search(r"\d{4}-\d{2}-\d{2}", str(value))
                        if match:
                            reporting_date = match.group(0)
                            break
                if "отчет о финансовых результатах" in lowered or "форма № 2" in lowered:
                    statement_section = "income_statement"
                elif "обязательства и собственный капитал" in lowered or lowered == "обязательства" or lowered == "собственный капитал":
                    statement_section = "liabilities_equity"
                elif lowered == "активы" or lowered.endswith(" активы"):
                    statement_section = "assets"
                elif "бухгалтерский баланс" in lowered or "форма № 1" in lowered:
                    statement_section = None
                rows.append({
                    **row,
                    "label": label,
                    "statement_section": statement_section,
                    "reporting_date": reporting_date,
                    "sheet": sheet_name,
                    "report_index": report_index,
                    "report_id": report.get("report_id"),
                    "published_at": report.get("published_at"),
                    "period_type": report.get("period_type"),
                    "report_form": report.get("report_form"),
                    "title": report.get("title"),
                })
    return rows


def _article_row_kind(row: dict) -> str:
    section = str(row.get("statement_section") or "").strip()
    if section in {"assets", "liabilities_equity", "income_statement"}:
        return section
    raw_kind = str(row.get("kind") or "").strip()
    if raw_kind in {"assets", "liabilities_equity", "income_statement"}:
        return raw_kind
    text = " ".join(
        str(row.get(key) or "").lower()
        for key in ("label", "sheet", "report_form", "title")
    )
    if any(token in text for token in (
        "форма 2", "form2", "финансов", "прибы", "убыт", "доход", "расход",
        "выруч", "себесто", "income", "profit", "loss",
    )):
        return "income_statement"
    if any(token in text for token in (
        "пассив", "обязатель", "капитал", "депозит", "вклад", "заем", "заём",
        "кредитор", "резерв", "устав", "liabil", "equity",
    )):
        return "liabilities_equity"
    if any(token in text for token in (
        "актив", "касс", "цбру", "к получению", "инвести", "кредит", "лизинг",
        "основн", "денеж", "дебитор", "запас", "имуществ", "asset",
    )):
        return "assets"
    return str(row.get("kind") or "financial_row")


def _article_amount_cells(row: dict) -> list[dict]:
    cells = row.get("numeric_cells") or []
    if not cells:
        cells = [
            {"index": index, "value": value}
            for index, value in enumerate(row.get("numeric_values") or [])
        ]
    cleaned = []
    for cell in cells:
        value = _safe_float(cell.get("value") if isinstance(cell, dict) else None)
        if value is None:
            continue
        cleaned.append({"index": int(cell.get("index", len(cleaned))), "value": value})
    return cleaned


def _article_amount_pair(row: dict) -> tuple[float, float] | None:
    cells = _article_amount_cells(row)
    large = [cell for cell in cells if abs(cell["value"]) >= 1000]
    source = large if len(large) >= 2 else cells
    if len(source) < 2:
        return None
    source = sorted(source, key=lambda item: item["index"])
    return source[0]["value"], source[1]["value"]


def _article_current_amount(row: dict) -> float | None:
    pair = _article_amount_pair(row)
    if pair:
        return pair[0]
    cells = _article_amount_cells(row)
    large = [cell for cell in cells if abs(cell["value"]) >= 1000]
    if large:
        return sorted(large, key=lambda item: item["index"])[0]["value"]
    return cells[0]["value"] if cells else None


def _clean_article_label(label: str) -> str:
    text = str(label or "").replace("\n", " ").strip(" -–—|")
    return " ".join(text.split())[:180] or "—"


def _find_excel_amount(
    rows: list[dict],
    *keywords: str,
    kind_filter: str | None = None,
) -> tuple[float | None, float | None]:
    """Return (current, prior) amounts for the first Excel row whose label contains ALL keywords."""
    kws = [kw.lower() for kw in keywords]
    for row in rows:
        label = (row.get("label") or "").lower()
        if kind_filter and str(row.get("article_kind") or "") != kind_filter:
            continue
        if all(kw in label for kw in kws):
            pair = _article_amount_pair(row)
            if pair:
                return pair[0], pair[1]
            cur = _article_current_amount(row)
            return cur, None
    return None, None


def _bank_ratios_from_excel(
    excel_rows: list[dict],
    total_assets: float | None,
    interest_income: float | None,
    interest_expense: float | None,
) -> dict:
    """Compute bank-specific ratios that require raw Excel row data (NSBOU forms 1 & 2)."""
    result: dict = {}
    if not excel_rows:
        return result

    # ── First-line liquidity: (Cash + Due-from-CBU) / Total Assets ────────
    cash_cur, _ = _find_excel_amount(excel_rows, "касс", kind_filter="assets")
    cbu_cur, _ = _find_excel_amount(excel_rows, "цбру", kind_filter="assets")
    if cbu_cur is None:
        cbu_cur, _ = _find_excel_amount(excel_rows, "получен", "цбру")
    if (cash_cur is not None or cbu_cur is not None) and total_assets:
        first_line = ((cash_cur or 0.0) + (cbu_cur or 0.0)) / total_assets * 100
        result["first_line_liquidity_pct"] = round(first_line, 2)

    # ── Coverage ratio: Loan-loss reserve / Gross loans (current & prior) ─
    llr_cur, llr_prior = _find_excel_amount(excel_rows, "резерв", "потер")
    gross_cur, gross_prior = _find_excel_amount(excel_rows, "брутто")
    if gross_cur is None:
        gross_cur, gross_prior = _find_excel_amount(excel_rows, "кредит", "брутто")
    if llr_cur is not None and gross_cur and gross_cur > 0:
        result["coverage_ratio_current_pct"] = round(abs(llr_cur) / gross_cur * 100, 2)
    if llr_prior is not None and gross_prior and gross_prior > 0:
        result["coverage_ratio_prior_pct"] = round(abs(llr_prior) / gross_prior * 100, 2)

    # ── Reserve burden: provision expense / interest income ───────────────
    prov_cur, _ = _find_excel_amount(excel_rows, "резерв", "убыт", kind_filter="income_statement")
    if prov_cur is None:
        prov_cur, _ = _find_excel_amount(excel_rows, "резерв", "кредит", kind_filter="income_statement")
    if prov_cur is not None and interest_income and interest_income > 0:
        result["reserve_burden_pct"] = round(abs(prov_cur) / interest_income * 100, 2)

    # ── Interest income coverage: interest income / interest expense ───────
    if interest_income and interest_expense and interest_expense > 0:
        result["interest_income_coverage"] = round(interest_income / abs(interest_expense), 3)

    # ── Non-interest income share: non-int income / (int + non-int income) ─
    non_int_cur, _ = _find_excel_amount(excel_rows, "беспроцентн", "доход", kind_filter="income_statement")
    if non_int_cur is None:
        non_int_cur, _ = _find_excel_amount(excel_rows, "непроцентн", "доход", kind_filter="income_statement")
    if non_int_cur is not None and interest_income and interest_income > 0:
        total_income = interest_income + abs(non_int_cur)
        if total_income > 0:
            result["non_interest_share_pct"] = round(abs(non_int_cur) / total_income * 100, 2)

    return result


def _table_from_rows(
    table_id: str,
    caption: str,
    headers: list[str],
    rows: list[list[str]],
    *,
    source: str,
) -> dict | None:
    if not rows:
        return None
    markdown = _markdown_table(caption, headers, rows)
    return {
        "id": table_id,
        "caption": caption,
        "headers": headers,
        "rows": rows,
        "markdown": markdown,
        "source": source,
    }


def _article_report_sort_value(rows: list[dict], report_index: int) -> str:
    report_rows = [row for row in rows if row.get("report_index") == report_index]
    for row in report_rows:
        reporting_date = str(row.get("reporting_date") or "")
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", reporting_date):
            return reporting_date
    for row in report_rows:
        label = str(row.get("label") or "").lower()
        if "дата отчетности" in label:
            for value in row.get("values") or []:
                match = re.search(r"\d{4}-\d{2}-\d{2}", str(value))
                if match:
                    return match.group(0)
    for row in report_rows:
        published = str(row.get("published_at") or "")
        match = re.search(r"\d{4}-\d{2}-\d{2}", published)
        if match:
            return match.group(0)
    return ""


def _article_report_period_label(rows: list[dict], report_index: int, fallback: str) -> str:
    value = _article_report_sort_value(rows, report_index)
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value or ""):
        year, month, day = value.split("-")
        return f"{day}.{month}.{year}"
    return fallback


def _article_previous_balance_period_label(current_label: str, fallback: str) -> str:
    match = re.fullmatch(r"(\d{2})\.(\d{2})\.(\d{4})", str(current_label or ""))
    if not match:
        return fallback
    year = int(match.group(3))
    return f"31.12.{year - 1}"


def _article_report_indices(rows: list[dict]) -> list[int]:
    indices = sorted({int(row.get("report_index") or 0) for row in rows})
    return sorted(indices, key=lambda index: _article_report_sort_value(rows, index), reverse=True)


def _article_rows_for_report(rows: list[dict], report_index: int | None) -> list[dict]:
    if report_index is None:
        return []
    return [row for row in rows if int(row.get("report_index") or 0) == int(report_index)]


def _article_line_code(label: str) -> str:
    text = str(label or "").strip().lower()
    match = re.match(r"^(\d+)\s*[\.\)]?", text)
    if match:
        return f"n:{match.group(1)}"
    match = re.match(r"^([a-zа-яё])\s*[\.\)]", text)
    if match:
        return f"l:{match.group(1)}:{_normalize_article_label_key(text)}"
    return _normalize_article_label_key(text)


def _normalize_article_label_key(label: str) -> str:
    text = str(label or "").lower()
    text = re.sub(r"^[\s\d\.\)\-–—]+", "", text)
    text = re.sub(r"^[a-zа-яё]\s*[\.\)]\s*", "", text)
    text = text.replace("ё", "е")
    text = re.sub(r"\b(а|б|в|г|д|е|ж|з|и|к|л)\b", " ", text)
    text = re.sub(r"[^a-zа-я0-9]+", " ", text)
    return " ".join(text.split())


def _article_row_lookup(rows: list[dict]) -> dict[str, dict]:
    lookup: dict[str, dict] = {}
    for row in rows:
        amount = _article_current_amount(row)
        if amount is None:
            continue
        label = str(row.get("label") or "")
        for key in {_article_line_code(label), _normalize_article_label_key(label)}:
            if key and key not in lookup:
                lookup[key] = row
    return lookup


def _article_matching_row(row: dict, lookup: dict[str, dict]) -> dict | None:
    label = str(row.get("label") or "")
    for key in (_article_line_code(label), _normalize_article_label_key(label)):
        if key and key in lookup:
            return lookup[key]
    return None


def _article_current_previous_amounts(row: dict, previous_row: dict | None = None) -> tuple[float | None, float | None]:
    pair = _article_amount_pair(row)
    if pair:
        return pair[0], pair[1]
    current = _article_current_amount(row)
    previous = _article_current_amount(previous_row or {}) if previous_row else None
    return current, previous


def _article_amount_is_zero(value: float | None) -> bool:
    return value is None or abs(value) < 0.5


def _article_is_zero_noise(label: str, current: float | None, previous: float | None = None) -> bool:
    if _is_total_report_label(label):
        return False
    return _article_amount_is_zero(current) and _article_amount_is_zero(previous)


def _article_spec_score(row: dict, spec: dict) -> int | None:
    label = _clean_article_label(row.get("label"))
    lowered = label.lower()
    normalized = _normalize_article_label_key(label)
    code = _article_line_code(label)

    excludes = [str(item).lower() for item in spec.get("exclude") or []]
    if any(item and item in lowered for item in excludes):
        return None

    keywords = [str(item).lower() for item in spec.get("keywords") or []]
    if any(item and item not in lowered for item in keywords):
        return None

    any_groups = spec.get("any_keywords") or []
    for group in any_groups:
        group_keywords = [str(item).lower() for item in group or []]
        if group_keywords and not any(item in lowered for item in group_keywords):
            return None

    line_codes = set(spec.get("line_codes") or [])
    score = 0
    if line_codes:
        if code in line_codes:
            score += 100
        elif spec.get("line_code_required"):
            return None

    exact = str(spec.get("exact") or "").strip().lower()
    if exact and lowered == exact:
        score += 120

    normalized_contains = [str(item).lower() for item in spec.get("normalized_contains") or []]
    if any(item and item not in normalized for item in normalized_contains):
        return None
    score += len(keywords) * 8 + len(any_groups) * 4 + len(normalized_contains) * 5
    if not (keywords or any_groups or normalized_contains or line_codes or exact):
        return None
    if spec.get("prefer_total") and _is_total_report_label(label):
        score += 20
    if spec.get("prefer_clean") and any(token in lowered for token in ("чист", "нетто")):
        score += 12
    if spec.get("prefer_gross") and any(token in lowered for token in ("брутто", "gross")):
        score += 12
    return score


def _article_select_row(rows: list[dict], spec: dict) -> dict | None:
    best: tuple[int, int, dict] | None = None
    for index, row in enumerate(rows):
        current = _article_current_amount(row)
        if current is None:
            continue
        score = _article_spec_score(row, spec)
        if score is None:
            continue
        if not spec.get("keep_zero") and _article_is_zero_noise(str(row.get("label") or ""), current, None):
            score -= 15
        candidate = (score, -index, row)
        if best is None or candidate > best:
            best = candidate
    return best[2] if best else None


def _article_entry_from_spec(
    spec: dict,
    current_rows: list[dict],
    previous_lookup: dict[str, dict],
    used_labels: set[str],
) -> dict | None:
    if spec.get("aggregate"):
        current_total = 0.0
        previous_total = 0.0
        has_current = False
        has_previous = False
        source_labels = []
        for part in spec.get("aggregate") or []:
            row = _article_select_row(current_rows, part)
            if not row:
                continue
            label = _clean_article_label(row.get("label"))
            if label in source_labels:
                continue
            previous_row = _article_matching_row(row, previous_lookup)
            current, previous = _article_current_previous_amounts(row, previous_row)
            if current is not None:
                current_total += current
                has_current = True
            if previous is not None:
                previous_total += previous
                has_previous = True
            source_labels.append(label)
        if not has_current:
            return None
        current = current_total
        previous = previous_total if has_previous else None
    else:
        row = _article_select_row(current_rows, spec)
        if not row:
            return None
        source_label = _clean_article_label(row.get("label"))
        if source_label in used_labels and not spec.get("allow_duplicate"):
            return None
        previous_row = _article_matching_row(row, previous_lookup)
        current, previous = _article_current_previous_amounts(row, previous_row)
        used_labels.add(source_label)

    label = spec.get("label") or _clean_article_label((row or {}).get("label") if not spec.get("aggregate") else "")
    if not spec.get("keep_zero") and _article_is_zero_noise(label, current, previous):
        return None
    return {"label": label, "current": current, "previous": previous, "spec": spec}


def _asset_article_specs() -> list[dict]:
    return [
        {"label": "1. Касса и платёжные документы", "line_codes": ["n:1"], "keywords": ["касс"]},
        {"label": "2. Средства к получению из ЦБРУ", "line_codes": ["n:2"], "keywords": ["цбру"]},
        {"label": "3. Средства к получению из других банков", "line_codes": ["n:3"], "keywords": ["других банков"]},
        {"label": "5. Инвестиции (нетто)", "line_codes": ["n:5"], "keywords": ["инвести"], "exclude": ["резерв"], "prefer_clean": True},
        {"label": "7. Кредиты и лизинг (нетто)", "line_codes": ["n:7"], "keywords": ["кредит"], "exclude": ["брутто", "резерв", "минус"], "prefer_clean": True},
        {"label": "— в т.ч. брутто-кредиты", "keywords": ["брутто", "кредит"], "prefer_gross": True},
        {"label": "— в т.ч. резерв на потери", "keywords": ["резерв", "кредит"], "any_keywords": [["потер", "лизинг"]]},
        {"label": "10. Основные средства (нетто)", "line_codes": ["n:10"], "keywords": ["основные средства"]},
        {"label": "11. Начисленные проценты к получению", "line_codes": ["n:11"], "keywords": ["начисленные проценты"]},
        {"label": "13. Другие активы", "line_codes": ["n:13"], "keywords": ["другие активы"], "exclude": ["приобрет", "резерв"]},
        {"label": "14. ИТОГО АКТИВОВ", "line_codes": ["n:14"], "keywords": ["итого актив"], "keep_zero": True},
    ]


def _liability_article_specs() -> list[dict]:
    deposit_parts = [
        {"line_codes": ["n:15"], "keywords": ["депозит", "востреб"]},
        {"line_codes": ["n:16"], "keywords": ["сберегатель", "депозит"]},
        {"line_codes": ["n:17"], "keywords": ["сроч", "депозит"]},
    ]
    return [
        {"label": "Клиентские депозиты, всего", "aggregate": deposit_parts, "allow_duplicate": True},
        {"label": "15. Депозиты до востребования", "line_codes": ["n:15"], "keywords": ["депозит", "востреб"]},
        {"label": "16. Сберегательные депозиты", "line_codes": ["n:16"], "keywords": ["сберегатель", "депозит"]},
        {"label": "17. Срочные депозиты", "line_codes": ["n:17"], "keywords": ["сроч", "депозит"]},
        {"label": "18. К оплате в ЦБРУ", "line_codes": ["n:18"], "keywords": ["цбру"]},
        {"label": "19. К оплате в другие банки", "line_codes": ["n:19"], "keywords": ["другие банки"]},
        {"label": "20. РЕПО / проданные ценные бумаги", "line_codes": ["n:20"], "keywords": ["выкупом"]},
        {"label": "21. Кредиты и лизинг к оплате", "line_codes": ["n:21"], "keywords": ["кредит", "оплат"]},
        {"label": "22. Субординированный долг", "line_codes": ["n:22"], "keywords": ["субординир"]},
        {"label": "23. Начисленные проценты к оплате", "line_codes": ["n:23"], "keywords": ["начисленные проценты"]},
        {"label": "24. Другие обязательства", "line_codes": ["n:24"], "keywords": ["другие обязательства"]},
        {"label": "25. ИТОГО ОБЯЗАТЕЛЬСТВ", "line_codes": ["n:25"], "keywords": ["итого обязательств"], "keep_zero": True},
        {"label": "26. Уставный капитал", "line_codes": ["n:26"], "keywords": ["уставный капитал"]},
        {"label": "28. Резервный капитал", "line_codes": ["n:28"], "keywords": ["резервный капитал"]},
        {"label": "29. Нераспределённая прибыль", "line_codes": ["n:29"], "keywords": ["нераспредел"]},
        {"label": "30. ИТОГО СОБСТВЕННОГО КАПИТАЛА", "line_codes": ["n:30"], "keywords": ["итого собственного капитала"], "keep_zero": True},
        {"label": "31. ИТОГО ОБЯЗАТЕЛЬСТВ И КАПИТАЛА", "line_codes": ["n:31"], "keywords": ["итого обязательств", "капитал"], "keep_zero": True},
    ]


def _income_article_specs() -> list[dict]:
    return [
        {"label": "Процентные доходы: ЦБРУ", "keywords": ["процентные доходы", "цбру"]},
        {"label": "Процентные доходы: другие банки", "keywords": ["процентные доходы", "других банках"]},
        {"label": "Процентные доходы: торговые ценные бумаги", "keywords": ["процентные доходы", "купли-продажи"]},
        {"label": "Процентные доходы: кредиты и лизинг", "keywords": ["процент", "кредит", "лизингов"]},
        {"label": "Другие процентные доходы", "keywords": ["другие процентные доходы"]},
        {"label": "ИТОГО ПРОЦЕНТНЫХ ДОХОДОВ", "keywords": ["итого процентных доход"], "prefer_total": True, "keep_zero": True},
        {"label": "Процентные расходы по депозитам", "keywords": ["итого процентных расходов по депозитам"], "prefer_total": True},
        {"label": "Процентные расходы по кредитам к оплате", "keywords": ["процентные расходы", "кредитам к оплате"]},
        {"label": "Другие процентные расходы", "keywords": ["другие процентные расходы"]},
        {"label": "ИТОГО ПРОЦЕНТНЫХ РАСХОДОВ", "keywords": ["итого процентных расходов"], "exclude": ["депозитам", "займам"], "prefer_total": True, "keep_zero": True},
        {"label": "Чистые процентные доходы до резервов", "line_codes": ["n:3"], "keywords": ["чистые процентные доходы до"]},
        {"label": "Оценка возможных убытков по кредитам и лизингу", "keywords": ["оценка возможных убытков", "кредитам"]},
        {"label": "Чистые процентные доходы после резервов", "keywords": ["после оценки возможных убытков"]},
        {"label": "Комиссионные доходы", "keywords": ["доходы от комиссий"]},
        {"label": "Прибыль в иностранной валюте", "keywords": ["прибыль в иностранной валюте"]},
        {"label": "Другие беспроцентные доходы", "keywords": ["другие беспроцентные доходы"]},
        {"label": "ИТОГО БЕСПРОЦЕНТНЫХ ДОХОДОВ", "keywords": ["итого беспроцентных доход"], "prefer_total": True, "keep_zero": True},
        {"label": "ИТОГО БЕСПРОЦЕНТНЫХ РАСХОДОВ", "keywords": ["итого беспроцентных расходов"], "prefer_total": True},
        {"label": "Чистый доход до операционных расходов", "line_codes": ["n:6"], "keywords": ["чистый доход до операционных расходов"]},
        {"label": "Операционные расходы: персонал", "keywords": ["заработная плата"]},
        {"label": "Операционные расходы: административные", "keywords": ["административные расходы"]},
        {"label": "Операционные расходы: износ", "keywords": ["расходы на износ"]},
        {"label": "Операционные расходы: страхование и налоги", "keywords": ["страхование", "налоги"]},
        {"label": "ИТОГО ОПЕРАЦИОННЫХ РАСХОДОВ", "keywords": ["итого операционных расходов"], "prefer_total": True},
        {"label": "Чистая прибыль до налога", "line_codes": ["n:9"], "keywords": ["чистая прибыль до уплаты налогов"]},
        {"label": "Налог на прибыль", "keywords": ["оценка налога на прибыль"]},
        {"label": "ЧИСТАЯ ПРИБЫЛЬ", "line_codes": ["n:11"], "keywords": ["чистая прибыль"], "keep_zero": True},
    ]


def _normalized_article_entries(
    table_id: str,
    current_rows: list[dict],
    previous_lookup: dict[str, dict],
) -> list[dict]:
    if not current_rows:
        return []
    if table_id.startswith("assets"):
        specs = _asset_article_specs()
    elif table_id.startswith("liabilities"):
        specs = _liability_article_specs()
    elif table_id == "income_statement_horizontal_vertical":
        specs = _income_article_specs()
    else:
        return []

    entries: list[dict] = []
    used_labels: set[str] = set()
    for spec in specs:
        entry = _article_entry_from_spec(spec, current_rows, previous_lookup, used_labels)
        if entry:
            entries.append(entry)
    return entries


def _horizontal_article_table(
    table_id: str,
    caption: str,
    source_rows: list[dict],
    language: str,
    *,
    limit: int = ARTICLE_ANALYSIS_ROW_LIMIT,
) -> dict | None:
    labels = _report_table_labels(language)
    rows = []
    seen = set()
    report_indices = _article_report_indices(source_rows)
    current_index = report_indices[0] if report_indices else None
    previous_index = report_indices[1] if len(report_indices) > 1 else None
    current_rows = _article_rows_for_report(source_rows, current_index) or source_rows
    previous_lookup = _article_row_lookup(_article_rows_for_report(source_rows, previous_index))
    current_label = _article_report_period_label(source_rows, current_index, labels["current"]) if current_index is not None else labels["current"]
    previous_label = _article_report_period_label(source_rows, previous_index, labels["previous"]) if previous_index is not None else labels["previous"]
    if any(_article_amount_pair(row) for row in current_rows):
        previous_label = _article_previous_balance_period_label(current_label, previous_label)

    normalized_entries = _normalized_article_entries(table_id, current_rows, previous_lookup)
    if normalized_entries:
        row_source = normalized_entries
    else:
        row_source = []
        for row in current_rows:
            label = _clean_article_label(row.get("label"))
            if label in seen:
                continue
            previous_row = _article_matching_row(row, previous_lookup)
            current, previous = _article_current_previous_amounts(row, previous_row)
            if current is None or _article_is_zero_noise(label, current, previous):
                continue
            row_source.append({"label": label, "current": current, "previous": previous})
            seen.add(label)
            if len(row_source) >= limit:
                break

    for entry in row_source:
        label = _clean_article_label(entry.get("label"))
        current = entry.get("current")
        previous = entry.get("previous")
        if current is None:
            continue
        change = current - previous if previous is not None else None
        pct = (change / abs(previous) * 100) if previous not in (None, 0) and change is not None else None
        rows.append([
            label,
            _format_report_number(current, language),
            _format_report_number(previous, language) if previous is not None else "—",
            _format_report_number(change, language, signed=True),
            _format_report_pct(pct, language, signed=True),
        ])
        if len(rows) >= limit:
            break
    return _table_from_rows(
        table_id,
        caption,
        [labels["line"], current_label, previous_label, labels["change"], labels["change_pct"]],
        rows,
        source="openinfo_excel.table_rows",
    )


def _vertical_article_table(
    table_id: str,
    caption: str,
    source_rows: list[dict],
    language: str,
    *,
    total_hint: str,
    fallback_total: float | None = None,
    limit: int = ARTICLE_ANALYSIS_ROW_LIMIT,
) -> dict | None:
    labels = _report_table_labels(language)
    report_indices = _article_report_indices(source_rows)
    current_index = report_indices[0] if report_indices else None
    previous_index = report_indices[1] if len(report_indices) > 1 else None
    current_rows = _article_rows_for_report(source_rows, current_index) or source_rows
    previous_rows = _article_rows_for_report(source_rows, previous_index)
    previous_lookup = _article_row_lookup(previous_rows)
    current_label = _article_report_period_label(source_rows, current_index, labels["current"]) if current_index is not None else labels["current"]
    previous_label = _article_report_period_label(source_rows, previous_index, labels["previous"]) if previous_index is not None else labels["previous"]
    if any(_article_amount_pair(row) for row in current_rows):
        previous_label = _article_previous_balance_period_label(current_label, previous_label)

    total = fallback_total
    previous_total = None
    for row in current_rows:
        label = str(row.get("label") or "").lower()
        if total_hint in label:
            total = _article_current_amount(row)
            previous_row = _article_matching_row(row, previous_lookup)
            _, previous_total = _article_current_previous_amounts(row, previous_row)
            break
    if not total:
        return None

    rows = []
    seen = set()
    display_scale = 1000 if abs(total) >= 10_000_000 else 1
    normalized_entries = _normalized_article_entries(table_id, current_rows, previous_lookup)
    if normalized_entries:
        row_source = normalized_entries
    else:
        row_source = []
        for row in current_rows:
            label = _clean_article_label(row.get("label"))
            if label in seen:
                continue
            previous_row = _article_matching_row(row, previous_lookup)
            current, previous = _article_current_previous_amounts(row, previous_row)
            if current is None or _article_is_zero_noise(label, current, previous):
                continue
            row_source.append({"label": label, "current": current, "previous": previous})
            seen.add(label)
            if len(row_source) >= limit:
                break

    for entry in row_source:
        label = _clean_article_label(entry.get("label"))
        current = entry.get("current")
        previous = entry.get("previous")
        if current is None:
            continue
        share = current / total * 100 if total else None
        previous_share = previous / previous_total * 100 if previous is not None and previous_total else None
        rows.append([
            label,
            _format_report_number(current / display_scale, language),
            _format_report_pct(share, language),
            _format_report_number(previous / display_scale, language) if previous is not None else "—",
            _format_report_pct(previous_share, language) if previous_share is not None else "—",
        ])
        if len(rows) >= limit:
            break
    return _table_from_rows(
        table_id,
        caption,
        [labels["line"], current_label, labels["share"], previous_label, labels["share"]],
        rows,
        source="openinfo_excel.table_rows",
    )


def _income_article_table(
    source_rows: list[dict],
    language: str,
    *,
    limit: int = ARTICLE_ANALYSIS_ROW_LIMIT,
) -> dict | None:
    labels = _report_table_labels(language)
    rows = []
    seen = set()
    report_indices = _article_report_indices(source_rows)
    current_index = report_indices[0] if report_indices else None
    current_rows = _article_rows_for_report(source_rows, current_index) or source_rows

    interest_income_base = None
    non_interest_income_base = None
    operating_expense_base = None
    for row in current_rows:
        label_lower = str(row.get("label") or "").lower()
        amount = _article_current_amount(row)
        if amount is None:
            continue
        if "итого процентных доход" in label_lower or "total interest income" in label_lower:
            interest_income_base = abs(amount)
        if "итого беспроцентных доход" in label_lower or "total non-interest income" in label_lower:
            non_interest_income_base = abs(amount)
        if "итого операционных расход" in label_lower or "total operating expense" in label_lower:
            operating_expense_base = abs(amount)
    total_income_base = (interest_income_base or 0) + (non_interest_income_base or 0)
    if total_income_base <= 0:
        total_income_base = None

    normalized_entries = _normalized_article_entries("income_statement_horizontal_vertical", current_rows, {})
    if normalized_entries:
        row_source = normalized_entries
    else:
        row_source = []
        for row in current_rows:
            label = _clean_article_label(row.get("label"))
            if label in seen:
                continue
            current = _article_current_amount(row)
            if current is None or _article_is_zero_noise(label, current, None):
                continue
            row_source.append({"label": label, "current": current})
            seen.add(label)
            if len(row_source) >= limit:
                break

    for entry in row_source:
        label = _clean_article_label(entry.get("label"))
        current = entry.get("current")
        if current is None:
            continue
        label_lower = label.lower()
        if "отчет о финансовых результатах" in label_lower:
            continue
        pct_interest = (abs(current) / interest_income_base * 100) if interest_income_base else None
        pct_total = None
        if total_income_base and any(token in label_lower for token in ("доход", "прибыль")):
            pct_total = abs(current) / total_income_base * 100
        if operating_expense_base and any(token in label_lower for token in ("заработ", "аренда", "административ", "износ", "страхование", "налог")):
            pct_total = abs(current) / operating_expense_base * 100
        rows.append([
            label,
            _format_report_number(current, language),
            _format_report_pct(pct_interest, language) if pct_interest is not None else "—",
            _format_report_pct(pct_total, language) if pct_total is not None else "—",
        ])
        if len(rows) >= limit:
            break
    return _table_from_rows(
        "income_statement_horizontal_vertical",
        {
            "ru": "Таблица 5 — Отчёт о финансовых результатах",
            "en": "Table 5 — Income statement",
            "uz": "Jadval 5 — Moliyaviy natijalar hisoboti",
        }.get(_normalize_language(language), "Таблица 5 — Отчёт о финансовых результатах"),
        [labels["line"], labels["amount"], "% от проц. дох.", "% от сов. дох."],
        rows,
        source="openinfo_excel.table_rows",
    )


def _ratio_article_table(
    metrics: dict,
    ifrs_snapshot: dict,
    language: str,
    bank_extra: dict | None = None,
) -> dict | None:
    lang = _normalize_language(language)
    headers = {
        "ru": ["Показатель", "Значение", "Ориентир / норма", "Оценка", "Смысл"],
        "en": ["Metric", "Value", "Benchmark", "Assessment", "Meaning"],
        "uz": ["Ko'rsatkich", "Qiymat", "Me'yor", "Baho", "Mazmuni"],
    }.get(lang, ["Показатель", "Значение", "Ориентир / норма", "Оценка", "Смысл"])
    metric_rows: list[list[str]] = []
    bank_extra = bank_extra or {}

    def _assess(value, good_threshold, warn_threshold, *, reverse: bool = False, fmt: str = "pct") -> str:
        """Return assessment label based on value vs thresholds. reverse=True: lower is better."""
        if value is None:
            return "—"
        v = float(value)
        if reverse:
            if v <= good_threshold:
                return "✓ Хорошо"
            if v <= warn_threshold:
                return "~ Умеренно"
            return "⚠ Высокий"
        else:
            if v >= good_threshold:
                return "✓ Хорошо"
            if v >= warn_threshold:
                return "~ Умеренно"
            return "⚠ Слабый"

    def add(
        label: str,
        value,
        meaning: str,
        benchmark: str = "—",
        assessment: str = "—",
        *,
        pct: bool = False,
        ratio_suffix: str = "",
        digits: int = 2,
    ):
        if value is None or value == "":
            return
        if pct:
            formatted = _format_report_pct(value, language, digits=digits)
        elif ratio_suffix:
            formatted = f"{round(float(value), digits)}{ratio_suffix}"
        else:
            formatted = str(value)
        metric_rows.append([label, formatted, benchmark, assessment, meaning])

    quality = (ifrs_snapshot or {}).get("quality") or {}
    balance = (ifrs_snapshot or {}).get("balance_sheet") or {}
    income = (ifrs_snapshot or {}).get("income_statement") or {}
    bank = (ifrs_snapshot or {}).get("bank") or {}
    total_score = (metrics or {}).get("total_score") or {}
    is_bank = bool(bank.get("is_bank"))

    # ── Scoring ────────────────────────────────────────────────────────────
    add(
        "Итоговый скоринг",
        total_score.get("score"),
        total_score.get("summary") or total_score.get("grade") or "Сводная оценка качества отчётности",
        benchmark="≥ 60",
        assessment=_assess(total_score.get("score"), 70, 45),
    )

    # ── Liquidity ──────────────────────────────────────────────────────────
    ldr = bank.get("ldr_pct")
    add(
        "LDR — Кредиты / Депозиты" if is_bank else "Текущая ликвидность",
        ldr if is_bank else balance.get("current_ratio"),
        "Активы банка, размещённые в кредитах, vs. клиентская депозитная база" if is_bank else "Способность покрывать краткосрочные обязательства",
        benchmark="< 100%" if is_bank else "1,5–2,5",
        assessment=_assess(ldr, 100, 120, reverse=True) if is_bank else _assess(balance.get("current_ratio"), 1.5, 1.0),
        pct=is_bank,
    )
    first_line = bank_extra.get("first_line_liquidity_pct")
    add(
        "Ликвид. активы 1-й линии / Активы",
        first_line,
        "Касса + счёт в ЦБ / итого активов — мгновенная ликвидность",
        benchmark="> 5%",
        assessment=_assess(first_line, 8, 4),
        pct=True,
    )
    if not is_bank:
        add("Текущая ликвидность", balance.get("current_ratio"), "Способность покрывать краткосрочные обязательства", benchmark="1,5–2,5")

    # ── Profitability ──────────────────────────────────────────────────────
    roe = quality.get("roe_pct") or (bank.get("roe_pct") if is_bank else None)
    roa = quality.get("roa_pct") or (bank.get("roa_pct") if is_bank else None)
    nim = bank.get("nim_pct")
    add(
        "ROA (аннуализ.)" if is_bank else "ROA",
        roa,
        "Прибыль на активы",
        benchmark="1–2% (норм.)" if is_bank else "> 5%",
        assessment=_assess(roa, 1, 0.5),
        pct=True,
    )
    add(
        "ROE (аннуализ.)" if is_bank else "ROE",
        roe,
        "Доходность собственного капитала",
        benchmark="10–20% (норм.)",
        assessment=_assess(roe, 10, 5),
        pct=True,
    )
    if is_bank and nim is not None:
        add("NIM — Чистая процентная маржа", nim, "Чистый процентный доход / итого активов", benchmark="3–5% (норм.)", assessment=_assess(nim, 3, 1), pct=True)
    add(
        "Чистая маржа прибыли",
        income.get("net_margin_pct"),
        "Сколько прибыли остаётся с дохода",
        benchmark="15–25%",
        assessment=_assess(income.get("net_margin_pct"), 15, 5),
        pct=True,
    )

    # ── Asset quality (bank-specific) ──────────────────────────────────────
    cov_cur = bank_extra.get("coverage_ratio_current_pct")
    cov_prior = bank_extra.get("coverage_ratio_prior_pct")
    res_burden = bank_extra.get("reserve_burden_pct")
    if is_bank:
        add(
            "Резервы / Брутто-кредиты (текущий)",
            cov_cur,
            "Coverage ratio — покрытие кредитных потерь резервами",
            benchmark="< 2%",
            assessment=_assess(cov_cur, 2, 3, reverse=True) if cov_cur is not None else "—",
            pct=True,
        )
        add(
            "Резервы / Брутто-кредиты (предыдущий)",
            cov_prior,
            "Coverage ratio предыдущего периода для сравнения",
            benchmark="< 2%",
            assessment=_assess(cov_prior, 2, 3, reverse=True) if cov_prior is not None else "—",
            pct=True,
        )
        add(
            "Нагрузка резервирования",
            res_burden,
            "Резервы периода / процентные доходы — доля прибыли на покрытие потерь",
            benchmark="< 10%",
            assessment=_assess(res_burden, 10, 15, reverse=True) if res_burden is not None else "—",
            pct=True,
        )

    # ── Capital adequacy ───────────────────────────────────────────────────
    car = bank.get("car_simple_pct")
    if is_bank and car is not None:
        add("Капитал / Активы (CAR упрощ.)", car, "Собственный капитал к активам — приближённая достаточность", benchmark="> 8% (Базель)", assessment=_assess(car, 10, 6), pct=True)
    d_to_e = balance.get("debt_to_equity")
    d_to_a_raw = balance.get("debt_to_assets")
    d_to_a = (d_to_a_raw or 0) * 100 if d_to_a_raw is not None else None
    add(
        "Коэффициент задолженности (D/A)",
        d_to_a,
        "Доля обязательств в активах",
        benchmark="~85% (норм. для банков)" if is_bank else "< 50%",
        assessment="✓ Норма" if (is_bank and d_to_a is not None and 80 <= d_to_a <= 90) else _assess(d_to_a, 50, 70, reverse=True) if not is_bank else "—",
        pct=True,
    )
    add(
        "D/E — Долг / Капитал",
        d_to_e,
        "Финансовый рычаг",
        benchmark="4–8× (банки)" if is_bank else "< 1,5",
        assessment="✓ Норма" if (is_bank and d_to_e is not None and 4 <= d_to_e <= 8) else _assess(d_to_e, 1.5, 2.0, reverse=True) if not is_bank else "—",
    )

    # ── Operational efficiency ─────────────────────────────────────────────
    cir = bank.get("cir_pct")
    int_cov = bank.get("interest_income_coverage") or bank_extra.get("interest_income_coverage")
    non_int_share = bank_extra.get("non_interest_share_pct")
    if is_bank:
        add("CIR — Cost-to-Income", cir, "Операционные расходы / чистый доход", benchmark="40–60%", assessment=_assess(cir, 60, 70, reverse=True) if cir is not None else "—", pct=True)
        add(
            "Покрытие % расходов доходами",
            int_cov,
            "Процентные доходы / процентные расходы",
            benchmark="> 1,2×",
            assessment=_assess(int_cov, 1.5, 1.2) if int_cov is not None else "—",
            ratio_suffix="×",
        )
        add(
            "Доля непроц. доходов",
            non_int_share,
            "Непроцентные доходы / совокупные доходы",
            benchmark="20–40%",
            assessment="✓ Норма" if (non_int_share is not None and 20 <= non_int_share <= 40) else "~ Вне нормы" if non_int_share is not None else "—",
            pct=True,
        )
    else:
        add("Покрытие процентов", quality.get("interest_coverage"), "Запас прибыли для выплаты процентов", benchmark="> 3×")
        add("Долг / капитал", d_to_e, "Во сколько раз долг соотносится с собственным капиталом", benchmark="< 1,5")

    return _table_from_rows(
        "ratio_summary",
        {
            "ru": "Таблица 6 — Сводный коэффициентный профиль",
            "en": "Table 6 — Ratio summary profile",
            "uz": "Jadval 6 — Koeffitsiyentlar profili",
        }.get(lang, "Таблица 6 — Сводный коэффициентный профиль"),
        headers,
        metric_rows,
        source="metrics.ifrs_snapshot",
    )


def _excel_appendix_article_tables(company_data: dict | None, language: str) -> list[dict]:
    if not isinstance(company_data, dict):
        return []

    lang = _normalize_language(language)
    labels = _report_table_labels(lang)
    text = {
        "ru": {
            "table": "Таблица",
            "source": "исходные строки XLSX",
            "row": "Строка",
            "value": "Значение",
            "shown": "Показано строк",
            "of": "из",
        },
        "en": {
            "table": "Table",
            "source": "source XLSX rows",
            "row": "Row",
            "value": "Value",
            "shown": "Rows shown",
            "of": "of",
        },
        "uz": {
            "table": "Jadval",
            "source": "XLSX manba satrlari",
            "row": "Qator",
            "value": "Qiymat",
            "shown": "Ko'rsatilgan qatorlar",
            "of": "dan",
        },
    }.get(lang, {
        "table": "Table",
        "source": "source XLSX rows",
        "row": "Row",
        "value": "Value",
        "shown": "Rows shown",
        "of": "of",
    })

    reports = ((company_data.get("excel_reports") or {}).get("items") or [])
    max_tables = max(0, ARTICLE_EXCEL_APPENDIX_MAX_TABLES)
    max_rows = max(0, ARTICLE_EXCEL_APPENDIX_MAX_ROWS)
    max_columns = max(2, ARTICLE_EXCEL_APPENDIX_MAX_COLUMNS)
    tables: list[dict] = []

    for report_index, report in enumerate(reports):
        report_name = (
            report.get("report_form")
            or report.get("title")
            or report.get("period_type")
            or f"report {report_index + 1}"
        )
        published = report.get("published_at")
        for sheet_index, sheet in enumerate(report.get("sheets") or []):
            source_rows = sheet.get("table_rows") or []
            if not source_rows:
                continue

            rows: list[list[str]] = []
            row_value_counts: list[int] = []
            seen: set[tuple[str, tuple[str, ...]]] = set()

            for row in source_rows:
                label = _clean_article_label(row.get("label"))
                values = [
                    _format_report_number(cell["value"], lang)
                    for cell in _article_amount_cells(row)
                ][:max_columns]
                if not label or not values:
                    continue
                key = (label, tuple(values))
                if key in seen:
                    continue
                seen.add(key)
                row_value_counts.append(len(values))
                rows.append([
                    str(row.get("row") or len(rows) + 1),
                    label,
                    *values,
                ])
                if len(rows) >= max_rows:
                    break

            if not rows:
                continue

            value_count = max(row_value_counts or [1])
            headers = [
                text["row"],
                labels["line"],
                *[f"{text['value']} {index + 1}" for index in range(value_count)],
            ]
            normalized_rows = [
                row + ["—"] * max(0, len(headers) - len(row))
                for row in rows
            ]
            sheet_name = sheet.get("sheet") or f"sheet {sheet_index + 1}"
            period_bits = " / ".join(str(bit) for bit in (published, report_name, sheet_name) if bit)
            caption = f"{text['table']} {7 + len(tables)} - {text['source']}: {period_bits}"
            table = _table_from_rows(
                f"excel_source_{report_index}_{sheet_index}_{len(tables)}",
                caption,
                headers,
                normalized_rows,
                source="openinfo_excel.table_rows",
            )
            if table:
                table["note"] = f"{text['shown']}: {len(normalized_rows)} {text['of']} {len(source_rows)}"
                tables.append(table)
            if len(tables) >= max_tables:
                return tables

    return tables


def _table_count_from_article(sections: list[dict]) -> int:
    return sum(
        1
        for section in sections
        for block in section.get("blocks", [])
        if block.get("type") == "table"
    )


def _number_from_report_text(value: str) -> float | None:
    text = str(value or "").strip()
    if not text or text in {"—", "-"}:
        return None
    sign = -1 if text.startswith(("−", "-")) else 1
    text = text.lstrip("+−-").replace("%", "").replace("\xa0", " ").replace(" ", "")
    if "," in text and "." not in text:
        text = text.replace(",", ".")
    text = "".join(ch for ch in text if ch.isdigit() or ch == ".")
    try:
        return sign * float(text)
    except ValueError:
        return None


def _largest_abs_table_row(table: dict | None, column_index: int) -> tuple[str, str] | None:
    if not table:
        return None
    best: tuple[float, str, str] | None = None
    for row in table.get("rows") or []:
        if len(row) <= column_index:
            continue
        parsed = _number_from_report_text(row[column_index])
        if parsed is None:
            continue
        label = str(row[0] or "").strip()
        value = str(row[column_index] or "").strip()
        if not label or not value:
            continue
        magnitude = abs(parsed)
        if best is None or magnitude > best[0]:
            best = (magnitude, label, value)
    if best is None:
        return None
    return best[1], best[2]


def _is_total_report_label(label: str) -> bool:
    lowered = str(label or "").lower()
    return any(token in lowered for token in ("итого", "total", "jami", "всего"))


def _rank_report_rows(
    table: dict | None,
    column_index: int,
    *,
    reverse: bool = True,
    exclude_total: bool = True,
) -> list[tuple[float, str, str]]:
    if not table:
        return []
    ranked: list[tuple[float, str, str]] = []
    for row in table.get("rows") or []:
        if len(row) <= column_index:
            continue
        label = str(row[0] or "").strip()
        if not label or (exclude_total and _is_total_report_label(label)):
            continue
        parsed = _number_from_report_text(row[column_index])
        if parsed is None:
            continue
        ranked.append((parsed, label, str(row[column_index] or "").strip()))
    return sorted(ranked, key=lambda item: item[0], reverse=reverse)


def _total_report_row(table: dict | None) -> list[str] | None:
    if not table:
        return None
    for row in table.get("rows") or []:
        label = str(row[0] if row else "")
        if _is_total_report_label(label):
            return row
    return None


def _format_change_phrase(row: list[str] | None) -> str:
    if not row or len(row) < 5:
        return ""
    return f"{row[0]}: {row[3]} ({row[4]})"


def _practical_table_explanation_blocks(table: dict | None, role: str, language: str) -> list[dict] | None:
    if not table:
        return []

    lang = _normalize_language(language)
    row_count = len(table.get("rows") or [])
    total_phrase = _format_change_phrase(_total_report_row(table))
    strongest_growth = next((item for item in _rank_report_rows(table, 3, reverse=True) if item[0] > 0), None)
    strongest_decline = next((item for item in _rank_report_rows(table, 3, reverse=False) if item[0] < 0), None)
    biggest_change = _largest_abs_table_row(table, 3)
    largest_share = _largest_abs_table_row(table, 2)
    largest_income_share = _largest_abs_table_row(table, 5)

    def block(text: str) -> dict:
        return {"type": "paragraph", "text": text}

    def movement_text(growth_word: str, decline_word: str) -> str:
        parts = []
        if strongest_decline:
            parts.append(f"{decline_word}: {strongest_decline[1]} ({strongest_decline[2]})")
        if strongest_growth:
            parts.append(f"{growth_word}: {strongest_growth[1]} ({strongest_growth[2]})")
        return "; ".join(parts)

    if role == "assets_horizontal":
        moves_en = movement_text("largest growth", "largest fall")
        moves_uz = movement_text("eng katta o'sish", "eng katta pasayish")
        moves_ru = movement_text("самый сильный рост", "самое сильное снижение")
        if lang == "en":
            headline = f"Use this table to see where the bank moved its money across {row_count} asset lines."
            if total_phrase:
                headline += f" Main movement: {total_phrase}."
            if moves_en:
                headline += f" Key rows: {moves_en}."
            return [
                block(headline),
                block("What to do: if loans grew, check provisions and portfolio quality; if cash/liquid assets fell, check liquidity pressure; if one asset line jumped sharply, treat concentration risk as a separate question in the final analysis."),
            ]
        if lang == "uz":
            headline = f"Bu jadval bank pullari {row_count} ta aktiv satri bo'yicha qayerga ko'chganini ko'rsatadi."
            if total_phrase:
                headline += f" Asosiy harakat: {total_phrase}."
            if moves_uz:
                headline += f" Muhim satrlar: {moves_uz}."
            return [
                block(headline),
                block("Nima qilish kerak: kreditlar o'ssa, rezervlar va portfel sifatini tekshiring; likvid aktivlar kamaygan bo'lsa, likvidlik bosimini ko'ring; bitta aktiv keskin o'ssa, yakuniy tahlilda konsentratsiya riskini alohida baholang."),
            ]
        headline = f"Эта таблица показывает, куда банк перераспределил деньги по {row_count} строкам активов."
        if total_phrase:
            headline += f" Главное движение: {total_phrase}."
        if moves_ru:
            headline += f" Ключевые строки: {moves_ru}."
        return [
            block(headline),
            block("Что делать: если выросли кредиты, проверьте резервы и качество портфеля; если снизились деньги или ликвидные активы, смотрите риск нехватки ликвидности; если резко выросла одна статья, учитывайте риск концентрации в итоговом выводе."),
        ]

    if role == "liabilities_horizontal":
        moves_en = movement_text("largest increase", "largest reduction")
        moves_uz = movement_text("eng katta o'sish", "eng katta kamayish")
        moves_ru = movement_text("самый сильный рост", "самое сильное сокращение")
        if lang == "en":
            headline = f"This table shows where the bank got funding for its assets across {row_count} lines."
            if total_phrase:
                headline += f" Main movement: {total_phrase}."
            if moves_en:
                headline += f" Key funding rows: {moves_en}."
            return [
                block(headline),
                block("What to do: falling deposits or rising borrowings mean liquidity and refinancing risk need extra attention; stronger equity makes the balance safer; a funding mix that changes quickly should make the final tone more cautious."),
            ]
        if lang == "uz":
            headline = f"Bu jadval bank aktivlari {row_count} ta manba bo'yicha qaysi pul bilan moliyalashtirilganini ko'rsatadi."
            if total_phrase:
                headline += f" Asosiy harakat: {total_phrase}."
            if moves_uz:
                headline += f" Muhim funding satrlari: {moves_uz}."
            return [
                block(headline),
                block("Nima qilish kerak: depozitlar kamayishi yoki qarzlar o'sishi likvidlik va qayta moliyalashtirish riskini kuchaytiradi; kapital o'sishi balansni xavfsizroq qiladi; funding tarkibi tez o'zgarsa, yakuniy bahoda ehtiyotkor bo'lish kerak."),
            ]
        headline = f"Эта таблица показывает, за счёт каких денег банк финансирует активы по {row_count} строкам."
        if total_phrase:
            headline += f" Главное движение: {total_phrase}."
        if moves_ru:
            headline += f" Ключевые строки фондирования: {moves_ru}."
        return [
            block(headline),
            block("Что делать: если депозиты падают или заёмные средства растут, отдельно проверьте ликвидность и риск рефинансирования; рост капитала делает баланс устойчивее; резкая смена источников денег должна делать итоговую оценку осторожнее."),
        ]

    if role == "assets_vertical":
        if lang == "en":
            detail = f" Largest weight: {largest_share[0]} ({largest_share[1]})." if largest_share else ""
            return [
                block(f"This table shows what the balance sheet is mostly made of, not just whether it grew.{detail}"),
                block("What to do: focus the analysis on the biggest asset block. Loans mean credit-quality risk, liquid assets mean safety but usually lower yield, securities mean market and interest-rate sensitivity."),
            ]
        if lang == "uz":
            detail = f" Eng katta ulush: {largest_share[0]} ({largest_share[1]})." if largest_share else ""
            return [
                block(f"Bu jadval balans asosan nimadan iboratligini ko'rsatadi, faqat o'sishni emas.{detail}"),
                block("Nima qilish kerak: tahlilni eng katta aktiv blokiga qarating. Kreditlar bo'lsa kredit sifati, likvid aktivlar bo'lsa xavfsizlik va pastroq rentabellik, qimmatli qog'ozlar bo'lsa bozor va foiz riski muhim."),
            ]
        detail = f" Самая большая доля: {largest_share[0]} ({largest_share[1]})." if largest_share else ""
        return [
            block(f"Эта таблица показывает, из чего в основном состоит баланс, а не просто вырос он или нет.{detail}"),
            block("Что делать: главный фокус анализа переносите на крупнейший блок активов. Кредиты означают риск качества портфеля, ликвидные активы дают запас прочности, но обычно ниже доходность, ценные бумаги добавляют рыночный и процентный риск."),
        ]

    if role == "liabilities_vertical":
        if lang == "en":
            detail = f" Largest weight: {largest_share[0]} ({largest_share[1]})." if largest_share else ""
            return [
                block(f"This table shows the bank's funding model: deposits, borrowings or equity.{detail}"),
                block("What to do: a high stable-deposit or equity share supports the score; a high debt/repo share means the conclusion must pay more attention to refinancing terms and liquidity buffers."),
            ]
        if lang == "uz":
            detail = f" Eng katta ulush: {largest_share[0]} ({largest_share[1]})." if largest_share else ""
            return [
                block(f"Bu jadval bankning funding modelini ko'rsatadi: depozitlar, qarzlar yoki kapital.{detail}"),
                block("Nima qilish kerak: barqaror depozit yoki kapital ulushi yuqori bo'lsa baho mustahkamlanadi; qarz/REPO ulushi yuqori bo'lsa, xulosada qayta moliyalashtirish shartlari va likvidlik buferlariga ko'proq e'tibor bering."),
            ]
        detail = f" Самая большая доля: {largest_share[0]} ({largest_share[1]})." if largest_share else ""
        return [
            block(f"Эта таблица показывает модель фондирования банка: депозиты, заёмные средства или собственный капитал.{detail}"),
            block("Что делать: высокая доля устойчивых депозитов или капитала поддерживает оценку; высокая доля долга/РЕПО означает, что в выводе нужно сильнее учитывать сроки рефинансирования и запас ликвидности."),
        ]

    if role == "income_statement":
        if lang == "en":
            detail = f" Largest P&L movement: {biggest_change[0]} ({biggest_change[1]})." if biggest_change else ""
            share = f" Largest current-period weight: {largest_income_share[0]} ({largest_income_share[1]})." if largest_income_share else ""
            return [
                block(f"This table shows where profit is coming from and whether revenue growth is actually turning into profit. {detail}{share}".strip()),
                block("What to do: compare income growth with funding costs, provisions and operating expenses. If costs or provisions rise faster than income, the final analysis should be more cautious even when revenue is growing."),
            ]
        if lang == "uz":
            detail = f" Eng katta foyda-zarar harakati: {biggest_change[0]} ({biggest_change[1]})." if biggest_change else ""
            share = f" Joriy davrdagi eng katta ulush: {largest_income_share[0]} ({largest_income_share[1]})." if largest_income_share else ""
            return [
                block(f"Bu jadval foyda qayerdan kelayotganini va tushum o'sishi haqiqiy foydaga aylanayotganini ko'rsatadi. {detail}{share}".strip()),
                block("Nima qilish kerak: daromad o'sishini funding xarajatlari, rezervlar va operatsion xarajatlar bilan solishtiring. Xarajatlar yoki rezervlar daromaddan tezroq o'ssa, tushum o'ssa ham yakuniy xulosa ehtiyotkor bo'lishi kerak."),
            ]
        detail = f" Самое крупное движение в прибыли/убытке: {biggest_change[0]} ({biggest_change[1]})." if biggest_change else ""
        share = f" Самая большая доля в текущем периоде: {largest_income_share[0]} ({largest_income_share[1]})." if largest_income_share else ""
        return [
            block(f"Эта таблица показывает, откуда берётся прибыль и превращается ли рост доходов в реальный результат. {detail}{share}".strip()),
            block("Что делать: сравните рост доходов со стоимостью фондирования, резервами и операционными расходами. Если расходы или резервы растут быстрее доходов, итоговый вывод должен быть осторожнее даже при росте выручки."),
        ]

    if role == "ratio_summary":
        if lang == "en":
            return [
                block(f"This table turns the statements into {row_count} quick health checks: profitability, leverage, liquidity, funding and efficiency."),
                block("What to do: read weak ratios first and connect them with the tables above. One good ratio is not enough; the final view should improve only when profitability, liquidity and capital quality are consistent at the same time."),
            ]
        if lang == "uz":
            return [
                block(f"Bu jadval hisobotlarni {row_count} ta tezkor sog'liq signaliga aylantiradi: rentabellik, qarz yuki, likvidlik, funding va samaradorlik."),
                block("Nima qilish kerak: avval zaif koeffitsiyentlarni o'qing va ularni yuqoridagi jadvallar bilan bog'lang. Bitta yaxshi ko'rsatkich yetarli emas; yakuniy baho faqat rentabellik, likvidlik va kapital sifati bir vaqtda mos bo'lsa yaxshilanadi."),
            ]
        return [
            block(f"Эта таблица превращает отчётность в {row_count} быстрых проверок здоровья бизнеса: прибыльность, долговая нагрузка, ликвидность, фондирование и эффективность."),
            block("Что делать: сначала смотрите слабые коэффициенты и связывайте их с таблицами выше. Один хороший показатель не спасает картину; итоговая оценка улучшается только когда прибыльность, ликвидность и качество капитала совпадают одновременно."),
        ]

    if role == "key_indicators":
        if lang == "en":
            return [
                block("This summary table is the decision layer of the report: it keeps only the ratios that should directly influence the final assessment."),
                block("What to do: read the red and amber rows first. If the same weakness appears in liquidity, asset quality and capital, the final tone should be cautious even when profit is positive."),
            ]
        if lang == "uz":
            return [
                block("Bu xulosa jadvali hisobotning qaror qatlamidir: unda yakuniy bahoga bevosita ta'sir qiladigan ko'rsatkichlar qoldirilgan."),
                block("Nima qilish kerak: avval xavfli va ehtiyotkor satrlarni o'qing. Bir xil zaiflik likvidlik, aktiv sifati va kapitalda takrorlansa, foyda ijobiy bo'lsa ham yakuniy baho ehtiyotkor bo'lishi kerak."),
            ]
        return [
            block("Сводная таблица — это слой принятия решения: здесь оставлены только показатели, которые прямо меняют итоговую оценку банка."),
            block("Что делать: сначала смотрите строки с выводом «Риск» и «Зона внимания». Если слабый сигнал повторяется сразу в ликвидности, качестве активов и капитале, финальный вывод должен быть осторожным даже при положительной прибыли."),
        ]

    if role == "excel_source":
        return _excel_source_intro_blocks(1, lang)

    return None


def _excel_source_intro_blocks(table_count: int, language: str) -> list[dict]:
    lang = _normalize_language(language)

    def block(text: str) -> dict:
        return {"type": "paragraph", "text": text}

    if lang == "en":
        return [
            block(f"Below are the raw XLSX rows used by the analysis ({table_count} source tables). Use this section only when you want to check where a number came from or why a line affected the conclusion."),
            block("What to do: compare suspicious or large rows with the explanation above. If an important line is here but not explained in the analysis, open the original report or rerun deep Excel analysis for a cleaner result."),
        ]
    if lang == "uz":
        return [
            block(f"Quyida tahlilda ishlatilgan XLSX manba satrlari bor ({table_count} ta manba jadval). Bu bo'lim raqam qayerdan kelganini yoki nima uchun xulosaga ta'sir qilganini tekshirish uchun kerak."),
            block("Nima qilish kerak: shubhali yoki katta satrlarni yuqoridagi izohlar bilan solishtiring. Muhim satr bu yerda bor, lekin tahlilda tushuntirilmagan bo'lsa, asl hisobotni oching yoki chuqur Excel tahlilini qayta ishga tushiring."),
        ]
    return [
        block(f"Ниже показаны исходные строки XLSX, которые использовались в анализе ({table_count} таблиц-источников). Этот раздел нужен не для чтения подряд, а чтобы быстро проверить, откуда взялась цифра и почему она повлияла на вывод."),
        block("Что делать: смотрите только подозрительные или самые крупные строки и сравнивайте их с объяснениями выше. Если важная статья есть здесь, но не объяснена в анализе, откройте исходный отчёт или перезапустите глубокий Excel-анализ."),
    ]


def _table_row_by_keywords(table: dict | None, *keywords: str) -> list[str] | None:
    if not table:
        return None
    lowered_keywords = [keyword.lower() for keyword in keywords]
    for row in table.get("rows") or []:
        label = str(row[0] if row else "").lower()
        if all(keyword in label for keyword in lowered_keywords):
            return row
    return None


def _table_number(row: list[str] | None, index: int) -> float | None:
    if not row or len(row) <= index:
        return None
    return _number_from_report_text(row[index])


def _table_label(row: list[str] | None) -> str:
    return str(row[0] if row else "").strip()


def _format_bln_sum_from_thousand(value: float | None, language: str = "ru") -> str:
    if value is None:
        return "—"
    return f"{_format_report_number(value / 1_000_000, language=language, digits=1)} млрд сум"


def _article_period_label_from_table(table: dict | None) -> str:
    headers = (table or {}).get("headers") or []
    return str(headers[1] or "") if len(headers) > 1 else ""


def _article_previous_period_label_from_table(table: dict | None) -> str:
    headers = (table or {}).get("headers") or []
    for header in headers[2:]:
        text = str(header or "")
        if re.fullmatch(r"\d{2}\.\d{2}\.\d{4}", text):
            return text
    for header in headers[2:]:
        text = str(header or "")
        if text and text.lower() not in {"доля", "share", "ulush"}:
            return text
    return ""


def _article_period_phrase(current_label: str, language: str = "ru") -> str:
    if _normalize_language(language) != "ru":
        return current_label or ""
    match = re.fullmatch(r"(\d{2})\.(\d{2})\.(\d{4})", str(current_label or ""))
    if not match:
        return current_label or ""
    day, month, year = match.groups()
    quarter_map = {
        "03": "I квартала",
        "06": "II квартала",
        "09": "III квартала",
    }
    if month in quarter_map:
        return f"по результатам {quarter_map[month]} {year} года"
    if month == "12":
        return f"по итогам {year} года"
    return f"по состоянию на {day}.{month}.{year}"


def _article_comparison_phrase(table: dict | None, language: str = "ru") -> str:
    if _normalize_language(language) != "ru":
        return ""
    current = _article_period_label_from_table(table)
    previous = _article_previous_period_label_from_table(table)
    if current and previous:
        return f"{current} к {previous}"
    return current


def _article_period_title(base: str, table: dict | None, language: str = "ru") -> str:
    phrase = _article_comparison_phrase(table, language)
    return f"{base} ({phrase})" if phrase and _normalize_language(language) == "ru" else base


def _table_value_by_keywords(table: dict | None, *keywords: str, column_index: int = 1) -> float | None:
    return _table_number(_table_row_by_keywords(table, *keywords), column_index)


def _table_last_value_by_keywords(table: dict | None, *keywords: str, column_index: int = 1) -> float | None:
    if not table:
        return None
    lowered_keywords = [keyword.lower() for keyword in keywords]
    for row in reversed(table.get("rows") or []):
        label = str(row[0] if row else "").lower()
        if all(keyword in label for keyword in lowered_keywords):
            return _table_number(row, column_index)
    return None


def _table_sum_by_keyword_sets(
    table: dict | None,
    keyword_sets: list[tuple[str, ...]],
    *,
    column_index: int = 1,
) -> float | None:
    total = 0.0
    found = False
    seen_labels: set[str] = set()
    for keywords in keyword_sets:
        row = _table_row_by_keywords(table, *keywords)
        if not row:
            continue
        label = _table_label(row)
        if label in seen_labels:
            continue
        value = _table_number(row, column_index)
        if value is None:
            continue
        total += value
        found = True
        seen_labels.add(label)
    return total if found else None


def _tone_from_threshold(value: float | None, good: float, warn: float, *, reverse: bool = False) -> str:
    if value is None:
        return "neutral"
    if reverse:
        if value <= good:
            return "good"
        if value <= warn:
            return "warning"
        return "danger"
    if value >= good:
        return "good"
    if value >= warn:
        return "warning"
    return "danger"


def _article_table_signals(
    assets_h: dict | None,
    liab_h: dict | None,
    income_table: dict | None,
) -> dict:
    assets_total = _table_value_by_keywords(assets_h, "итого актив")
    assets_change = _table_value_by_keywords(assets_h, "итого актив", column_index=3)
    cash = _table_value_by_keywords(assets_h, "касс")
    cbu = _table_value_by_keywords(assets_h, "цбру")
    loans_net = _table_value_by_keywords(assets_h, "кредиты", "лизинг", "нетто")
    if loans_net is None:
        loans_net = _table_value_by_keywords(assets_h, "кредиты", "лизинг")
    gross_loans = _table_value_by_keywords(assets_h, "брутто", "кредит")
    reserve_loans = _table_value_by_keywords(assets_h, "резерв", "потер")
    reserve_change = _table_value_by_keywords(assets_h, "резерв", "потер", column_index=3)

    deposits = _table_value_by_keywords(liab_h, "клиентские депозиты")
    if deposits is None:
        deposits = _table_sum_by_keyword_sets(
            liab_h,
            [
                ("депозиты", "востреб"),
                ("сберегательные", "депозиты"),
                ("срочные", "депозиты"),
            ],
        )
    deposits_change = _table_value_by_keywords(liab_h, "клиентские депозиты", column_index=3)
    if deposits_change is None:
        deposits_change = _table_sum_by_keyword_sets(
            liab_h,
            [
                ("депозиты", "востреб"),
                ("сберегательные", "депозиты"),
                ("срочные", "депозиты"),
            ],
            column_index=3,
        )
    equity = _table_value_by_keywords(liab_h, "итого собственного капитала")
    equity_change = _table_value_by_keywords(liab_h, "итого собственного капитала", column_index=3)

    interest_income = _table_value_by_keywords(income_table, "итого процентных доход")
    interest_expense = _table_value_by_keywords(income_table, "итого процентных расходов")
    non_interest_income = _table_value_by_keywords(income_table, "итого беспроцентных доход")
    operating_expenses = _table_value_by_keywords(income_table, "итого операционных расходов")
    pre_operating_income = _table_value_by_keywords(income_table, "чистый доход до операционных расходов")
    net_profit = _table_last_value_by_keywords(income_table, "чистая прибыль")

    ldr_pct = loans_net / deposits * 100 if loans_net is not None and deposits else None
    first_line_pct = ((cash or 0.0) + (cbu or 0.0)) / assets_total * 100 if assets_total and (cash is not None or cbu is not None) else None
    reserve_coverage_pct = reserve_loans / gross_loans * 100 if reserve_loans is not None and gross_loans else None
    capital_assets_pct = equity / assets_total * 100 if equity is not None and assets_total else None
    interest_coverage = interest_income / interest_expense if interest_income is not None and interest_expense else None
    non_interest_share_pct = (
        non_interest_income / (interest_income + non_interest_income) * 100
        if interest_income is not None and non_interest_income is not None and (interest_income + non_interest_income)
        else None
    )
    cir_pct = operating_expenses / pre_operating_income * 100 if operating_expenses is not None and pre_operating_income else None

    return {
        "assets_total": assets_total,
        "assets_change": assets_change,
        "cash": cash,
        "cbu": cbu,
        "loans_net": loans_net,
        "gross_loans": gross_loans,
        "reserve_loans": reserve_loans,
        "reserve_change": reserve_change,
        "deposits": deposits,
        "deposits_change": deposits_change,
        "equity": equity,
        "equity_change": equity_change,
        "interest_income": interest_income,
        "interest_expense": interest_expense,
        "non_interest_income": non_interest_income,
        "operating_expenses": operating_expenses,
        "pre_operating_income": pre_operating_income,
        "net_profit": net_profit,
        "ldr_pct": ldr_pct,
        "first_line_pct": first_line_pct,
        "reserve_coverage_pct": reserve_coverage_pct,
        "capital_assets_pct": capital_assets_pct,
        "interest_coverage": interest_coverage,
        "non_interest_share_pct": non_interest_share_pct,
        "cir_pct": cir_pct,
    }


def _article_indicator_items(signals: dict, language: str) -> list[dict]:
    if _normalize_language(language) != "ru":
        return []

    items: list[dict] = []

    def assessment(tone: str) -> str:
        return {
            "good": "Норма / сильная сторона",
            "warning": "Зона внимания",
            "danger": "Риск",
        }.get(tone, "Нейтрально")

    def add_pct(
        category: str,
        title: str,
        key: str,
        formula: str,
        hint: str,
        benchmark: str,
        good: float,
        warn: float,
        *,
        reverse: bool = False,
    ):
        value = signals.get(key)
        if value is None:
            return
        tone = _tone_from_threshold(value, good, warn, reverse=reverse)
        result = _format_report_pct(value, language)
        items.append({
            "category": category,
            "label": title,
            "value": result,
            "hint": hint,
            "formula": formula,
            "benchmark": benchmark,
            "assessment": assessment(tone),
            "tone": tone,
        })

    def add_ratio(
        category: str,
        title: str,
        key: str,
        formula: str,
        hint: str,
        benchmark: str,
        good: float,
        warn: float,
    ):
        value = signals.get(key)
        if value is None:
            return
        tone = _tone_from_threshold(value, good, warn)
        result = f"{_format_report_number(value, language=language, digits=2)}×"
        items.append({
            "category": category,
            "label": title,
            "value": result,
            "hint": hint,
            "formula": formula,
            "benchmark": benchmark,
            "assessment": assessment(tone),
            "tone": tone,
        })

    net_profit = signals.get("net_profit")
    if net_profit is not None:
        tone = "good" if net_profit > 0 else "danger" if net_profit < 0 else "neutral"
        items.append({
            "category": "profitability",
            "label": "Чистая прибыль",
            "value": _format_bln_sum_from_thousand(net_profit, language),
            "hint": "Финальный финансовый результат периода после расходов и налога.",
            "formula": "Финансовый результат после операционных расходов, налога и поправок",
            "benchmark": "> 0",
            "assessment": assessment(tone),
            "tone": tone,
        })

    add_pct(
        "liquidity",
        "LDR — кредиты / депозиты",
        "ldr_pct",
        "(Кредиты и лизинг нетто / клиентские депозиты) × 100",
        "Показывает, насколько кредитный портфель покрыт клиентской депозитной базой. Значение выше 100% означает зависимость от дополнительного фондирования.",
        "< 100%",
        100,
        120,
        reverse=True,
    )
    add_pct(
        "liquidity",
        "Ликвидность первой линии",
        "first_line_pct",
        "(Касса + средства в ЦБРУ) / активы × 100",
        "Показывает быстрый запас денег, который можно использовать без продажи кредитов или ценных бумаг.",
        "> 8%",
        8,
        4,
    )
    add_ratio(
        "profitability",
        "Покрытие процентных расходов",
        "interest_coverage",
        "Процентные доходы / процентные расходы",
        "Показывает, насколько процентные доходы перекрывают стоимость денег. Чем ближе к 1×, тем меньше запас маржи.",
        "> 1,5×",
        1.5,
        1.2,
    )
    add_pct(
        "asset_quality",
        "Покрытие брутто-кредитов резервами",
        "reserve_coverage_pct",
        "Резерв на потери / брутто-кредиты × 100",
        "Показывает, какую часть кредитного портфеля банк уже закрыл резервом. Резкий рост ухудшает качество прибыли.",
        "< 2%",
        2,
        3,
        reverse=True,
    )
    add_pct(
        "capital",
        "Капитал / активы",
        "capital_assets_pct",
        "Собственный капитал / активы × 100",
        "Показывает запас прочности баланса до привлечённых денег.",
        "> 12%",
        12,
        8,
    )
    add_pct(
        "efficiency",
        "CIR — расходы / доход",
        "cir_pct",
        "Операционные расходы / чистый доход до операционных расходов × 100",
        "Показывает, сколько операционных затрат съедает доход до налога. Чем ниже, тем лучше операционная эффективность.",
        "< 60%",
        60,
        70,
        reverse=True,
    )
    add_pct(
        "efficiency",
        "Доля непроцентных доходов",
        "non_interest_share_pct",
        "Беспроцентные доходы / (процентные + беспроцентные доходы) × 100",
        "Показывает, насколько прибыль зависит не только от кредитно-депозитной маржи.",
        "20–40%",
        20,
        10,
    )
    return items


def _article_ratio_category_intro(category: str, items: list[dict], signals: dict, language: str) -> str:
    if _normalize_language(language) != "ru":
        return ""
    by_key = {item.get("label"): item for item in items}
    if category == "liquidity":
        ldr = by_key.get("LDR — кредиты / депозиты")
        first_line = by_key.get("Ликвидность первой линии")
        parts = []
        if ldr:
            parts.append(f"LDR равен {ldr['value']}: это показывает, хватает ли депозитов для покрытия кредитного портфеля.")
        if first_line:
            parts.append(f"Ликвидность первой линии составляет {first_line['value']}: это быстрые деньги для покрытия оттока.")
        return " ".join(parts) or "Ликвидность показывает, есть ли у банка быстрый запас денег и насколько кредитный портфель зависит от устойчивой депозитной базы."
    if category == "profitability":
        net_profit = by_key.get("Чистая прибыль")
        coverage = by_key.get("Покрытие процентных расходов")
        parts = []
        if net_profit:
            parts.append(f"Чистая прибыль составила {net_profit['value']}, поэтому банк завершил период с положительным результатом.")
        if coverage:
            parts.append(f"Покрытие процентных расходов — {coverage['value']}, что показывает запас процентной маржи над стоимостью фондирования.")
        return " ".join(parts) or "Рентабельность показывает, превращается ли доходная база банка в реальную прибыль после расходов и резервов."
    if category == "asset_quality":
        reserve = by_key.get("Покрытие брутто-кредитов резервами")
        reserve_change = signals.get("reserve_change")
        text = "Качество активов показывает, насколько кредитный портфель требует резервов и как это влияет на прибыль."
        if reserve:
            text += f" Покрытие брутто-кредитов резервами — {reserve['value']}."
        if reserve_change is not None and reserve_change > 0:
            text += f" Рост резерва на {_format_bln_sum_from_thousand(reserve_change, language)} делает вывод осторожнее: часть результата уходит на покрытие возможных потерь."
        return text
    if category == "capital":
        capital = by_key.get("Капитал / активы")
        equity_change = signals.get("equity_change")
        text = "Достаточность капитала показывает, какой запас прочности есть у банка поверх привлечённых денег."
        if capital:
            text += f" Капитал к активам — {capital['value']}."
        if equity_change is not None and equity_change < 0:
            text += f" Снижение капитала на {_format_bln_sum_from_thousand(abs(equity_change), language)} уменьшает буфер для покрытия ошибок в активах."
        return text
    if category == "efficiency":
        cir = by_key.get("CIR — расходы / доход")
        non_interest = by_key.get("Доля непроцентных доходов")
        parts = []
        if cir:
            parts.append(f"CIR равен {cir['value']}: это показывает, сколько дохода съедают операционные расходы.")
        if non_interest:
            parts.append(f"Доля непроцентных доходов — {non_interest['value']}, то есть доходная база не ограничивается только процентной маржей.")
        return " ".join(parts) or "Операционная эффективность показывает качество бизнес-модели: доход должен расти быстрее расходов и не зависеть от одной статьи."
    return ""


def _article_ratio_section_blocks(
    assets_h: dict | None,
    liab_h: dict | None,
    income_table: dict | None,
    language: str,
) -> list[dict]:
    if _normalize_language(language) != "ru":
        return []

    signals = _article_table_signals(assets_h, liab_h, income_table)
    items = _article_indicator_items(signals, language)
    blocks: list[dict] = []

    if items:
        blocks.append({"type": "kpi_grid", "items": items[:8]})

    category_order = [
        ("liquidity", "5.1. Анализ ликвидности"),
        ("profitability", "5.2. Анализ рентабельности"),
        ("asset_quality", "5.3. Анализ качества активов"),
        ("capital", "5.4. Достаточность капитала"),
        ("efficiency", "5.5. Операционная эффективность"),
    ]
    for category, title in category_order:
        category_items = [item for item in items if item.get("category") == category]
        if not category_items:
            continue
        blocks.append({"type": "subheading", "text": title})
        intro = _article_ratio_category_intro(category, category_items, signals, language)
        if intro:
            blocks.append({"type": "paragraph", "text": intro})
        for item in category_items:
            blocks.append({
                "type": "formula",
                "title": item["label"],
                "formula": item["formula"],
                "result": item["value"],
                "description": item["hint"],
                "tone": item["tone"],
            })
    return blocks


def _key_indicators_article_table(
    assets_h: dict | None,
    liab_h: dict | None,
    income_table: dict | None,
    language: str,
) -> dict | None:
    lang = _normalize_language(language)
    if lang != "ru":
        return None
    signals = _article_table_signals(assets_h, liab_h, income_table)
    items = _article_indicator_items(signals, language)
    rows = [
        [
            {
                "liquidity": "Ликвидность",
                "profitability": "Рентабельность",
                "asset_quality": "Качество активов",
                "capital": "Капитал",
                "efficiency": "Эффективность",
            }.get(item.get("category"), "Показатель"),
            item["label"],
            item["value"],
            item["benchmark"],
            item["assessment"],
            item["hint"],
        ]
        for item in items
    ]
    return _table_from_rows(
        "key_indicators_summary",
        "Таблица 7 — Сводная таблица ключевых показателей",
        ["Блок", "Показатель", "Значение", "Ориентир", "Вывод", "Как влияет на анализ"],
        rows,
        source="openinfo_excel.derived_ratios",
    )


def _article_rating_from_signals(signals: dict, language: str) -> dict:
    items = _article_indicator_items(signals, language)
    danger_count = sum(1 for item in items if item.get("tone") == "danger")
    warning_count = sum(1 for item in items if item.get("tone") == "warning")
    for key in ("assets_change", "deposits_change", "equity_change"):
        value = signals.get(key)
        if value is not None and value < 0:
            warning_count += 1
    reserve_change = signals.get("reserve_change")
    if reserve_change is not None and reserve_change > 0:
        warning_count += 1

    if danger_count >= 3 or (danger_count >= 2 and warning_count >= 3):
        return {
            "tone": "danger",
            "value": "Повышенный риск",
            "text": "Прибыль есть, но несколько ключевых коэффициентов одновременно указывают на давление ликвидности, фондирования или качества активов.",
        }
    if danger_count >= 1 or warning_count >= 3:
        return {
            "tone": "warning",
            "value": "Умеренно рискованное финансовое состояние",
            "text": "Банк сохраняет рабочую прибыльность, но итоговая оценка требует осторожности из-за отдельных слабых сигналов в балансе и коэффициентах.",
        }
    if warning_count:
        return {
            "tone": "neutral",
            "value": "Устойчивое состояние с зонами внимания",
            "text": "Ключевые показатели в целом читаются приемлемо, но отдельные строки нужно отслеживать в следующих кварталах.",
        }
    return {
        "tone": "good",
        "value": "Устойчивое финансовое состояние",
        "text": "Ключевые показатели не показывают критических разрывов между прибыльностью, капиталом и ликвидностью.",
    }


def _article_conclusion_blocks(
    base_text: str,
    assets_h: dict | None,
    liab_h: dict | None,
    income_table: dict | None,
    ratio_table: dict | None,
    language: str,
) -> list[dict]:
    if _normalize_language(language) != "ru":
        return [{"type": "paragraph", "text": base_text or "Final assessment depends on profit quality, balance structure and data completeness."}]

    signals = _article_table_signals(assets_h, liab_h, income_table)
    assets_total = signals.get("assets_total")
    assets_change = signals.get("assets_change")
    equity_change = signals.get("equity_change")
    net_profit = signals.get("net_profit")
    period_phrase = _article_period_phrase(_article_period_label_from_table(assets_h), language)
    rating = _article_rating_from_signals(signals, language)

    if assets_total is not None:
        period_part = f" {period_phrase}" if period_phrase else ""
        intro = (
            f"Итоговая картина{period_part} строится вокруг трёх фактов: активы составляют "
            f"{_format_bln_sum_from_thousand(assets_total, language)}, изменение баланса за период — "
            f"{_format_bln_sum_from_thousand(assets_change, language)}, чистая прибыль — "
            f"{_format_bln_sum_from_thousand(net_profit, language)}. Поэтому вывод нужно читать не только через прибыль, "
            "а через качество фондирования, ликвидность и то, сколько риска уже видно в резервах."
        )
    else:
        intro = base_text or "Итоговая оценка зависит от качества прибыли, структуры баланса и полноты раскрытых данных."

    items: list[dict] = []

    def add(label: str, text: str, tone: str):
        items.append({"label": label, "text": text, "tone": tone})

    if net_profit is not None and net_profit > 0:
        add("Сильная сторона", f"Банк остаётся прибыльным: чистая прибыль составила {_format_bln_sum_from_thousand(net_profit, language)}. Это поддерживает базовую оценку, но не отменяет проверки резервов и капитала.", "good")

    interest_coverage = signals.get("interest_coverage")
    if interest_coverage is not None and interest_coverage >= 1.2:
        add("Маржа", f"Процентные доходы покрывают процентные расходы в {_format_report_number(interest_coverage, language=language, digits=2)}×. Это значит, что основной банковский бизнес генерирует запас над стоимостью денег.", "good" if interest_coverage >= 1.5 else "warning")

    capital_assets = signals.get("capital_assets_pct")
    if capital_assets is not None:
        tone = _tone_from_threshold(capital_assets, 12, 8)
        add("Капитал", f"Капитал к активам равен {_format_report_pct(capital_assets, language)}. Чем ниже этот запас, тем осторожнее нужно читать прибыль и рост портфеля.", tone)

    first_line = signals.get("first_line_pct")
    if first_line is not None:
        tone = _tone_from_threshold(first_line, 8, 4)
        add("Ликвидность", f"Ликвидность первой линии — {_format_report_pct(first_line, language)}. Это быстрые деньги на случай оттока ресурсов; низкое значение делает итоговый тон осторожнее.", tone)

    if assets_change is not None and assets_change < 0:
        add("Риск", f"Баланс сократился на {_format_bln_sum_from_thousand(abs(assets_change), language)}. Само по себе это не плохо, но нужно понимать, ушло ли снижение в плановую переоценку/погашение или в отток ресурсов.", "warning")

    deposits_change = signals.get("deposits_change")
    if deposits_change is not None and deposits_change < 0:
        add("Фондирование", f"Клиентские депозиты снизились на {_format_bln_sum_from_thousand(abs(deposits_change), language)}. Это усиливает важность ликвидности и стоимости альтернативного фондирования.", "warning")

    reserve_change = signals.get("reserve_change")
    if reserve_change is not None and reserve_change > 0:
        add("Кредитный риск", f"Резерв под потери вырос на {_format_bln_sum_from_thousand(reserve_change, language)}. Для анализа это сигнал проверить качество кредитного портфеля, а не смотреть только на чистую прибыль.", "danger")

    if equity_change is not None and equity_change < 0:
        add("Запас прочности", f"Собственный капитал снизился на {_format_bln_sum_from_thousand(abs(equity_change), language)}. Это уменьшает буфер, который покрывает ошибки в активах и рыночные шоки.", "warning")

    if not items:
        add("Что делать дальше", "Сравните самые крупные изменения в таблицах с коэффициентами выше: если слабые места совпадают сразу в балансе, прибыли и ликвидности, итоговую оценку нужно снижать.", "neutral")

    return [
        {"type": "rating", "label": "Итоговая оценка", **rating},
        {"type": "paragraph", "text": intro},
        {"type": "verdict_list", "items": items[:8]},
    ]


def _html_style_table_explanation_blocks(table: dict | None, role: str, language: str) -> list[dict] | None:
    if not table or _normalize_language(language) != "ru":
        return None

    def block(text: str) -> dict:
        return {"type": "paragraph", "text": text}

    rows = table.get("rows") or []
    total_row = _total_report_row(table)
    total_current = _table_number(total_row, 1)
    total_previous = _table_number(total_row, 2)
    total_change = _table_number(total_row, 3)
    total_pct = str(total_row[4]).strip() if total_row and len(total_row) > 4 else "—"
    strongest_growth = next((item for item in _rank_report_rows(table, 3, reverse=True) if item[0] > 0), None)
    strongest_decline = next((item for item in _rank_report_rows(table, 3, reverse=False) if item[0] < 0), None)

    if role == "assets_horizontal":
        investment = _table_row_by_keywords(table, "инвест")
        loans = _table_row_by_keywords(table, "кредит")
        reserves = _table_row_by_keywords(table, "резерв")
        liquid_cbu = _table_row_by_keywords(table, "цбру")
        interbank = _table_row_by_keywords(table, "других банков")
        intro = "Горизонтальный анализ активов показывает, какие части баланса реально изменились за период, а какие только сохранили прежний вес."
        if total_row:
            intro = (
                f"За анализируемый период совокупные активы изменились на "
                f"{_format_bln_sum_from_thousand(total_change, language)} ({total_pct}) и составили "
                f"{_format_bln_sum_from_thousand(total_current, language)}. Это главный масштаб изменения баланса, от которого зависит тон всего дальнейшего анализа."
            )
        main = "Наиболее заметные движения нужно читать не по количеству строк, а по абсолютному влиянию на баланс."
        if strongest_decline:
            main += f" Самое сильное сокращение: «{strongest_decline[1]}» ({strongest_decline[2]})."
        if strongest_growth:
            main += f" Самый сильный рост: «{strongest_growth[1]}» ({strongest_growth[2]})."
        loan_bits = []
        if loans:
            loan_bits.append(f"кредитный портфель: {_table_label(loans)} изменился на {loans[3]} ({loans[4] if len(loans) > 4 else '—'})")
        if reserves:
            loan_bits.append(f"резервы: {_table_label(reserves)} изменились на {reserves[3]} ({reserves[4] if len(reserves) > 4 else '—'})")
        if investment:
            loan_bits.append(f"инвестиции: {_table_label(investment)} изменились на {investment[3]} ({investment[4] if len(investment) > 4 else '—'})")
        detail = "Для пользователя важен практический вывод: изменение активов показывает, где банк зарабатывает будущий доход и где появляется риск."
        if loan_bits:
            detail += " По ключевым строкам видно: " + "; ".join(loan_bits) + "."
        liquidity = "Ликвидность смотрим отдельно: если строки денег, ЦБРУ или межбанковских размещений падают, банк мог использовать быстрые активы для покрытия оттока ресурсов; если они растут, запас манёвра становится выше."
        if liquid_cbu or interbank:
            pieces = []
            if liquid_cbu:
                pieces.append(f"ЦБРУ: {liquid_cbu[3]} ({liquid_cbu[4] if len(liquid_cbu) > 4 else '—'})")
            if interbank:
                pieces.append(f"другие банки: {interbank[3]} ({interbank[4] if len(interbank) > 4 else '—'})")
            liquidity += " В этой таблице ключевые сигналы: " + "; ".join(pieces) + "."
        return [block(intro), block(main), block(detail), block(liquidity)]

    if role == "liabilities_horizontal":
        deposits_demand = _table_row_by_keywords(table, "депозит", "востреб")
        deposits_term = _table_row_by_keywords(table, "сроч")
        debt = _table_row_by_keywords(table, "кредит", "оплат")
        equity = _table_row_by_keywords(table, "собственного капитала")
        intro = "Горизонтальный анализ пассивов показывает, какими деньгами профинансирован баланс: депозитами клиентов, заёмными средствами или собственным капиталом."
        if total_row:
            intro += f" Совокупная строка изменилась на {total_row[3]} ({total_row[4] if len(total_row) > 4 else '—'})."
        funding = "Главный вопрос здесь — устойчивость ресурсной базы."
        moves = []
        for row in (deposits_demand, deposits_term, debt, equity):
            if row:
                moves.append(f"{_table_label(row)}: {row[3]} ({row[4] if len(row) > 4 else '—'})")
        if moves:
            funding += " Ключевые движения: " + "; ".join(moves) + "."
        risk = "Если депозиты сокращаются, а заёмные средства растут, банк сильнее зависит от оптового фондирования и условий рефинансирования. Если капитал снижается, запас прочности хуже даже при сохранении прибыли."
        verdict = "Эта таблица напрямую влияет на итоговую оценку ликвидности и долговой нагрузки: стабильные депозиты и капитал улучшают вывод, отток депозитов и рост дорогого фондирования делают вывод осторожнее."
        return [block(intro), block(funding), block(risk), block(verdict)]

    if role == "assets_vertical":
        largest_ranked = _rank_report_rows(table, 2, reverse=True)
        largest = (largest_ranked[0][1], largest_ranked[0][2]) if largest_ranked else None
        intro = "Вертикальный анализ активов показывает структуру баланса: не сколько банк вырос или снизился, а из чего он состоит."
        if largest:
            intro += f" Крупнейшая доля в текущем периоде — «{largest[0]}» ({largest[1]})."
        loans = _table_row_by_keywords(table, "кредит")
        liquid = _table_row_by_keywords(table, "цбру") or _table_row_by_keywords(table, "касс")
        securities = _table_row_by_keywords(table, "инвест")
        detail = "Для анализа это важнее простой динамики: большая доля кредитов означает зависимость от качества портфеля, большая доля ликвидных активов — запас безопасности, большая доля ценных бумаг — чувствительность к ставкам и переоценке."
        facts = []
        for row in (loans, liquid, securities):
            if row and len(row) > 4:
                facts.append(f"{_table_label(row)}: {row[2]} сейчас против {row[4]} ранее")
        if facts:
            detail += " По структуре видно: " + "; ".join(facts) + "."
        return [block(intro), block(detail)]

    if role == "liabilities_vertical":
        largest_ranked = _rank_report_rows(table, 2, reverse=True)
        largest = (largest_ranked[0][1], largest_ranked[0][2]) if largest_ranked else None
        intro = "Вертикальный анализ пассивов показывает модель фондирования банка: какую долю занимают депозиты, долг и собственный капитал."
        if largest:
            intro += f" Крупнейшая доля в текущем периоде — «{largest[0]}» ({largest[1]})."
        capital = _table_row_by_keywords(table, "собственного капитала")
        liabilities = _table_row_by_keywords(table, "обязательств")
        detail = "Для пользователя это отвечает на простой вопрос: баланс держится на устойчивой клиентской базе и капитале или на более чувствительных заёмных источниках."
        facts = []
        for row in (liabilities, capital):
            if row and len(row) > 4:
                facts.append(f"{_table_label(row)}: {row[2]} сейчас против {row[4]} ранее")
        if facts:
            detail += " Ключевые доли: " + "; ".join(facts) + "."
        return [block(intro), block(detail)]

    if role == "income_statement":
        interest_income = _table_row_by_keywords(table, "итого процентных доход")
        interest_expense = _table_row_by_keywords(table, "итого процентных расход")
        non_interest_income = _table_row_by_keywords(table, "итого беспроцентных доход")
        profit = _table_row_by_keywords(table, "чистая прибыль")
        provisions = _table_row_by_keywords(table, "убыт", "кредит") or _table_row_by_keywords(table, "резерв")
        intro = "Отчёт о финансовых результатах показывает не только размер прибыли, но и качество её источников: процентная маржа, комиссии, валютные операции, резервы и операционные расходы."
        facts = []
        for row in (interest_income, non_interest_income, interest_expense, provisions, profit):
            if row:
                facts.append(f"{_table_label(row)} — {row[1]}")
        if facts:
            intro += " Ключевые суммы: " + "; ".join(facts) + "."
        quality = "Хороший результат считается устойчивым, когда процентные доходы покрывают стоимость фондирования, резервы не съедают маржу, а прибыль не держится только на разовых или плохо раскрытых строках."
        if interest_expense and interest_income:
            expense_ratio = _table_number(interest_expense, 2)
            if expense_ratio is not None:
                quality += f" В этой таблице процентные расходы составляют {interest_expense[2]} от процентных доходов, поэтому маржу нужно оценивать вместе с резервами."
        verdict = "Для итогового вывода это главный раздел по качеству прибыли: рост доходов сам по себе не достаточен, если одновременно растут резервы, стоимость фондирования или операционные расходы."
        return [block(intro), block(quality), block(verdict)]

    if role == "ratio_summary":
        weak_rows = []
        strong_rows = []
        for row in rows:
            text = " ".join(str(cell) for cell in row).lower()
            if "⚠" in text or "высок" in text and any(token in text for token in ("риск", "ухуд", "нагруз")):
                weak_rows.append(row)
            elif "✓" in text or "хорош" in text or "норм" in text:
                strong_rows.append(row)
        intro = "Коэффициентный анализ переводит таблицы в набор быстрых сигналов: ликвидность, рентабельность, качество активов, капитал и эффективность."
        if weak_rows:
            intro += " Сначала стоит смотреть слабые места: " + "; ".join(_table_label(row) for row in weak_rows[:3]) + "."
        balance = "Сводный вывод строится не по одному коэффициенту, а по сочетанию сигналов. Высокая прибыльность улучшает картину только тогда, когда ликвидность, резервы и капитал не дают встречных красных флагов."
        if strong_rows:
            balance += " Поддерживающие показатели: " + "; ".join(_table_label(row) for row in strong_rows[:3]) + "."
        return [block(intro), block(balance)]

    return None


def _table_explanation_blocks(table: dict | None, role: str, language: str) -> list[dict]:
    if not table:
        return []
    html_style_blocks = _html_style_table_explanation_blocks(table, role, language)
    if html_style_blocks is not None:
        return html_style_blocks
    practical_blocks = _practical_table_explanation_blocks(table, role, language)
    if practical_blocks is not None:
        return practical_blocks
    lang = _normalize_language(language)
    row_count = len(table.get("rows") or [])
    total_row = _total_report_row(table)
    total_phrase = _format_change_phrase(total_row)
    strongest_growth = next((item for item in _rank_report_rows(table, 3, reverse=True) if item[0] > 0), None)
    strongest_decline = next((item for item in _rank_report_rows(table, 3, reverse=False) if item[0] < 0), None)
    biggest_change = _largest_abs_table_row(table, 3)
    largest_share = _largest_abs_table_row(table, 2)
    largest_income_share = _largest_abs_table_row(table, 5)

    def block(text: str) -> dict:
        return {"type": "paragraph", "text": text}

    if role == "assets_horizontal":
        if lang == "en":
            opening = f"The horizontal asset table shows the direction and scale of change across {row_count} asset lines."
            if total_phrase:
                opening += f" The headline movement is {total_phrase}, so the first analytical question is whether the balance sheet is expanding normally or shrinking/reallocating capital."
            outlier = ""
            if strongest_decline:
                outlier += f" The largest negative contribution is {strongest_decline[1]} ({strongest_decline[2]})."
            if strongest_growth and strongest_growth[0] > 0:
                outlier += f" The main positive offset is {strongest_growth[1]} ({strongest_growth[2]})."
            return [
                block(opening),
                block((outlier or "The individual line movements show where the balance sheet changed most materially.") + " This matters because asset contraction in liquid reserves, loans or securities has different meanings for future income and liquidity."),
                block("For the final analysis, this table affects the risk tone: falling liquid assets can weaken the safety buffer, falling loans can reduce future interest income, and rapid growth in one asset category can signal concentration or risk accumulation."),
            ]
        if lang == "uz":
            opening = f"Gorizontal aktiv jadvali {row_count} ta aktiv satri bo'yicha o'zgarish yo'nalishi va hajmini ko'rsatadi."
            if total_phrase:
                opening += f" Asosiy harakat: {total_phrase}; shuning uchun balans oddiy o'syaptimi yoki kapital qayta taqsimlanyaptimi, degan savol muhim."
            outlier = ""
            if strongest_decline:
                outlier += f" Eng katta salbiy hissa: {strongest_decline[1]} ({strongest_decline[2]})."
            if strongest_growth and strongest_growth[0] > 0:
                outlier += f" Asosiy ijobiy qarshi harakat: {strongest_growth[1]} ({strongest_growth[2]})."
            return [
                block(opening),
                block((outlier or "Alohida satrlar balans qayerda eng ko'p o'zgarganini ko'rsatadi.") + " Bu muhim, chunki likvid zaxiralar, kreditlar yoki qimmatli qog'ozlardagi o'zgarish kelajakdagi daromad va likvidlikka turlicha ta'sir qiladi."),
                block("Yakuniy tahlilda bu jadval risk tonini o'zgartiradi: likvid aktivlar kamayishi xavfsizlik yostig'ini susaytiradi, kreditlar kamayishi foiz daromadini pasaytiradi, bitta aktiv guruhi tez o'sishi esa konsentratsiya riskini kuchaytiradi."),
            ]
        opening = f"Горизонтальная таблица активов показывает направление и масштаб изменений по {row_count} строкам актива."
        if total_phrase:
            opening += f" Ключевое движение: {total_phrase}; поэтому главный вопрос анализа — баланс реально растёт или происходит сжатие и перераспределение активов."
        outlier = ""
        if strongest_decline:
            outlier += f" Наибольший отрицательный вклад даёт статья «{strongest_decline[1]}» ({strongest_decline[2]})."
        if strongest_growth and strongest_growth[0] > 0:
            outlier += f" Главный положительный противовес — «{strongest_growth[1]}» ({strongest_growth[2]})."
        return [
            block(opening),
            block((outlier or "Движения отдельных строк показывают, где баланс изменился наиболее существенно.") + " Это важно, потому что снижение ликвидных резервов, кредитов или ценных бумаг по-разному влияет на будущий доход и запас ликвидности."),
            block("В итоговой оценке эта таблица меняет тон риска: падение ликвидных активов ослабляет защитный буфер, сокращение кредитов может давить на будущие процентные доходы, а резкий рост одной группы активов указывает на возможную концентрацию риска."),
        ]

    if role == "liabilities_horizontal":
        if lang == "en":
            opening = f"The liabilities and equity table explains how the asset base is funded across {row_count} lines."
            if total_phrase:
                opening += f" The aggregate movement is {total_phrase}, which shows whether the bank is losing resources, replacing deposits with debt, or strengthening its own capital."
            pressure = ""
            if strongest_decline:
                pressure += f" The largest funding reduction is {strongest_decline[1]} ({strongest_decline[2]})."
            if strongest_growth and strongest_growth[0] > 0:
                pressure += f" The largest compensating increase is {strongest_growth[1]} ({strongest_growth[2]})."
            return [
                block(opening),
                block((pressure or "The composition of funding determines how stable the balance sheet is.") + " Deposit outflows are usually more important for liquidity risk than accounting movements inside equity, while rising borrowings can increase dependence on wholesale or regulated funding."),
                block("For the final verdict, this table affects leverage and liquidity assessment: stable capital and deposits support resilience; shrinking deposits, rising short-term debt or falling retained earnings make the analysis more cautious."),
            ]
        if lang == "uz":
            opening = f"Majburiyatlar va kapital jadvali {row_count} satr bo'yicha aktivlar qaysi manbalar bilan moliyalashtirilganini ko'rsatadi."
            if total_phrase:
                opening += f" Umumiy harakat: {total_phrase}; bu bank resurs yo'qotyaptimi, depozitlarni qarz bilan almashtiryaptimi yoki kapitalni kuchaytiryaptimi degan savolga javob beradi."
            pressure = ""
            if strongest_decline:
                pressure += f" Eng katta funding kamayishi: {strongest_decline[1]} ({strongest_decline[2]})."
            if strongest_growth and strongest_growth[0] > 0:
                pressure += f" Eng katta kompensatsion o'sish: {strongest_growth[1]} ({strongest_growth[2]})."
            return [
                block(opening),
                block((pressure or "Funding tarkibi balans barqarorligini belgilaydi.") + " Depozit chiqib ketishi likvidlik riski uchun odatda kapital ichidagi buxgalteriya harakatlaridan muhimroq, qarzlar o'sishi esa ulgurji yoki regulyator fundingiga bog'liqlikni oshiradi."),
                block("Yakuniy xulosada bu jadval leverage va likvidlik bahosiga ta'sir qiladi: barqaror kapital va depozitlar kuch beradi; depozitlar kamayishi, qisqa muddatli qarz o'sishi yoki taqsimlanmagan foyda pasayishi tahlilni ehtiyotkor qiladi."),
            ]
        opening = f"Таблица обязательств и капитала объясняет, за счёт каких источников профинансирована база активов по {row_count} строкам."
        if total_phrase:
            opening += f" Совокупное движение: {total_phrase}; оно показывает, теряет ли банк ресурсную базу, замещает ли депозиты долгом или усиливает собственный капитал."
        pressure = ""
        if strongest_decline:
            pressure += f" Самое крупное сокращение фондирования — «{strongest_decline[1]}» ({strongest_decline[2]})."
        if strongest_growth and strongest_growth[0] > 0:
            pressure += f" Крупнейший компенсирующий рост — «{strongest_growth[1]}» ({strongest_growth[2]})."
        return [
            block(opening),
            block((pressure or "Структура фондирования определяет устойчивость баланса.") + " Отток депозитов обычно важнее для риска ликвидности, чем бухгалтерские движения внутри капитала, а рост заёмных ресурсов повышает зависимость от оптового или регуляторного фондирования."),
            block("Для итогового вердикта эта таблица влияет на оценку долговой нагрузки и ликвидности: стабильный капитал и депозиты поддерживают устойчивость; сокращение депозитов, рост краткосрочного долга или снижение нераспределённой прибыли делают вывод более осторожным."),
        ]

    if role == "assets_vertical":
        if lang == "en":
            detail = f" The largest visible weight is {largest_share[0]} ({largest_share[1]})." if largest_share else ""
            return [
                block(f"Vertical asset analysis is needed because it shows concentration, not just growth.{detail} The same asset change has different meaning when it is a small line item versus a dominant balance-sheet block."),
                block("If loans dominate, the analysis becomes more sensitive to credit quality and reserve dynamics. If liquid assets dominate, liquidity is stronger but profitability can be lower; if securities dominate, valuation and interest-rate risk become more important."),
            ]
        if lang == "uz":
            detail = f" Eng katta ko'rinadigan ulush: {largest_share[0]} ({largest_share[1]})." if largest_share else ""
            return [
                block(f"Vertikal aktiv tahlili faqat o'sishni emas, konsentratsiyani ko'rsatgani uchun kerak.{detail} Bir xil o'zgarish kichik satrda va dominant balans blokida turlicha ma'no beradi."),
                block("Kreditlar ustun bo'lsa, tahlil kredit sifati va rezervlar dinamikasiga sezgir bo'ladi. Likvid aktivlar ustun bo'lsa, likvidlik kuchliroq, lekin rentabellik pastroq bo'lishi mumkin; qimmatli qog'ozlar ustun bo'lsa, baholash va foiz stavkasi riski muhimlashadi."),
            ]
        detail = f" Самая крупная видимая доля: {largest_share[0]} ({largest_share[1]})." if largest_share else ""
        return [
            block(f"Вертикальный анализ активов нужен, потому что показывает не только рост, но и концентрацию.{detail} Одно и то же изменение имеет разный смысл, если оно находится в малой строке или в доминирующем блоке баланса."),
            block("Если доминируют кредиты, итоговая оценка становится чувствительнее к качеству портфеля и резервам. Если велика доля ликвидных активов, запас ликвидности выше, но доходность может быть ниже; если велика доля ценных бумаг, важнее становятся переоценка и процентный риск."),
        ]

    if role == "liabilities_vertical":
        if lang == "en":
            detail = f" The largest visible weight is {largest_share[0]} ({largest_share[1]})." if largest_share else ""
            return [
                block(f"Vertical liabilities/equity analysis shows the funding model rather than only the change in amounts.{detail} A bank with the same asset size can have very different risk depending on whether it is funded by retail deposits, wholesale debt or own capital."),
                block("This section affects the final solvency view: a high capital share creates a buffer, a high deposit share can be stable if deposits are sticky, and a rising debt or repo share increases sensitivity to refinancing conditions."),
            ]
        if lang == "uz":
            detail = f" Eng katta ko'rinadigan ulush: {largest_share[0]} ({largest_share[1]})." if largest_share else ""
            return [
                block(f"Passiv va kapitalning vertikal tahlili faqat summalar o'zgarishini emas, funding modelini ko'rsatadi.{detail} Bir xil aktiv hajmiga ega bank retail depozit, ulgurji qarz yoki kapital bilan moliyalashtirilganiga qarab turlicha riskka ega bo'ladi."),
                block("Bu bo'lim yakuniy to'lov qobiliyati bahosiga ta'sir qiladi: kapital ulushi yuqori bo'lsa bufer kuchli, depozit ulushi barqaror bo'lsa funding sifatli, qarz yoki REPO ulushi oshsa qayta moliyalashtirish sharoitlariga sezgirlik kuchayadi."),
            ]
        detail = f" Самая крупная видимая доля: {largest_share[0]} ({largest_share[1]})." if largest_share else ""
        return [
            block(f"Вертикальный анализ пассивов и капитала показывает не только изменение сумм, но и модель фондирования.{detail} Банк с одинаковым размером активов может иметь разный риск в зависимости от того, профинансирован он розничными депозитами, оптовым долгом или собственным капиталом."),
            block("Этот раздел влияет на итоговую оценку платёжеспособности: высокая доля капитала создаёт буфер, высокая доля устойчивых депозитов поддерживает качество фондирования, а рост долга или РЕПО повышает чувствительность к условиям рефинансирования."),
        ]

    if role == "income_statement":
        if lang == "en":
            detail = f" The largest absolute profit-and-loss movement is {biggest_change[0]}: {biggest_change[1]}." if biggest_change else ""
            share = f" The largest visible weight in the current-period structure is {largest_income_share[0]} ({largest_income_share[1]})." if largest_income_share else ""
            return [
                block(f"The income statement table links growth to profit quality, not just headline revenue.{detail}{share} It shows whether the bank earns from core interest business, commissions, trading/FX operations or one-off lines."),
                block("This matters because revenue growth is not automatically good: if funding costs, provisions or operating expenses grow faster than income, the final analysis becomes more cautious even when the top line looks strong."),
                block("For the final verdict, recurring interest margin and controlled expenses improve quality; dependence on unclear 'other' income, high provisions or fast cost growth reduces confidence in sustainability."),
            ]
        if lang == "uz":
            detail = f" Eng katta foyda-zarar o'zgarishi: {biggest_change[0]}: {biggest_change[1]}." if biggest_change else ""
            share = f" Joriy davr tarkibidagi eng katta ko'rinadigan ulush: {largest_income_share[0]} ({largest_income_share[1]})." if largest_income_share else ""
            return [
                block(f"Moliyaviy natijalar jadvali o'sishni faqat tushum bilan emas, foyda sifati bilan bog'laydi.{detail}{share} U bank asosiy foiz biznesidanmi, komissiyalardanmi, savdo/valyuta operatsiyalaridanmi yoki bir martalik satrlardanmi daromad olayotganini ko'rsatadi."),
                block("Bu muhim, chunki tushum o'sishi avtomatik ravishda yaxshi signal emas: funding xarajatlari, rezervlar yoki operatsion xarajatlar daromaddan tezroq o'ssa, yuqori tushumga qaramay yakuniy baho ehtiyotkor bo'ladi."),
                block("Yakuniy xulosada takrorlanuvchi foiz marjasi va nazoratdagi xarajatlar sifatni oshiradi; noaniq 'boshqa' daromadlar, yuqori rezervlar yoki xarajatlarning tez o'sishi barqarorlikka ishonchni pasaytiradi."),
            ]
        detail = f" Самое крупное движение в отчёте о прибылях и убытках: {biggest_change[0]}: {biggest_change[1]}." if biggest_change else ""
        share = f" Самая крупная видимая доля в структуре текущего периода: {largest_income_share[0]} ({largest_income_share[1]})." if largest_income_share else ""
        return [
            block(f"Таблица финансовых результатов связывает рост бизнеса не только с выручкой, но и с качеством прибыли.{detail}{share} Она показывает, за счёт чего банк зарабатывает: базового процентного бизнеса, комиссий, торговых/валютных операций или разовых статей."),
            block("Это важно, потому что рост доходов сам по себе ещё не является хорошим сигналом: если стоимость фондирования, резервы или операционные расходы растут быстрее доходов, итоговая оценка становится осторожнее даже при сильной верхней строке."),
            block("Для финального вердикта устойчивую оценку поддерживают повторяемая процентная маржа и контролируемые расходы; зависимость от нерасшифрованных «прочих» доходов, высоких резервов или быстрого роста затрат снижает уверенность в устойчивости прибыли."),
        ]

    if role == "ratio_summary":
        if lang == "en":
            return [
                block(f"Ratio analysis turns the raw statements into comparable risk and quality signals across {row_count} metrics. Unlike absolute balance-sheet lines, these indicators show whether the business is efficient relative to its assets, capital and funding base."),
                block("For banks the table includes bank-specific ratios: LDR (loan-to-deposit), first-line liquidity, NIM, CIR, coverage ratio (loan-loss reserve / gross loans), reserve burden (provision expense / interest income), interest income coverage (interest income / interest expense), and non-interest income share. These ratios are computed from XLSX data where available and supplement the standard scoring metrics."),
                block("These figures affect the final verdict because they connect profitability, leverage, liquidity and operating efficiency in one scoring layer. Strong profitability can be offset by weak liquidity or aggressive leverage, while moderate growth can still be attractive if capital quality and coverage are strong."),
            ]
        if lang == "uz":
            return [
                block(f"Koeffitsiyentlar tahlili xom hisobotlarni {row_count} ta solishtiriladigan risk va sifat signaliga aylantiradi. Mutlaq balans satrlaridan farqli ravishda ular biznes aktivlar, kapital va funding bazasiga nisbatan qanchalik samarali ishlayotganini ko'rsatadi."),
                block("Banklar uchun jadvalga bank-spetsifik nisbatlar kiritilgan: LDR, birinchi qator likvidlik, NIM, CIR, qoplama koeffitsienti (zararlar uchun rezerv / brutto kreditlar), rezerv yuki (ta'minotlar / foiz daromadlari), foiz daromadlari qoplanishi (foiz daromadlari / foiz xarajatlari) va nofoiz daromadlar ulushi."),
                block("Bu ko'rsatkichlar yakuniy xulosaga ta'sir qiladi, chunki rentabellik, leverage, likvidlik va operatsion samaradorlikni bitta baholash qatlamida bog'laydi. Kuchli rentabellik zaif likvidlik yoki agressiv leverage bilan neytrallashishi mumkin; o'rtacha o'sish esa kapital sifati va qoplama kuchli bo'lsa jozibali qoladi."),
            ]
        return [
            block(f"Коэффициентный анализ превращает сырые отчёты в {row_count} сопоставимых сигналов риска и качества. В отличие от абсолютных строк баланса, эти показатели показывают, насколько эффективно бизнес работает относительно активов, капитала и ресурсной базы."),
            block("Для банков таблица включает специфические банковские коэффициенты: LDR (кредиты/депозиты), ликвидность 1-й линии, NIM, CIR, коэффициент покрытия (резерв на убытки / брутто-кредиты), нагрузку резервирования (резервы периода / процентные доходы), покрытие процентных расходов доходами и долю непроцентных доходов. Эти показатели вычисляются из данных XLSX там, где они доступны."),
            block("Эти показатели влияют на итоговый вердикт, потому что связывают прибыльность, долговую нагрузку, ликвидность и операционную эффективность в один слой оценки. Сильная рентабельность может быть нейтрализована слабой ликвидностью или агрессивным рычагом, а умеренный рост всё ещё может быть привлекательным при сильном капитале и хорошем покрытии рисков."),
        ]

    if role == "excel_source":
        if lang == "en":
            return [
                block("These appendix tables are included for auditability: they show the source XLSX rows behind the analytical tables. They should not be read as separate conclusions; they are the evidence layer that lets the reader trace where the numbers came from."),
                block("They affect the analysis indirectly: if an important line appears here but not in the analytical sections, it flags a need for manual review; if period columns look unusual, the conclusion should be treated with more caution."),
            ]
        if lang == "uz":
            return [
                block("Bu ilova jadvallari tekshirish uchun qo'shilgan: ular tahliliy jadvallar ortidagi XLSX manba satrlarini ko'rsatadi. Ularni alohida xulosa deb o'qimaslik kerak; ular raqamlar qayerdan kelganini kuzatish uchun dalil qatlamidir."),
                block("Ular tahlilga bilvosita ta'sir qiladi: muhim satr bu yerda bor, lekin tahliliy bo'limlarda yo'q bo'lsa, qo'lda tekshiruv kerak; davr ustunlari noodatiy ko'rinsa, xulosaga ehtiyotkorroq qarash kerak."),
            ]
        return [
            block("Таблицы приложения нужны для проверяемости: они показывают исходные строки XLSX, из которых собраны аналитические таблицы. Их не нужно читать как отдельные выводы; это доказательная база, позволяющая проследить происхождение чисел."),
            block("На анализ они влияют косвенно: если важная строка есть здесь, но не попала в аналитические разделы, это сигнал для ручной проверки; если колонки периодов выглядят нестандартно, итоговый вывод нужно читать осторожнее."),
        ]

    return []


def _table_with_explanation(table: dict | None, role: str, language: str) -> list[dict]:
    if not table:
        return []
    return [
        {"type": "table", **table},
        *_table_explanation_blocks(table, role, language),
    ]


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
) -> dict:
    lang = _normalize_language(language)
    excel_rows = _excel_rows_for_article(company_data)
    for row in excel_rows:
        row["article_kind"] = _article_row_kind(row)

    asset_rows = [row for row in excel_rows if row.get("article_kind") == "assets"]
    liability_rows = [row for row in excel_rows if row.get("article_kind") == "liabilities_equity"]
    income_rows = [row for row in excel_rows if row.get("article_kind") == "income_statement"]

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

    assets_h = _horizontal_article_table("assets_horizontal", captions["assets_h"].get(lang, captions["assets_h"]["ru"]), asset_rows, lang)
    liab_h = _horizontal_article_table("liabilities_horizontal", captions["liab_h"].get(lang, captions["liab_h"]["ru"]), liability_rows, lang)
    assets_v = _vertical_article_table("assets_vertical", captions["assets_v"].get(lang, captions["assets_v"]["ru"]), asset_rows, lang, total_hint="итого актив", fallback_total=_safe_float(total_assets))
    liab_v = _vertical_article_table("liabilities_vertical", captions["liab_v"].get(lang, captions["liab_v"]["ru"]), liability_rows, lang, total_hint="итого обязательств и собственного", fallback_total=_safe_float(total_assets))
    income_table = _income_article_table(income_rows, lang)
    # Compute bank-specific ratios that need raw Excel row data
    _bank = (ifrs_snapshot or {}).get("bank") or {}
    _is_bank = bool(_bank.get("is_bank"))
    _bank_extra: dict = {}
    if _is_bank and excel_rows:
        _snap_income = (ifrs_snapshot or {}).get("income_statement") or {}
        _snap_balance = (ifrs_snapshot or {}).get("balance_sheet") or {}
        _bank_extra = _bank_ratios_from_excel(
            excel_rows,
            total_assets=_safe_float(_snap_balance.get("total_assets")),
            interest_income=_safe_float(_snap_income.get("revenue")),
            interest_expense=_safe_float(_snap_balance.get("interest_expense")),
        )
    ratio_table = _ratio_article_table(metrics or {}, ifrs_snapshot or {}, lang, bank_extra=_bank_extra)
    ratio_blocks = _article_ratio_section_blocks(assets_h, liab_h, income_table, lang)
    key_indicators_table = _key_indicators_article_table(assets_h, liab_h, income_table, lang)
    period_phrase = _article_period_phrase(_article_period_label_from_table(assets_h), lang)
    period_suffix = f" {period_phrase}" if period_phrase and lang == "ru" else ""
    appendix_tables: list[dict] = []

    def p(text: str) -> dict:
        return {"type": "paragraph", "text": text}

    def t(table: dict | None, role: str) -> list[dict]:
        return _table_with_explanation(table, role, lang)

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
                p(_first_article_paragraph(sections, "ДОСЬЕ") or "Анализ построен на публичной отчётности, расчетных метриках и доступных Excel-раскрытиях эмитента."),
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
                p(_first_article_paragraph(sections, "ЧТО_С_ДЕНЬГАМИ") or "Горизонтальный анализ показывает изменение ключевых строк между текущим и предыдущим периодом."),
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
                p("Вертикальный анализ показывает, какая часть активов и пассивов приходится на каждую крупную строку отчётности. Это помогает увидеть концентрацию баланса и зависимость от отдельных статей."),
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
                p(_first_article_paragraph(sections, "ТРЕНД", "ЧТО_С_ДЕНЬГАМИ") or "Раздел сопоставляет доходы, расходы и прибыльность между периодами."),
                *t(income_table, "income_statement"),
            ],
        },
        {
            "id": "ratio_analysis",
            "number": "05",
            "title": {
                "ru": "Коэффициентный анализ",
                "en": "Ratio analysis",
                "uz": "Koeffitsiyentlar tahlili",
            }.get(lang),
            "blocks": [
                p(_first_article_paragraph(sections, "ЭФФЕКТИВНОСТЬ", "ОЦЕНКА_ЦЕНЫ") or "Коэффициенты дополняют табличный разбор и показывают прибыльность, устойчивость баланса и качество операционной модели."),
                *ratio_blocks,
                *t(ratio_table, "ratio_summary"),
            ],
        },
        {
            "id": "key_indicators",
            "number": "06",
            "title": {
                "ru": "Сводная таблица ключевых показателей",
                "en": "Key indicators summary",
                "uz": "Asosiy ko'rsatkichlar xulosasi",
            }.get(lang),
            "blocks": [
                p("Эта таблица собирает главные коэффициенты в один слой: показатель, значение, ориентир и прямое влияние на анализ. Её удобно читать перед финальным выводом, потому что здесь видно, какие сигналы усиливают оценку, а какие требуют осторожности."),
                *t(key_indicators_table, "key_indicators"),
            ],
        },
        {
            "id": "conclusion",
            "number": "07",
            "title": {
                "ru": f"Итоговая оценка финансового состояния {company_name}{period_suffix}".strip(),
                "en": "Final financial condition assessment",
                "uz": "Moliyaviy holat bo'yicha yakuniy baho",
            }.get(lang),
            "blocks": _article_conclusion_blocks(
                _first_article_paragraph(sections, "ИТОГ", "ВЕРДИКТ") or "Итоговая оценка зависит от качества прибыли, структуры баланса и полноты раскрытых данных.",
                assets_h,
                liab_h,
                income_table,
                ratio_table,
                lang,
            ),
        },
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
            "table_count": table_count,
            "excel_row_count": len(excel_rows),
            "excel_source_table_count": len(appendix_tables),
        },
        "abstract": _first_article_paragraph(sections, "ИТОГ", "ВЕРДИКТ", "ДОСЬЕ"),
        "sections": article_sections,
    }


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
    # Keep last 30 for technical indicators computation
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
    report_documents_limit = max(0, min(REPORT_DOCUMENTS_PROMPT_LIMIT, 300))
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
        for item in reports[:report_documents_limit]
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
    excel_reports = company_data.get("excel_reports") or {}
    excel_items = []
    excel_prompt_limit = max(0, min(EXCEL_PROMPT_MAX_REPORTS, ABSOLUTE_EXCEL_REPORT_LIMIT))
    sheet_limit = max(1, min(EXCEL_PROMPT_MAX_SHEETS_PER_REPORT, 10))
    row_limit = max(1, min(EXCEL_PROMPT_MAX_ROWS_PER_SHEET, 30))
    for report in (excel_reports.get("items") or [])[:excel_prompt_limit]:
        compact_sheets = []
        for sheet in (report.get("sheets") or [])[:sheet_limit]:
            compact_sheets.append({
                "sheet": sheet.get("sheet"),
                "matched_rows": [
                    {
                        "row": row.get("row"),
                        "label": row.get("label"),
                        "numeric_values": row.get("numeric_values"),
                        "values": (row.get("values") or [])[:8],
                    }
                    for row in (sheet.get("matched_rows") or [])[:row_limit]
                ],
            })
        excel_items.append({
            "report_id": report.get("report_id"),
            "object_id": report.get("object_id"),
            "published_at": report.get("published_at"),
            "period_type": report.get("period_type"),
            "report_form": report.get("report_form"),
            "title": report.get("title"),
            "from_cache": report.get("from_cache", False),
            "content_length": report.get("content_length"),
            "sheet_count": report.get("sheet_count"),
            "facts_count": report.get("facts_count"),
            "sheets": compact_sheets,
        })

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
        "market_availability": market.get("availability") or {},
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
        "excel_report_snapshots": {
            "enabled": excel_reports.get("enabled", False),
            "count": excel_reports.get("count", 0),
            "selected_count": excel_reports.get("selected_count", 0),
            "included_in_prompt": len(excel_items),
            "items": excel_items,
            "errors": (excel_reports.get("errors") or [])[:5],
        },
        "accounting_api_summary": (company_data.get("accounting") or {}).get("summary") or {},
    }


def _slim_market_context_for_prompt(market_context: dict) -> dict:
    """Create a slimmed version of market context for the AI prompt to reduce input tokens."""
    if not market_context or market_context.get("status") != "ok":
        return market_context

    # Only include last 10 price points instead of 30 for prompt
    recent_prices = market_context.get("recent_price_history") or []
    slim_prices = [
        {"date": p.get("date"), "close": p.get("close"), "volume": p.get("trading_volume")}
        for p in recent_prices[-10:]
    ]

    # Only include last 3 reports instead of all
    reports = market_context.get("report_documents") or {}
    slim_reports = {
        "count": reports.get("count", 0),
        "items": (reports.get("items") or [])[:3],
    }

    # Only include last 2 dividends
    dividends = market_context.get("dividends") or {}
    slim_dividends = {
        "count": dividends.get("count", 0),
        "items": (dividends.get("items") or [])[:2],
    }

    excel_reports = market_context.get("excel_report_snapshots") or {}
    slim_excel_reports = {
        "enabled": excel_reports.get("enabled", False),
        "count": excel_reports.get("count", 0),
        "selected_count": excel_reports.get("selected_count", 0),
        "included_in_prompt": excel_reports.get("included_in_prompt", 0),
        "items": excel_reports.get("items") or [],
        "errors": excel_reports.get("errors") or [],
    }

    return {
        "status": "ok",
        "security": market_context.get("security"),
        "market_summary": market_context.get("market_summary"),
        "market_availability": market_context.get("market_availability") or {},
        "fibonacci_levels": market_context.get("fibonacci_levels"),
        "recent_price_history": slim_prices,
        "dividends": slim_dividends,
        "report_documents": slim_reports,
        "excel_report_snapshots": slim_excel_reports,
    }


def _slim_technical_indicators_for_prompt(indicators: dict) -> dict:
    """Create a slimmed version of technical indicators for the AI prompt."""
    if not indicators or indicators.get("status") != "ok":
        return indicators

    slim = {"status": "ok"}

    # RSI - keep essential
    if "rsi" in indicators:
        rsi = indicators["rsi"]
        slim["rsi"] = {
            "value": rsi.get("value"),
            "signal": rsi.get("signal"),
        }

    # Fibonacci - keep key levels only
    if "fibonacci_price" in indicators:
        fib = indicators["fibonacci_price"]
        slim["fibonacci"] = {
            "current_price": fib.get("current_price"),
            "current_zone": fib.get("current_zone"),
            "nearest_support": fib.get("nearest_support"),
            "nearest_resistance": fib.get("nearest_resistance"),
        }

    # Price momentum - keep summary
    if "price_momentum" in indicators:
        mom = indicators["price_momentum"]
        slim["momentum"] = {
            "trend": mom.get("trend"),
            "total_change_pct": mom.get("changes", {}).get("total"),
        }

    # Volume - keep signal
    if "volume_analysis" in indicators:
        vol = indicators["volume_analysis"]
        slim["volume"] = {
            "signal": vol.get("signal"),
            "divergence": vol.get("divergence"),
        }

    # Volatility - keep level
    if "volatility" in indicators:
        slim["volatility"] = {
            "annual_pct": indicators["volatility"].get("annual_pct"),
            "level": indicators["volatility"].get("level"),
        }

    # Overall summary
    if "summary" in indicators:
        slim["summary"] = indicators["summary"].get("overall")

    return slim


def _compute_bank_profile(latest: dict, prev: dict | None) -> dict | None:
    """Compute bank-specific ratios (CAR, NIM, LDR, CIR) when the company has
    bank-shaped balance sheet (customer_deposits / loans_to_customers).

    Returns None for non-banks so the front-end can skip the bank panel."""
    customer_deposits = _safe_float(latest.get("customer_deposits"))
    loans = _safe_float(latest.get("loans_to_customers"))
    interbank = _safe_float(latest.get("interbank_deposits"))
    if customer_deposits is None and loans is None and interbank is None:
        return None

    total_assets = _safe_float(latest.get("total_assets"))
    equity = _safe_float(latest.get("equity"))
    revenue = _safe_float(latest.get("revenue"))           # interest income for banks
    gross_profit = _safe_float(latest.get("gross_profit"))  # net interest income
    operating_expenses = _safe_float(latest.get("operating_expenses"))
    net_income = _safe_float(latest.get("net_income"))
    interest_expense = _safe_float(latest.get("interest_expense"))

    def pct(num, den):
        if num is None or den in (None, 0):
            return None
        return round(num / den * 100, 2)

    # CAR (simplified: equity / total assets — true CAR needs risk-weighted assets)
    car_simple = pct(equity, total_assets)
    # NIM: net interest income / total assets
    nim = pct(gross_profit, total_assets)
    # LDR: loans / customer deposits
    ldr = pct(loans, customer_deposits)
    # CIR: operating expenses / (net interest income + ... ) ≈ opex / revenue (interest income)
    # Use gross_profit (NII) as denominator when revenue is sketchy
    cir_denom = gross_profit if gross_profit and gross_profit > 0 else revenue
    cir = pct(operating_expenses, cir_denom) if operating_expenses is not None else None
    # Cost of funds (rough): interest_expense / customer_deposits
    cost_of_funds = pct(interest_expense, customer_deposits)
    # Loan-to-asset
    loan_to_assets = pct(loans, total_assets)
    # ROA / ROE — банк-aware (используем то же net_income / equity / assets)
    bank_roa = pct(net_income, total_assets)
    bank_roe = pct(net_income, equity)
    # Interest income coverage (banking): interest income / interest expense
    int_income_cov = None
    if revenue is not None and interest_expense not in (None, 0):
        int_income_cov = round(revenue / abs(interest_expense), 3)

    def tone(value, good, bad, reverse=False):
        if value is None:
            return "neutral"
        if reverse:  # lower is better (CIR, cost of funds)
            return "good" if value <= good else "warning" if value <= bad else "danger"
        return "good" if value >= good else "warning" if value >= bad else "danger"

    return {
        "is_bank": True,
        "car_simple_pct": car_simple,           # capital adequacy (equity/assets)
        "nim_pct": nim,                          # net interest margin
        "ldr_pct": ldr,                          # loan-to-deposit
        "cir_pct": cir,                          # cost-to-income
        "loan_to_assets_pct": loan_to_assets,
        "roa_pct": bank_roa,
        "roe_pct": bank_roe,
        "interest_income_coverage": int_income_cov,  # interest income / interest expense
        "tones": {
            "car_simple_pct": tone(car_simple, 10, 6),
            "nim_pct": tone(nim, 4, 2),
            "ldr_pct": tone(ldr, 70, 95, reverse=True) if ldr is not None and ldr > 100
                       else tone(ldr, 90, 70),
            "cir_pct": tone(cir, 50, 65, reverse=True),
            "interest_income_coverage": tone(int_income_cov, 1.5, 1.2),
        },
        "notes": {
            "car_simple_pct": "Достаточность капитала (equity / активы) — рисково-взвешенный CAR требует RWA, которого нет в публичной отчётности.",
            "nim_pct": "Чистый процентный доход / активы — сколько банк зарабатывает на каждом сум активов.",
            "ldr_pct": "Кредиты / депозиты — насколько активно банк раздаёт собранные деньги.",
            "cir_pct": "Операционные расходы / чистый процентный доход — сколько съедает обслуживание.",
            "interest_income_coverage": "Процентные доходы / процентные расходы — сколько раз доходы покрывают стоимость фондирования.",
        },
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
        "bank": _compute_bank_profile(latest, prev),
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
    {"key": "latest_year", "label": "Год", "unit": "", "better": "neutral"},
    {"key": "revenue", "label": "Выручка", "unit": "UZS млн", "better": "higher"},
    {"key": "revenue_growth_pct", "label": "Рост выручки", "unit": "%", "better": "higher"},
    {"key": "net_income", "label": "Чистая прибыль", "unit": "UZS млн", "better": "higher"},
    {"key": "net_income_growth_pct", "label": "Рост прибыли", "unit": "%", "better": "higher"},
    {"key": "net_profit_margin_pct", "label": "Чистая маржа", "unit": "%", "better": "higher"},
    {"key": "gross_profit_margin_pct", "label": "Валовая маржа", "unit": "%", "better": "higher"},
    {"key": "roe_pct", "label": "ROE", "unit": "%", "better": "higher"},
    {"key": "roa_pct", "label": "ROA", "unit": "%", "better": "higher"},
    {"key": "debt_ratio_pct", "label": "Долг/активы", "unit": "%", "better": "lower"},
    {"key": "debt_to_equity_ratio", "label": "Debt/Equity", "unit": "x", "better": "lower"},
    {"key": "current_ratio", "label": "Current ratio", "unit": "x", "better": "higher"},
    {"key": "quick_ratio", "label": "Quick ratio", "unit": "x", "better": "higher"},
    {"key": "balance_quality_score", "label": "Качество баланса", "unit": "/100", "better": "higher"},
    {"key": "piotroski_score", "label": "Piotroski", "unit": "/9", "better": "higher"},
    {"key": "altman_score", "label": "Altman Z", "unit": "", "better": "higher"},
    {"key": "latest_price", "label": "Цена", "unit": "UZS", "better": "neutral"},
    {"key": "day_change_percent", "label": "За день", "unit": "%", "better": "neutral"},
    {"key": "period_change_percent", "label": "За период", "unit": "%", "better": "neutral"},
    {"key": "avg_daily_trading_value", "label": "Ср. оборот", "unit": "UZS", "better": "higher"},
    {"key": "total_trading_value", "label": "Всего оборот", "unit": "UZS", "better": "higher"},
    {"key": "dividend_count", "label": "Дивиденды", "unit": "шт.", "better": "higher"},
    {"key": "report_document_count", "label": "Отчеты", "unit": "шт.", "better": "higher"},
    {"key": "pdf_report_count", "label": "PDF отчетов", "unit": "шт.", "better": "higher"},
    {"key": "excel_report_count", "label": "Excel отчетов", "unit": "шт.", "better": "higher"},
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
    # Reduced max_output_tokens from 1200 to 600 for faster response
    profile, response = _responses_text(f"{PROFILE_STYLE_NOTE}\n\n{prompt}", instructions, max_output_tokens=600)

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
            "excel_report_snapshot_count": (market_context.get("excel_report_snapshots") or {}).get("count"),
        }

    # Compute technical indicators from price history
    technical_indicators = {}
    price_history = market_context.get("recent_price_history") or []
    if price_history:
        technical_indicators = compute_technical_indicators(price_history)
        if technical_indicators.get("status") == "ok":
            metrics["technical_indicators"] = technical_indicators

    prompt = f"""
Ты — старший инвестиционный аналитик. Пишешь полноформатную аналитическую записку по отчётности.
Твоя задача — глубокий финансовый разбор с числами, формулами и оценкой каждого показателя.
НЕ пересказывай данные — интерпретируй их: что это значит для устойчивости бизнеса и инвестора.

Язык ответа: {LANGUAGE_HINTS[lang]['label']}

Жёсткие правила:
{PUBLIC_ANALYSIS_POLICY}

- Use PUBLIC MARKET DATA for quotes, price history, trading volumes, dividends, report documents and Fibonacci levels. If unavailable, say so.
- Use EXCEL REPORT SNAPSHOTS as direct public report extracts. If they conflict with API figures, note the discrepancy.
- Используй только данные из отчётности, метрик, IFRS snapshot и PUBLIC MARKET DATA ниже.
- Никаких общих фраз, маркетинга, воды, литературных отступлений и лишних вступлений.
- Каждое утверждение — цифра или явный показатель. Норма → факт → вывод.
- Сравнивай с нормами UZ-рынка. Аббревиатуры в ОСНОВНОМ тексте допустимы — при первом упоминании давай расшифровку в скобках 3–6 слов.
- Формулы обязательны для ключевых коэффициентов: записывай «Показатель = Числитель / Знаменатель = Значение».
- Для банков: дай все 5 групп коэффициентов (ликвидность, рентабельность, качество активов, достаточность капитала, операционная эффективность).
- Квартальные показатели рентабельности (ROA, ROE, NIM) аннуализируй (×4) и указывай оба значения.

Формат таблиц:
- В [ЧТО_С_ДЕНЬГАМИ] и [ТРЕНД] после «Кратко» — одна Markdown-таблица (через |) с реальными данными. Подпись: «Таблица 1 — …» отдельной строкой.
- В [ЭФФЕКТИВНОСТЬ] — обязательная сводная таблица коэффициентов с колонками: Показатель | Значение | Ориентир / норма | Оценка.
- Не придумывай строки. Нет данных — пиши «Недостаточно данных» и переходи к тексту.
- После таблицы — 3–5 аналитических абзацев: что изменилось, почему важно, где риск, где позитив.

Фокус анализа:
[Для всех компаний]
1) Выручка / процентные доходы и их динамика
2) Валовая прибыль / чистый процентный доход и маржа
3) Операционные расходы и операционная прибыль
4) Чистая прибыль и чистая маржа
5) Ликвидность и денежная позиция
6) Долговая нагрузка и устойчивость баланса
7) ROE, ROA — квартал и аннуализация
8) DCF как одно из подтверждений, не единственный аргумент

[Для банков — обязательно в дополнение]
9) LTD = Кредиты / Депозиты → норма <100%, сигнал при >120%
10) Ликвид. активы 1-й линии / Активы = (Касса + ЦБ) / Активы → норма >5%
11) Coverage ratio = Резерв на убытки / Брутто-кредиты → норма <2%; динамика vs предыдущий период
12) Нагрузка резервирования = Расходы на резервы / Проц. доходы → норма <10%
13) NIM = ЧПД до резервов / Активы → квартал + аннуализация → норма 3–5%
14) CIR = Операц. расходы / (ЧПД + Беспроц. доходы) → норма 40–60%
15) Покрытие % расходов = Проц. доходы / Проц. расходы → норма >1,2×
16) Доля непроц. доходов = Беспроц. доходы / Совокупные доходы → норма 20–40%
17) CAR (упрощ.) = Капитал / Активы → норма >8%

Компания:
{company_name}

Валюта и масштаб:
{slim["currency"]}

IFRS SNAPSHOT:
{json.dumps(ifrs_snapshot, ensure_ascii=False, indent=2)}

PUBLIC MARKET DATA (slimmed for prompt):
{json.dumps(_slim_market_context_for_prompt(market_context), ensure_ascii=False, indent=2)}

TECHNICAL INDICATORS (slimmed for prompt):
{json.dumps(_slim_technical_indicators_for_prompt(technical_indicators), ensure_ascii=False, indent=2) if technical_indicators else '{"status": "нет данных о ценах"}'}

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

ЖЁСТКИЕ ПРАВИЛА блока «Кратко»:
1. В «Кратко» ЗАПРЕЩЕНЫ голые аббревиатуры (ROE, ROA, NIM, CIR, LDR, CAR, D/E…).
   Заменяй бытовыми аналогами: «на каждый сум вложенного капитала банк зарабатывает 28 копеек прибыли».
2. Каждая цифра — человеческим языком: «выросла на 38%», «долгов в 5,5 раза больше собственных денег».
3. Плюсы и минусы — 2–3 пункта каждый. Не повторяй тезис дважды.
4. «Для тебя» — не рекомендация купить/продать. Что это значит для частного инвестора на практике.

Формат каждой секции:
[МЕТКА_СЕКЦИИ]
Кратко
Тон: <позитивный | умеренный | тревожный | критичный | нет_данных>
Плюсы:
- ...
Минусы:
- ...
Для тебя: ...

<пустая строка>
<полный аналитический текст секции — минимум 3 абзаца>

Формат ответа:
[СКОРИНГ]
Кратко
Тон: ...
Скор: XX/100
Плюсы:
- ...
Минусы:
- ...
Для тебя: ...

Класс: A / B / C / D
Расшифровка: 3–4 предложения с ключевыми числами. Укажи главное сильное место и главный риск.
Для банков: обязательно назови LTD, CAR, NIM и Coverage ratio с числами.

[ДОСЬЕ]
Кратко
Тон: ...
Плюсы:
- ...
Минусы:
- ...
Для тебя: ...

4–5 предложений: чем зарабатывает компания, рыночная позиция, масштаб, форма собственности.
Для банков: специализация (ипотечный / универсальный / корпоративный), доля государства, тикеры.

[ЧТО_С_ДЕНЬГАМИ]
Кратко
Тон: ...
Плюсы:
- ...
Минусы:
- ...
Для тебя: ...

Таблица 1 — Ключевые показатели баланса и доходов (реальные данные, не выдуманные):
| Показатель | Текущий период | Предыдущий период | Изм., % |
|---|---|---|---|
| ... | ... | ... | ... |

После таблицы — 3–5 аналитических абзацев.

[Для банков в основном тексте обязательно]:
• Горизонтальный анализ баланса: ключевые изменения активов (кредиты, инвестиции, ликвидность),
  обязательств (депозиты, займы, РЕПО) и капитала. Что выросло — что упало — почему это важно.
• LTD (кредиты к депозитам) = Кредиты нетто / (Депозиты до востреб. + Срочные) = X%  (норма: <100%)
• Ликвид. активы 1-й линии / Активы = (Касса + Счёт в ЦБ) / Итого активов = X%  (норма: >5%)
• Coverage ratio = Резерв на убытки / Брутто-кредиты = X%  (норма: <2%; динамика vs пред. период)
• Нагрузка резервирования = Расходы на резервы / Проц. доходы = X%  (норма: <10%)
• Для каждого: вычисли сам по данным IFRS snapshot, укажи числа и оценку (✓ норма / ⚠ превышение).

[ТРЕНД]
Кратко
Тон: ...
Плюсы:
- ...
Минусы:
- ...
Для тебя: ...

Таблица 2 — Динамика доходов, расходов и прибыли:
| Статья | Период 1 | Период 2 | Период 3 | Изм. |
|---|---|---|---|---|
| ... | ... | ... | ... | ... |

3–5 абзацев: направление по доходам/марже/прибыли за доступные периоды.
Для банков: разбери Форму 2 — процентные доходы → расходы → ЧПД до резервов → резервы →
беспроцентные доходы/расходы → операционные расходы → прибыль до налогов → чистая прибыль.
Укажи долю каждой статьи от процентных доходов.

[ЭФФЕКТИВНОСТЬ]
Кратко
Тон: ...
Плюсы:
- ...
Минусы:
- ...
Для тебя: ...

Таблица 3 — Сводный коэффициентный профиль:
| Группа | Показатель | Значение | Ориентир / норма | Оценка |
|---|---|---|---|---|
| Ликвидность | LTD | X% | <100% | ✓/⚠ |
| Ликвидность | Ликвид. активы 1-й линии / Активы | X% | >5% | ✓/⚠ |
| Рентабельность | ROA (аннуализ.) | X% | 1–2% (банки) | ✓/⚠ |
| Рентабельность | ROE (аннуализ.) | X% | 10–20% | ✓/⚠ |
| Рентабельность | NIM (аннуализ.) | X% | 3–5% | ✓/⚠ |
| Рентабельность | Чистая маржа | X% | 15–25% | ✓/⚠ |
| Качество активов | Coverage ratio (текущ.) | X% | <2% | ✓/⚠ |
| Качество активов | Coverage ratio (пред.) | X% | <2% | ✓/⚠ |
| Качество активов | Нагрузка резервирования | X% | <10% | ✓/⚠ |
| Капитал | CAR (Капитал / Активы) | X% | >8% | ✓/⚠ |
| Капитал | Коэф. задолженности | X% | ~85% (банки) | ✓/⚠ |
| Капитал | D/E | Xх | 4–8х (банки) | ✓/⚠ |
| Эффективность | CIR | X% | 40–60% | ✓/⚠ |
| Эффективность | Покрытие % расходов | Xх | >1,2х | ✓/⚠ |
| Эффективность | Доля непроц. доходов | X% | 20–40% | ✓/⚠ |

Заполняй таблицу реальными числами из IFRS snapshot и метрик. После таблицы — 3–5 абзацев:
детальный разбор каждой группы (ликвидность → рентабельность → качество активов → капитал → эффективность).
Для нефинансовых компаний: замени банковские коэффициенты на оборачиваемость (дни запасов, дебиторки,
кредиторки, CCC), покрытие процентов (EBIT / проц. расходы), текущую ликвидность.

[ТЕХНИЧЕСКИЙ_АНАЛИЗ]
Кратко
Тон: ...
Плюсы:
- ...
Минусы:
- ...
Для тебя: ...

Если есть TECHNICAL INDICATORS: RSI и сигнал, Fibonacci-зона и ближайшие уровни,
объёмы (растут/падают), волатильность. Если данных нет — «Рыночные данные отсутствуют».

[ОЦЕНКА_ЦЕНЫ]
Кратко
Тон: ...
Плюсы:
- ...
Минусы:
- ...
Для тебя: ...

Дорого или дёшево по DCF и отраслевым мультипликаторам — только с числами.
Не упоминай Piotroski, Altman, Buffett, Graham.

[КАТАЛИЗАТОРЫ]
Кратко
Тон: ...
Плюсы:
- ...
Минусы:
- ...
Для тебя: ...

2–4 конкретных фактора из данных, влияющих на риск/оценку. Не прогнозируй будущее.

[СИЛЬНЫЕ_СТОРОНЫ]
Кратко
Тон: позитивный
Плюсы:
- ...
Минусы:
- (если есть оговорки к сильным сторонам)
Для тебя: ...

Минимум 3 пункта, каждый с числом:
• Сильная сторона №1 — [Что]: [Показатель с цифрой] — [Почему это важно, 1–2 предложения]
• Сильная сторона №2 — ...
• Сильная сторона №3 — ...

[СЛАБЫЕ_СТОРОНЫ]
Кратко
Тон: тревожный или критичный
Плюсы:
- (если есть смягчающие обстоятельства)
Минусы:
- ...
Для тебя: ...

Минимум 3 пункта, каждый с числом:
• Риск №1 — [Что]: [Показатель с цифрой] — [Почему это важно, 1–2 предложения]
• Риск №2 — ...
• Риск №3 — ...

[РЫНОЧНЫЕ_ДАННЫЕ]
Кратко
Тон: ...
Плюсы:
- ...
Минусы:
- ...
Для тебя: ...

Котировки, объёмы, дивиденды, отчётные документы. По каждому: «есть» / «нет в наборе». Без прогнозов.

[ВЕРДИКТ]
Кратко
Тон: ...
Плюсы:
- ...
Минусы:
- ...
Для тебя: ...

Информационный статус: СИЛЬНАЯ ОТЧЁТНОСТЬ / УМЕРЕННАЯ ОТЧЁТНОСТЬ / СЛАБАЯ ОТЧЁТНОСТЬ / ПОВЫШЕННЫЙ РИСК / НЕДОСТАТОЧНО ДАННЫХ.
Обоснование цифрами: какие группы коэффициентов в норме, какие — вне нормы.
Не давай инвестиционных рекомендаций.

[ОГРАНИЧЕНИЯ_ПУБЛИЧНОГО_КОНТУРА]
Кратко
Тон: нет_данных
Минусы:
- (отсутствующие категории публичных данных)
Для тебя: ...

Что анализ не содержит: персональные данные, прогнозы, инвест-рекомендации, юридические заключения.

[ИТОГ]
Кратко
Тон: ...
Плюсы:
- (главные плюсы простыми словами)
Минусы:
- (главные минусы простыми словами)
Для тебя: ...

ХЕРО-АБЗАЦ ДЛЯ НОВИЧКА (4–6 предложений). Объясняй как школьнику 9 класса — без единого термина без перевода.
Последняя фраза: «стоит ли вкладываться обычному частному инвестору и почему».

СИЛЬНЫЕ СТОРОНЫ (минимум 3 — повтори из [СИЛЬНЫЕ_СТОРОНЫ] самые важные с числами):
• Сильная сторона №1 — [Что]: [Показатель] — [Значимость]
• Сильная сторона №2 — ...
• Сильная сторона №3 — ...

РИСКИ (минимум 3 — повтори из [СЛАБЫЕ_СТОРОНЫ] самые важные с числами):
• Риск №1 — [Что]: [Показатель] — [Значимость]
• Риск №2 — ...
• Риск №3 — ...
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
        "Квартальные ROA/ROE/NIM аннуализируй (×4) и указывай оба значения.\n\n"
        "В [СИЛЬНЫЕ_СТОРОНЫ] и [СЛАБЫЕ_СТОРОНЫ]: минимум 3 пункта каждый, "
        "формат «• Сильная сторона №N — [Что]: [Показатель с числом] — [Значимость 1–2 предл.]».\n\n"
        "В [ИТОГ]: ХЕРО-АБЗАЦ 4–6 предложений (язык 9-классника, без термина без перевода), "
        "финал «стоит ли вкладываться и почему»; затем СИЛЬНЫЕ СТОРОНЫ (≥3) и РИСКИ (≥3) с числами.\n\n"
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


async def run_company_analysis(
    company_name: str,
    force_refresh: bool = False,
    language: str = "ru",
    include_all_excel_reports: bool = False,
    excel_report_limit: int | None = None,
) -> dict:
    company_name = (company_name or "").strip()
    if not company_name:
        raise ValueError("company_name cannot be empty")
    language = _normalize_language(language)
    excel_report_limit = _normalize_excel_report_limit(
        excel_report_limit,
        include_all=include_all_excel_reports,
    )
    excel_report_mode = {
        "include_all": include_all_excel_reports,
        "limit": excel_report_limit,
    }
    cache_mode = _analysis_cache_mode(include_all_excel_reports, excel_report_limit)
    allow_cache = not force_refresh

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
            )
            cached["article_report_version"] = ARTICLE_REPORT_VERSION
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
        "liquidity": liquidity_data,
        "market_data": company_data,
        "market_context": market_context,
        "excel_report_mode": excel_report_mode,
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

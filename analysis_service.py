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
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5.4-mini").strip() or "gpt-5.4-mini"
OPENAI_REASONING_EFFORT = os.getenv("OPENAI_REASONING_EFFORT", "low").strip().lower() or "low"
ANALYSIS_POLICY_VERSION = "public-information-v8-expanded-article-report-2026-05-31"
REPORT_TABLES_VERSION = "report-tables-v1"
ARTICLE_REPORT_VERSION = "article-report-v2"
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
            "change": "Change, UZS mln",
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
            "change": "O'zgarish, mln so'm",
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
        "change": "Изм., млн сум",
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
            for row in sheet.get("table_rows") or []:
                label = str(row.get("label") or "").strip()
                if not label:
                    continue
                rows.append({
                    **row,
                    "label": label,
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
    for row in source_rows:
        label = _clean_article_label(row.get("label"))
        if label in seen:
            continue
        pair = _article_amount_pair(row)
        if not pair:
            continue
        current, previous = pair
        change = current - previous
        pct = (change / abs(previous) * 100) if previous else None
        rows.append([
            label,
            _format_report_number(current, language),
            _format_report_number(previous, language),
            _format_report_number(change, language, signed=True),
            _format_report_pct(pct, language, signed=True),
        ])
        seen.add(label)
        if len(rows) >= limit:
            break
    return _table_from_rows(
        table_id,
        caption,
        [labels["line"], labels["current"], labels["previous"], labels["change"], labels["change_pct"]],
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
    total = fallback_total
    for row in source_rows:
        label = str(row.get("label") or "").lower()
        if total_hint in label:
            total = _article_current_amount(row)
            break
    if not total:
        return None

    rows = []
    seen = set()
    for row in source_rows:
        label = _clean_article_label(row.get("label"))
        if label in seen:
            continue
        current = _article_current_amount(row)
        if current is None:
            continue
        share = current / total * 100 if total else None
        rows.append([
            label,
            _format_report_number(current, language),
            _format_report_pct(share, language),
        ])
        seen.add(label)
        if len(rows) >= limit:
            break
    return _table_from_rows(
        table_id,
        caption,
        [labels["line"], labels["amount"], labels["share"]],
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
    revenue_base = None
    for row in source_rows:
        label_lower = str(row.get("label") or "").lower()
        if any(token in label_lower for token in ("выруч", "доход", "revenue")):
            revenue_base = _article_current_amount(row)
            if revenue_base:
                break
    for row in source_rows:
        label = _clean_article_label(row.get("label"))
        if label in seen:
            continue
        pair = _article_amount_pair(row)
        if not pair:
            continue
        current, previous = pair
        change = current - previous
        pct = (change / abs(previous) * 100) if previous else None
        share = (current / revenue_base * 100) if revenue_base else None
        rows.append([
            label,
            _format_report_number(current, language),
            _format_report_number(previous, language),
            _format_report_number(change, language, signed=True),
            _format_report_pct(pct, language, signed=True),
            _format_report_pct(share, language),
        ])
        seen.add(label)
        if len(rows) >= limit:
            break
    return _table_from_rows(
        "income_statement_horizontal_vertical",
        {
            "ru": "Таблица 5 — Отчёт о финансовых результатах",
            "en": "Table 5 — Income statement",
            "uz": "Jadval 5 — Moliyaviy natijalar hisoboti",
        }.get(_normalize_language(language), "Таблица 5 — Отчёт о финансовых результатах"),
        [labels["line"], labels["current"], labels["previous"], labels["change"], labels["change_pct"], labels["share"]],
        rows,
        source="openinfo_excel.table_rows",
    )


def _ratio_article_table(metrics: dict, ifrs_snapshot: dict, language: str) -> dict | None:
    labels = {
        "ru": ["Показатель", "Значение", "Смысл"],
        "en": ["Metric", "Value", "Meaning"],
        "uz": ["Ko'rsatkich", "Qiymat", "Mazmuni"],
    }.get(_normalize_language(language), ["Показатель", "Значение", "Смысл"])
    metric_rows = []

    def add(label: str, value, meaning: str, pct: bool = False, digits: int = 2):
        if value is None or value == "":
            return
        formatted = _format_report_pct(value, language, digits=digits) if pct else str(value)
        metric_rows.append([label, formatted, meaning])

    quality = (ifrs_snapshot or {}).get("quality") or {}
    balance = (ifrs_snapshot or {}).get("balance_sheet") or {}
    income = (ifrs_snapshot or {}).get("income_statement") or {}
    bank = (ifrs_snapshot or {}).get("bank") or {}
    total_score = (metrics or {}).get("total_score") or {}
    add("Итоговый скоринг", total_score.get("score"), total_score.get("summary") or total_score.get("grade") or "Сводная оценка качества отчётности")
    add("ROE", quality.get("roe_pct"), "Доходность собственного капитала", pct=True)
    add("ROA", quality.get("roa_pct"), "Прибыль на активы", pct=True)
    add("Чистая маржа", income.get("net_margin_pct"), "Сколько прибыли остаётся с дохода", pct=True)
    add("Текущая ликвидность", balance.get("current_ratio"), "Способность покрывать краткосрочные обязательства")
    add("Долг / капитал", balance.get("debt_to_equity"), "Во сколько раз долг соотносится с собственным капиталом")
    add("Долг / активы", (balance.get("debt_to_assets") or 0) * 100 if balance.get("debt_to_assets") is not None else None, "Доля долга в активах", pct=True)
    add("Покрытие процентов", quality.get("interest_coverage"), "Запас прибыли для выплаты процентов")
    add("CAR simplified", bank.get("car_simple_pct"), "Капитал к активам, приближённая оценка", pct=True)
    add("NIM", bank.get("nim_pct"), "Чистый процентный доход к активам", pct=True)
    add("LDR", bank.get("ldr_pct"), "Кредиты к депозитам", pct=True)
    add("CIR", bank.get("cir_pct"), "Расходы к доходам", pct=True)
    return _table_from_rows(
        "ratio_summary",
        {
            "ru": "Таблица 6 — Сводный коэффициентный профиль",
            "en": "Table 6 — Ratio summary profile",
            "uz": "Jadval 6 — Koeffitsiyentlar profili",
        }.get(_normalize_language(language), "Таблица 6 — Сводный коэффициентный профиль"),
        labels,
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
    liab_v = _vertical_article_table("liabilities_vertical", captions["liab_v"].get(lang, captions["liab_v"]["ru"]), liability_rows, lang, total_hint="итого пассив", fallback_total=total_liabilities)
    income_table = _income_article_table(income_rows, lang)
    ratio_table = _ratio_article_table(metrics or {}, ifrs_snapshot or {}, lang)
    appendix_tables = _excel_appendix_article_tables(company_data, lang)

    def p(text: str) -> dict:
        return {"type": "paragraph", "text": text}

    def t(table: dict | None) -> list[dict]:
        return [{"type": "table", **table}] if table else []

    article_sections = [
        {
            "id": "overview",
            "number": "01",
            "title": {
                "ru": "Общие сведения об эмитенте и методология анализа",
                "en": "Issuer overview and analysis method",
                "uz": "Emitent haqida umumiy ma'lumot va tahlil usuli",
            }.get(lang),
            "blocks": [p(_first_article_paragraph(sections, "ДОСЬЕ") or "Анализ построен на публичной отчётности, расчетных метриках и доступных Excel-раскрытиях эмитента.")],
        },
        {
            "id": "horizontal_balance",
            "number": "02",
            "title": {
                "ru": "Горизонтальный анализ бухгалтерского баланса",
                "en": "Horizontal balance sheet analysis",
                "uz": "Balansning gorizontal tahlili",
            }.get(lang),
            "blocks": [
                *t(assets_h),
                *t(liab_h),
                p(_first_article_paragraph(sections, "ЧТО_С_ДЕНЬГАМИ") or "Горизонтальный анализ показывает изменение ключевых строк между текущим и предыдущим периодом."),
            ],
        },
        {
            "id": "vertical_balance",
            "number": "03",
            "title": {
                "ru": "Вертикальный анализ бухгалтерского баланса",
                "en": "Vertical balance sheet analysis",
                "uz": "Balansning vertikal tahlili",
            }.get(lang),
            "blocks": [
                *t(assets_v),
                *t(liab_v),
                p("Вертикальный анализ показывает, какая часть активов и пассивов приходится на каждую крупную строку отчётности. Это помогает увидеть концентрацию баланса и зависимость от отдельных статей."),
            ],
        },
        {
            "id": "income_statement",
            "number": "04",
            "title": {
                "ru": "Анализ отчёта о финансовых результатах",
                "en": "Income statement analysis",
                "uz": "Moliyaviy natijalar hisoboti tahlili",
            }.get(lang),
            "blocks": [
                *t(income_table),
                p(_first_article_paragraph(sections, "ТРЕНД", "ЧТО_С_ДЕНЬГАМИ") or "Раздел сопоставляет доходы, расходы и прибыльность между периодами."),
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
                *t(ratio_table),
                p(_first_article_paragraph(sections, "ЭФФЕКТИВНОСТЬ", "ОЦЕНКА_ЦЕНЫ") or "Коэффициенты дополняют табличный разбор и показывают прибыльность, устойчивость баланса и качество операционной модели."),
            ],
        },
        {
            "id": "conclusion",
            "number": "07" if appendix_tables else "06",
            "title": {
                "ru": "Итоговая оценка финансового состояния",
                "en": "Final financial condition assessment",
                "uz": "Moliyaviy holat bo'yicha yakuniy baho",
            }.get(lang),
            "blocks": [p(_first_article_paragraph(sections, "ИТОГ", "ВЕРДИКТ") or "Итоговая оценка зависит от качества прибыли, структуры баланса и полноты раскрытых данных.")],
        },
    ]

    if appendix_tables:
        article_sections.insert(
            -1,
            {
                "id": "source_excel_data",
                "number": "06",
                "title": {
                    "ru": "Исходные строки из XLSX-отчётов",
                    "en": "Source rows from XLSX reports",
                    "uz": "XLSX hisobotlaridan manba satrlar",
                }.get(lang),
                "blocks": [{"type": "table", **table} for table in appendix_tables],
            },
        )

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
        "tones": {
            "car_simple_pct": tone(car_simple, 10, 6),        # >10% strong, <6% weak
            "nim_pct": tone(nim, 4, 2),                        # >4% strong
            "ldr_pct": tone(ldr, 70, 95, reverse=True) if ldr is not None and ldr > 100
                       else tone(ldr, 90, 70),                 # 70-95% sweet spot
            "cir_pct": tone(cir, 50, 65, reverse=True),       # <50% strong, >65% weak
        },
        "notes": {
            "car_simple_pct": "Достаточность капитала (equity / активы) — рисково-взвешенный CAR требует RWA, которого нет в публичной отчётности.",
            "nim_pct": "Чистый процентный доход / активы — сколько банк зарабатывает на каждом сум активов.",
            "ldr_pct": "Кредиты / депозиты — насколько активно банк раздаёт собранные деньги.",
            "cir_pct": "Операционные расходы / чистый процентный доход — сколько съедает обслуживание.",
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
Ты — инвестиционный аналитик, который пишет короткую и строгую записку по отчётности.
Твоя задача — не пересказывать данные, а объяснить экономический смысл для инвестора.

Язык ответа: {LANGUAGE_HINTS[lang]['label']}

Жёсткие правила:
{PUBLIC_ANALYSIS_POLICY}

- Use PUBLIC MARKET DATA for quotes, price history, trading volumes, dividends, report documents and Fibonacci levels. If it is not available, say the market data is missing.
- Use EXCEL REPORT SNAPSHOTS when available as direct public report extracts. If Excel rows conflict with API-derived figures, mention the discrepancy instead of hiding it.

- Используй только данные из отчётности, расчётных метрик, IFRS snapshot и PUBLIC MARKET DATA ниже.
- Если чего-то не хватает, прямо скажи "Недостаточно данных".
- Никаких общих фраз, маркетинга, воды, литературных сравнений и лишних вступлений.
- Каждое важное утверждение должно опираться на цифру, динамику или явно названный показатель.
- Сравнивай компанию прежде всего с нормами UZ-рынка, а не с глобальными западными стандартами.
- Сначала прибыльность и качество прибыли, потом ликвидность, затем долговая нагрузка, затем оценка и только потом вывод.
- Техническая секция [ФИБОНАЧЧИ] допускается только если есть реальные рыночные уровни; иначе напиши "Недостаточно рыночных данных".
- Не выдумывай денежный поток, EPS, количество акций или цену, если этих данных нет.

Формат табличного разбора:
- В секциях [ЧТО_С_ДЕНЬГАМИ] и [ТРЕНД] после блока «Кратко» сначала дай одну компактную Markdown-таблицу с реальными строками из отчётности, расчётных метрик или EXCEL REPORT SNAPSHOTS.
- Перед таблицей обязательно поставь подпись отдельной строкой: «Таблица 1 — ...», «Table 1 — ...» или «Jadval 1 — ...» по языку ответа.
- Таблица должна быть обычной Markdown-таблицей через символ |, не HTML.
- После таблицы дай подробный аналитический текст 2-4 абзацами: что именно изменилось, почему это важно, где риск, где положительное исключение.
- Не придумывай строки таблицы. Если чистых строк для таблицы нет, напиши «Недостаточно данных» и сразу переходи к тексту.

Фокус анализа по МСФО:
1) Выручка и её динамика
2) Валовая прибыль и валовая маржа
3) EBIT и операционная маржа
4) Чистая прибыль и чистая маржа
5) Рабочий капитал, текущая ликвидность и денежная позиция
6) Долг, покрытие процентов и устойчивость баланса
7) ROE, ROA и качество роста
8) DCF как одно из подтверждений оценки, а не как единственный аргумент

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

КАЖДАЯ секция должна начинаться со СТРУКТУРИРОВАННОГО блока «Кратко» в строго таком формате:

Кратко
Тон: <позитивный | умеренный | тревожный | критичный | нет_данных>
Скор: <число от 0 до 100>/100   ← только в [СКОРИНГ], в остальных секциях строку Скор пропусти
Плюсы:
- <одно простое предложение с цифрой, понятное девятикласснику>
- <ещё один плюс>
Минусы:
- <один минус простым языком>
- <ещё один минус>
Для тебя: <одна короткая фраза простым языком — что это означает лично для частного инвестора>

После пустой строки — полный текст секции с конкретикой и расчётами.

ЖЁСТКИЕ ПРАВИЛА ДЛЯ блока «Кратко»:
1. В блоке «Кратко» (Тон/Плюсы/Минусы/Для тебя) ЗАПРЕЩЕНЫ голые аббревиатуры: ROE, ROA, EBIT,
   EBITDA, NIM, ЧПД, CIR, LDR, LTD, CAR, D/E, P/E, NPL, FCF, WACC, DCF, DSO, DPO, DIO, CCC.
   Если значение важно — переведи на язык бытовых сравнений ("на каждый сум вложенного
   капитала приносит 28 копеек прибыли"), а не "ROE 27,6%".
   1а. ТАКЖЕ ЗАПРЕЩЕНЫ профессиональные обороты, непонятные обычному человеку — заменяй их
   простыми словами:
   - "покрытие процентов слабое" → "прибыли едва хватает, чтобы платить проценты по долгам";
   - "долг к капиталу 5,45 раза" → "долгов в 5,5 раза больше собственных денег компании";
   - "обязательства 84,5% активов" → "почти 85% всего имущества куплено на чужие/заёмные деньги";
   - "структура пассивов" → "из чего складываются деньги компании: свои или взятые в долг";
   - "операционная прибыль не раскрыта" → "компания не показала, сколько зарабатывает на основной
     работе" (а не сухое "не раскрыта");
   - "ликвидность", "рентабельность", "маржа", "волатильность" — либо замени простыми словами,
     либо сразу поясни в скобках 3-6 слов.
   Любой термин, который не поймёт человек без финансового образования, ЛИБО переводи на бытовой
   язык, ЛИБО не используй в блоке «Кратко» вовсе.
2. Цифры можно — но КАЖДАЯ цифра должна быть в человеческой форме: проценты словами
   ("выросла на 38%"), кратные доходы ("в 4,5 раза больше"), либо суммы в сумах/тыс. сумах
   с переводом ("долг 1,2 трлн сумов — это в 4,5 раза больше собственных денег банка").
3. Плюсы и минусы — по 2-3 пункта. Не больше четырёх. Не повторяй один тезис разными словами.
4. Если данных недостаточно для пункта — пропусти его, а не пиши "нет данных".
5. Строка "Для тебя" — это не рекомендация покупать/продавать. Это краткая интерпретация для
   неопытного инвестора, что эти цифры означают на практике.

Формат ответа:
[СКОРИНГ]
Кратко
Тон: ...
Скор: XX/100
Плюсы:
- ...
- ...
Минусы:
- ...
- ...
Для тебя: ...

Класс: A/B/C/D
Расшифровка: 2-3 коротких предложения с числами для опытного читателя.

[ДОСЬЕ]
Кратко
Тон: ...
Плюсы:
- ...
Минусы:
- ...
Для тебя: ...

3-4 предложения о том, чем зарабатывает компания и какой у неё экономический профиль.

[ЧТО_С_ДЕНЬГАМИ]
Кратко
Тон: ...
Плюсы:
- ...
Минусы:
- ...
Для тебя: ...

Сначала: растёт ли выручка и маржа. Потом: зарабатывает ли компания на операционной
деятельности. Потом: ликвидность, рабочий капитал и долговая нагрузка. Не повторяй мысли.

[ТРЕНД]
Кратко
Тон: ...
Плюсы:
- ...
Минусы:
- ...
Для тебя: ...

Направление по выручке, прибыли, маржам и долгу за 3-5 лет. Если тренд смешанный — так и напиши.

[ЭФФЕКТИВНОСТЬ]
Кратко
Тон: ...
Плюсы:
- ...
Минусы:
- ...
Для тебя: ...

Оборачиваемость: запасы (дни), дебиторка (дни), кредиторка (дни), цикл конвертации денег.
Объясни, как быстро компания превращает товар в деньги. Если данных нет — "Недостаточно данных".

[ТЕХНИЧЕСКИЙ_АНАЛИЗ]
Кратко
Тон: ...
Плюсы:
- ...
Минусы:
- ...
Для тебя: ...

Если есть TECHNICAL INDICATORS: RSI и сигнал, Fibonacci-зона и ближайшие уровни,
объёмы (растут/падают, дивергенция), волатильность. Если данных нет — "Рыночные данные отсутствуют".

[ОЦЕНКА_ЦЕНЫ]
Кратко
Тон: ...
Плюсы:
- ...
Минусы:
- ...
Для тебя: ...

Выглядит ли компания дешёвой или дорогой по DCF (расчёт справедливой стоимости через
дисконтированные денежные потоки) и через сравнение с отраслью. Никакой абстракции без цифр.
Не упоминай Piotroski, Altman, Buffett, Graham.

[КАТАЛИЗАТОРЫ]
Кратко
Тон: ...
Плюсы:
- ...
Минусы:
- ...
Для тебя: ...

2-4 фактических фактора из данных, влияющих на оценку риска. Не прогнозируй будущее.

[СИЛЬНЫЕ_СТОРОНЫ]
Кратко
Тон: позитивный
Плюсы:
- ...
- ...
Минусы:
- (можно пропустить или указать что сильных сторон с минусами не выявлено)
Для тебя: ...

Развёрнутый список сильных сторон с числами и кратким смыслом.

[СЛАБЫЕ_СТОРОНЫ]
Кратко
Тон: тревожный (или критичный — по тяжести)
Плюсы:
- (можно пропустить)
Минусы:
- ...
- ...
Для тебя: ...

Развёрнутый список слабых сторон с числами и кратким смыслом.

[РЫНОЧНЫЕ_ДАННЫЕ]
Кратко
Тон: ...
Плюсы:
- ...
Минусы:
- ...
Для тебя: ...

Публичный контур: котировки, объёмы, облигации, новости, листинг, режимы торгов, тарифы.
По каждому типу: "есть в текущем наборе" / "нет в текущем наборе". Без прогнозов.

[ВЕРДИКТ]
Кратко
Тон: ...
Плюсы:
- ...
Минусы:
- ...
Для тебя: ...

Выбери информационный статус: СИЛЬНАЯ ОТЧЁТНОСТЬ / УМЕРЕННАЯ ОТЧЁТНОСТЬ /
СЛАБАЯ ОТЧЁТНОСТЬ / ПОВЫШЕННЫЙ РИСК / НЕДОСТАТОЧНО ДАННЫХ. Объясни цифрами.
Не давай инвестиционных рекомендаций.

[ОГРАНИЧЕНИЯ_ПУБЛИЧНОГО_КОНТУРА]
Кратко
Тон: нет_данных
Минусы:
- (перечисли отсутствующие категории публичных данных)
Для тебя: ...

Что анализ не содержит: персональные данные, прогнозы, инвест-рекомендации, юридические заключения.
Если каких-то публичных рыночных данных не хватает — перечисли это как ограничение.

[ИТОГ]
Кратко
Тон: ...
Плюсы:
- (главные плюсы простыми словами)
Минусы:
- (главные минусы простыми словами)
Для тебя: ...

ХЕРО-АБЗАЦ ДЛЯ НОВИЧКА (4-6 предложений). Пиши так, как будто объясняешь школьнику 9 класса,
который никогда не слышал слов ROE, EBITDA, маржа. Ни одного финансового термина без перевода.
Не превращай в инвестиционную рекомендацию. Финал — одно предложение
"стоит ли вкладываться обычному частному инвестору и почему".
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
        "Сразу после метки секции — СТРУКТУРИРОВАННЫЙ блок «Кратко» строго в формате:\n"
        "    Кратко\n"
        "    Тон: <позитивный | умеренный | тревожный | критичный | нет_данных>\n"
        "    Скор: XX/100   (только в секции [СКОРИНГ])\n"
        "    Плюсы:\n"
        "    - простое предложение с цифрой\n"
        "    - ещё один плюс\n"
        "    Минусы:\n"
        "    - один минус простым языком\n"
        "    - ещё один\n"
        "    Для тебя: одна короткая фраза простым языком\n"
        "    (пустая строка)\n"
        "    <дальше — обычный текст секции с конкретикой>.\n"
        "🚨 КРИТИЧНО ВАЖНО: каждая строка блока «Кратко» — на ОТДЕЛЬНОЙ строке, с реальным "
        "переводом строки (символ \\n). Не сжимай «Кратко» в один абзац. Не пиши "
        "'Кратко Тон: ... Плюсы: - ... Минусы: - ... Для тебя: ...' одной строкой. "
        "Слова 'Тон', 'Плюсы', 'Минусы', 'Для тебя' начинают каждая свою строку. "
        "Каждый bullet (- ...) — тоже на отдельной строке. "
        "После строки 'Для тебя: ...' — ПУСТАЯ СТРОКА, и только потом обычный текст секции.\n"
        "В секциях [ЧТО_С_ДЕНЬГАМИ] и [ТРЕНД] после блока «Кратко» и перед обычным текстом "
        "обязательно поставь report-style Markdown-таблицу с подписью 'Таблица ...' / 'Table ...' / 'Jadval ...', "
        "если в переданных данных есть реальные строки для такой таблицы. Таблица строится только из переданных "
        "IFRS snapshot, расчётных метрик или EXCEL REPORT SNAPSHOTS; строки и цифры не выдумывать. "
        "После таблицы пиши подробный аналитический текст 2-4 абзацами, как в финансовой записке.\n"
        "В блоке «Кратко» (Тон/Плюсы/Минусы/Для тебя) КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНЫ голые "
        "аббревиатуры: ROE, ROA, EBIT, EBITDA, NIM, ЧПД, CIR, LDR, LTD, CAR, D/E, P/E, "
        "NPL, FCF, WACC, DCF, DSO, DPO, DIO, CCC. "
        "Объясняй смысл словами для девятиклассника: например, не 'ROE 27,6%', а "
        "'на каждый сум собственных денег банк зарабатывает 28 копеек прибыли'. "
        "Не 'D/E 4,56', а 'долгов в 4,5 раза больше собственного капитала'. "
        "Не 'CIR 71%', а 'на каждый заработанный сум банк тратит 71 копейку на свою работу'. "
        "Так же поступай с профессиональными оборотами: не 'покрытие процентов слабое', а "
        "'прибыли едва хватает, чтобы платить проценты по долгам'; не 'обязательства 84,5% "
        "активов', а 'почти 85% имущества куплено на заёмные деньги'; не 'операционная прибыль "
        "не раскрыта', а 'компания не показала, сколько зарабатывает на основной работе'. "
        "Любой термин, непонятный человеку без финансового образования, в блоке «Кратко» либо "
        "переводи на бытовой язык, либо не используй вовсе. "
        "В основном тексте секции (после пустой строки) термины допустимы, но при первом "
        "упоминании дай пояснение в скобках 3-7 слов: 'ROE 27% (доходность на каждый сум "
        "собственного капитала)'. "
        "Не используй markdown заголовки (##). Не пропускай ни одну секцию. "
        "Не повторяй один и тот же тезис дважды разными словами. "
        "Если данных недостаточно — напиши 'Недостаточно данных' внутри секции, но секцию не пропускай. "
        "НЕ упоминай Piotroski F-Score, Altman Z-Score, Buffett-критерии, число Грэма — "
        "эти модели в отчёте пользователю не показываются. "
        "В секции [ИТОГ] после блока «Кратко» обязателен ХЕРО-АБЗАЦ для новичка: 4-6 предложений "
        "простым языком, без единого финансового термина без перевода, последняя фраза — "
        "одно предложение 'стоит ли вкладываться обычному частному инвестору и почему'. "
        f"{_language_hint(lang, 'analysis')}"
    )
    # Tables add some output length, but the report still stays compact.
    raw, response = _responses_text(prompt, instructions, max_output_tokens=6500)

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

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
ARTICLE_REPORT_VERSION = "article-report-v4"
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


def _table_explanation_blocks(table: dict | None, role: str, language: str) -> list[dict]:
    if not table:
        return []
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
    liab_v = _vertical_article_table("liabilities_vertical", captions["liab_v"].get(lang, captions["liab_v"]["ru"]), liability_rows, lang, total_hint="итого пассив", fallback_total=total_liabilities)
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
    appendix_tables = _excel_appendix_article_tables(company_data, lang)

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
                *t(assets_h, "assets_horizontal"),
                *t(liab_h, "liabilities_horizontal"),
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
                *t(assets_v, "assets_vertical"),
                *t(liab_v, "liabilities_vertical"),
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
                *t(income_table, "income_statement"),
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
                *t(ratio_table, "ratio_summary"),
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
                "blocks": [
                    block
                    for table in appendix_tables
                    for block in _table_with_explanation(table, "excel_source", lang)
                ],
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

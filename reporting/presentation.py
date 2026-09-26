"""Report number formatting and structured Markdown table construction."""

from __future__ import annotations
from reporting.localization import _normalize_language
from reporting.numbers import _safe_float


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


def _table_from_rows(
    table_id: str,
    caption: str,
    headers: list[str],
    rows: list[list[str]],
    *,
    source: str,
    source_labels: list[str] | None = None,
) -> dict | None:
    if not rows:
        return None
    markdown = _markdown_table(caption, headers, rows)
    table = {
        "id": table_id,
        "caption": caption,
        "headers": headers,
        "rows": rows,
        "markdown": markdown,
        "source": source,
    }
    if source_labels:
        table["_source_labels"] = source_labels[:len(rows)]
    return table

"""Resolve filing dates and select comparable reporting periods."""

from __future__ import annotations
import re
from reporting.article.rows import (
    _article_amount_cells,
    _article_report_has_meaningful_data,
    _article_report_rows,
)
from reporting.localization import _normalize_language
from reporting.numbers import _safe_float


def _parse_report_date_parts(value) -> tuple[int, int, int] | None:
    text = str(value or "")
    match = re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})", text)
    if match:
        year, month, day = (int(part) for part in match.groups())
    else:
        match = re.search(r"(\d{1,2})[./](\d{1,2})[./](\d{4})", text)
        if not match:
            return None
        day, month, year = (int(part) for part in match.groups())
    if 1900 <= year <= 2100 and 1 <= month <= 12 and 1 <= day <= 31:
        return year, month, day
    return None


def _format_report_date_label(year: int | None, month: int | None, day: int | None) -> str:
    if not year or not month or not day:
        return ""
    return f"{int(day):02d}.{int(month):02d}.{int(year):04d}"


def _format_report_date_iso(year: int | None, month: int | None, day: int | None) -> str:
    if not year or not month or not day:
        return ""
    return f"{int(year):04d}-{int(month):02d}-{int(day):02d}"


def _quarter_end_date(year: int | None, quarter: int | None) -> tuple[int, int, int] | None:
    if not year or quarter not in {1, 2, 3, 4}:
        return None
    month = {1: 3, 2: 6, 3: 9, 4: 12}[int(quarter)]
    day = 30 if quarter in {2, 3} else 31
    return int(year), month, day


def _article_report_metadata_value(rows: list[dict], report_index: int | None, key: str):
    for row in _article_report_rows(rows, report_index):
        value = row.get(key)
        if value not in (None, ""):
            return value
    return None


def _article_report_value_candidates(row: dict) -> list[float]:
    values = [cell["value"] for cell in _article_amount_cells(row)]
    for value in row.get("values") or []:
        parsed = _safe_float(value)
        if parsed is not None:
            values.append(parsed)
    return values


def _article_report_explicit_quarter(rows: list[dict], report_index: int | None) -> int | None:
    quarter_label_tokens = (
        "период квартала",
        "номер квартала",
        "quarter period",
        "quarter number",
    )
    for row in _article_report_rows(rows, report_index):
        label = str(row.get("label") or "").lower()
        if any(token in label for token in quarter_label_tokens):
            for value in _article_report_value_candidates(row):
                rounded = int(round(value))
                if 1 <= rounded <= 4 and abs(value - rounded) < 0.01:
                    return rounded
        match = re.search(r"\b(?:q|quarter|квартал)\s*([1-4])\b|\b([1-4])\s*(?:q|quarter|квартал)", label)
        if match:
            return int(match.group(1) or match.group(2))

    title = str(_article_report_metadata_value(rows, report_index, "title") or "").lower()
    match = re.search(r"\b(?:q|quarter|квартал)\s*([1-4])\b|\b([1-4])\s*(?:q|quarter|квартал)", title)
    if match:
        return int(match.group(1) or match.group(2))
    return None


def _article_year_from_published_quarter(year: int, month: int, quarter: int) -> int:
    if int(quarter) == 4 and int(month) <= 3:
        return int(year) - 1
    return int(year)


def _article_report_reporting_date(rows: list[dict], report_index: int | None) -> str:
    for row in _article_report_rows(rows, report_index):
        parts = _parse_report_date_parts(row.get("reporting_date"))
        if parts:
            return _format_report_date_iso(*parts)
    for row in _article_report_rows(rows, report_index):
        label = str(row.get("label") or "").lower()
        if not any(token in label for token in (
            "дата отчетности",
            "отчетная дата",
            "дата отчета",
            "reporting date",
            "date of report",
            "report date",
        )):
            continue
        values = [row.get("label"), *(row.get("values") or [])]
        for value in values:
            parts = _parse_report_date_parts(value)
            if parts:
                return _format_report_date_iso(*parts)
    return ""


def _article_report_published_date(rows: list[dict], report_index: int | None) -> str:
    for row in _article_report_rows(rows, report_index):
        parts = _parse_report_date_parts(row.get("published_at"))
        if parts:
            return _format_report_date_iso(*parts)
    return ""


def _normalize_article_period_type(value) -> str:
    text = str(value or "").strip().lower()
    if "quarter" in text or text in {"q", "quarterly"}:
        return "quarterly"
    if "annual" in text or text in {"year", "yearly"}:
        return "annual"
    return ""


def _article_quarter_from_reporting_month(month: int | None) -> int | None:
    return {3: 1, 6: 2, 9: 3, 12: 4}.get(int(month or 0))


def _article_quarter_from_published_date(year: int, month: int) -> tuple[int, int]:
    if 4 <= month <= 6:
        return year, 1
    if 7 <= month <= 9:
        return year, 2
    if 10 <= month <= 12:
        return year, 3
    return year - 1, 4


def _article_report_period_info(rows: list[dict], report_index: int) -> dict:
    raw_type = _normalize_article_period_type(_article_report_metadata_value(rows, report_index, "period_type"))
    reporting_date = _article_report_reporting_date(rows, report_index)
    published_date = _article_report_published_date(rows, report_index)
    reporting_parts = _parse_report_date_parts(reporting_date)
    published_parts = _parse_report_date_parts(published_date)
    explicit_quarter = _article_report_explicit_quarter(rows, report_index)

    period_type = raw_type
    if not period_type and reporting_parts:
        period_type = "annual" if reporting_parts[1] == 12 else "quarterly"

    year = None
    quarter = None
    label = ""
    if period_type == "quarterly":
        if reporting_parts:
            report_quarter = _article_quarter_from_reporting_month(reporting_parts[1])
            if report_quarter:
                year = reporting_parts[0]
                quarter = report_quarter
        if (not year or not quarter) and explicit_quarter:
            quarter = explicit_quarter
            if reporting_parts:
                year = reporting_parts[0]
            elif published_parts:
                year = _article_year_from_published_quarter(published_parts[0], published_parts[1], quarter)
        if (not year or not quarter) and published_parts:
            year, quarter = _article_quarter_from_published_date(published_parts[0], published_parts[1])
        if year and quarter:
            end_date = _quarter_end_date(year, quarter)
            label = _format_report_date_label(*(end_date or (None, None, None)))
    elif period_type == "annual":
        if reporting_parts and reporting_parts[1] == 12:
            year = reporting_parts[0]
        elif published_parts:
            year = published_parts[0] - 1
        if year:
            label = _format_report_date_label(year, 12, 31)

    if not label and reporting_parts:
        label = _format_report_date_label(*reporting_parts)
    if not label and published_parts:
        label = _format_report_date_label(*published_parts)

    return {
        "index": int(report_index),
        "period_type": period_type or "unknown",
        "year": year,
        "quarter": quarter,
        "label": label,
        "display": f"Q{quarter} {year}" if period_type == "quarterly" and year and quarter else (str(year) if period_type == "annual" and year else label),
        "reporting_date": reporting_date,
        "published_at": published_date,
        "sort_value": reporting_date or published_date or f"report:{report_index}",
        "has_data": _article_report_has_meaningful_data(rows, report_index),
    }


def _article_available_period_summary(infos: list[dict], language: str = "ru") -> dict:
    lang = _normalize_language(language)
    quarterly = sorted(
        {
            f"Q{info.get('quarter')} {info.get('year')}"
            for info in infos
            if info.get("period_type") == "quarterly" and info.get("year") and info.get("quarter") and info.get("has_data")
        },
        key=lambda value: (
            int(value.split()[1]) if len(value.split()) > 1 else 0,
            int(value[1]) if value.startswith("Q") and value[1].isdigit() else 0,
        ),
        reverse=True,
    )
    annual = sorted(
        {
            str(info.get("year"))
            for info in infos
            if info.get("period_type") == "annual" and info.get("year") and info.get("has_data")
        },
        reverse=True,
    )
    if lang == "en":
        parts = []
        if quarterly:
            parts.append(f"quarterly: {', '.join(quarterly)}")
        if annual:
            parts.append(f"annual: {', '.join(annual)}")
        text = "Available periods: " + ("; ".join(parts) if parts else "none")
    elif lang == "uz":
        parts = []
        if quarterly:
            parts.append(f"choraklik: {', '.join(quarterly)}")
        if annual:
            parts.append(f"yillik: {', '.join(annual)}")
        text = "Mavjud davrlar: " + ("; ".join(parts) if parts else "yo'q")
    else:
        parts = []
        if quarterly:
            parts.append(f"квартальные: {', '.join(quarterly)}")
        if annual:
            parts.append(f"годовые: {', '.join(annual)}")
        text = "Доступные периоды: " + ("; ".join(parts) if parts else "нет")
    return {"text": text, "quarterly": quarterly, "annual": annual}


def _article_comparison_selection_label(current: dict, previous: dict, language: str = "ru") -> str:
    lang = _normalize_language(language)
    current_display = current.get("display") or current.get("label") or ""
    previous_display = previous.get("display") or previous.get("label") or ""
    joiner = " vs " if lang == "en" else " ga " if lang == "uz" else " к "
    return f"{current_display}{joiner}{previous_display}".strip()


def _select_article_comparison_indices(
    excel_rows: list[dict],
    report_comparison: dict | None,
    language: str = "ru",
) -> dict:
    lang = _normalize_language(language)
    comparison = report_comparison or {}
    mode = comparison.get("mode") or "latest"
    infos = [_article_report_period_info(excel_rows, index) for index in _article_report_indices(excel_rows)]
    available = _article_available_period_summary(infos, lang)
    base = {
        "mode": mode,
        "current_index": None,
        "previous_index": None,
        "force_previous_row": False,
        "available_periods": available,
    }
    if mode == "latest":
        return base

    if not infos:
        form = comparison.get("report_form") or "MSFO"
        form_label = {"MSFO": "МСФО", "NSBU": "НСБУ", "Audition": "аудиторское заключение"}.get(form, form)
        if lang == "en":
            form_label_en = {"MSFO": "IFRS", "NSBU": "NAS", "Audition": "Auditor's Report"}.get(form, form)
            raise ValueError(f"The {form_label_en} report for the selected period was not found. The company may not have published this type of report for that period.")
        if lang == "uz":
            form_label_uz = {"MSFO": "MXHS", "NSBU": "MHBS", "Audition": "auditorlik xulosasi"}.get(form, form)
            raise ValueError(f"Tanlangan davr uchun {form_label_uz} hisoboti topilmadi. Kompaniya ushbu turdagi hisobotni nashr etmagan bo'lishi mumkin.")
        raise ValueError(f"Отчёт по форме «{form_label}» за выбранный период не найден. Компания могла не публиковать данный тип отчёта за этот период.")

    def find_info(year: int | None, quarter: int | None = None) -> dict | None:
        for info in infos:
            if not info.get("has_data"):
                continue
            if int(info.get("year") or 0) != int(year or 0):
                continue
            if mode == "quarterly":
                if info.get("period_type") == "quarterly" and int(info.get("quarter") or 0) == int(quarter or 0):
                    return info
            elif mode == "annual" and info.get("period_type") == "annual":
                return info
        return None

    current_year = comparison.get("current_year")
    previous_year = comparison.get("previous_year")
    quarter = comparison.get("quarter")
    current = find_info(current_year, quarter)
    previous = find_info(previous_year, quarter)
    if current and previous:
        label = _article_comparison_selection_label(current, previous, lang)
        mode_label = {"quarterly": "quarterly", "annual": "annual"}[mode]
        if lang == "ru":
            mode_label = "квартальное" if mode == "quarterly" else "годовое"
            description = f"Режим анализа: {mode_label} сравнение {label}. Основные таблицы берут данные только из выбранных XLSX-отчётов."
        elif lang == "uz":
            mode_label = "choraklik" if mode == "quarterly" else "yillik"
            description = f"Tahlil rejimi: {mode_label} taqqoslash {label}. Asosiy jadvallar faqat tanlangan XLSX hisobotlaridan olinadi."
        else:
            description = f"Analysis mode: {mode_label} comparison {label}. Main tables use only the selected XLSX reports."
        return {
            **base,
            "current_index": current["index"],
            "previous_index": previous["index"],
            "current_label": current.get("label"),
            "previous_label": previous.get("label"),
            "label": label,
            "force_previous_row": True,
            "description": description,
            "current_report": current,
            "previous_report": previous,
        }

    if mode == "quarterly":
        requested_current = f"Q{quarter} {current_year}"
        requested_previous = f"Q{quarter} {previous_year}"
    else:
        requested_current = str(current_year)
        requested_previous = str(previous_year)
    missing = [
        value
        for value, found in ((requested_current, current), (requested_previous, previous))
        if not found
    ]
    form = comparison.get("report_form") or "MSFO"
    if lang == "en":
        form_label_en = {"MSFO": "IFRS", "NSBU": "NAS", "Audition": "Auditor's Report"}.get(form, form)
        raise ValueError(f"The {form_label_en} report for {', '.join(missing)} was not found. The company may not have published this type of report for that period. {available['text']}")
    if lang == "uz":
        form_label_uz = {"MSFO": "MXHS", "NSBU": "MHBS", "Audition": "auditorlik xulosasi"}.get(form, form)
        raise ValueError(f"{form_label_uz} hisoboti {', '.join(missing)} uchun topilmadi. Kompaniya ushbu turdagi hisobotni nashr etmagan bo'lishi mumkin. {available['text']}")
    form_label_ru = {"MSFO": "МСФО", "NSBU": "НСБУ", "Audition": "аудиторское заключение"}.get(form, form)
    raise ValueError(f"Отчёт по форме «{form_label_ru}» за {', '.join(missing)} не найден. Компания могла не публиковать данный тип отчёта за этот период. {available['text']}")


def _article_report_sort_value(rows: list[dict], report_index: int) -> str:
    return _article_report_reporting_date(rows, report_index) or _article_report_published_date(rows, report_index)


def _article_report_period_label(rows: list[dict], report_index: int, fallback: str) -> str:
    info = _article_report_period_info(rows, report_index)
    if info.get("label"):
        return str(info["label"])
    value = _article_report_sort_value(rows, report_index)
    parts = _parse_report_date_parts(value)
    if parts:
        return _format_report_date_label(*parts)
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

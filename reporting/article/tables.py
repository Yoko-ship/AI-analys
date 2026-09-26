"""Build balance, income, trend, and source appendix tables from filings."""

from __future__ import annotations
import re
from reporting.article.labels import (
    _article_display_label,
    _clean_article_label,
    _normalize_article_label_key,
)
from reporting.article.periods import (
    _article_previous_balance_period_label,
    _article_report_indices,
    _article_report_period_label,
    _article_report_sort_value,
)
from reporting.article.rows import (
    _article_amount_cells,
    _article_amount_is_zero,
    _article_amount_pair,
    _article_current_amount,
    _article_current_previous_amounts,
    _article_is_zero_noise,
    _article_matching_row,
    _article_report_has_current_data,
    _article_row_lookup,
    _article_rows_for_report,
    _article_supplemental_entries,
    _normalized_article_entries,
)
from reporting.article.signals import _format_bln_sum_from_thousand
from reporting.localization import _normalize_language
from reporting.numbers import _safe_float
from reporting.presentation import (
    _format_report_number,
    _format_report_pct,
    _report_table_labels,
    _table_from_rows,
)
from reporting.settings import (
    ARTICLE_ANALYSIS_ROW_LIMIT,
    ARTICLE_EXCEL_APPENDIX_MAX_COLUMNS,
    ARTICLE_EXCEL_APPENDIX_MAX_ROWS,
    ARTICLE_EXCEL_APPENDIX_MAX_TABLES,
)


def _article_report_indices_with_current_data(rows: list[dict], table_id: str) -> list[int]:
    return [
        index
        for index in _article_report_indices(rows)
        if _article_report_has_current_data(table_id, _article_rows_for_report(rows, index))
    ]


def _article_current_previous_report_indices(rows: list[dict], table_id: str) -> tuple[int | None, int | None]:
    valid_indices = _article_report_indices_with_current_data(rows, table_id)
    indices = valid_indices or _article_report_indices(rows)
    current_index = indices[0] if indices else None
    previous_index = indices[1] if len(indices) > 1 else None
    return current_index, previous_index


def _horizontal_article_table(
    table_id: str,
    caption: str,
    source_rows: list[dict],
    language: str,
    *,
    limit: int = ARTICLE_ANALYSIS_ROW_LIMIT,
    forced_current_index: int | None = None,
    forced_previous_index: int | None = None,
    force_previous_row: bool = False,
) -> dict | None:
    labels = _report_table_labels(language)
    rows = []
    source_labels: list[str] = []
    seen = set()
    if forced_current_index is not None:
        current_index = forced_current_index
        previous_index = forced_previous_index
    else:
        current_index, previous_index = _article_current_previous_report_indices(source_rows, table_id)
    current_rows = _article_rows_for_report(source_rows, current_index) or source_rows
    previous_lookup = _article_row_lookup(_article_rows_for_report(source_rows, previous_index))
    current_label = _article_report_period_label(source_rows, current_index, labels["current"]) if current_index is not None else labels["current"]
    previous_label = _article_report_period_label(source_rows, previous_index, labels["previous"]) if previous_index is not None else labels["previous"]
    if not force_previous_row and any(_article_amount_pair(row) for row in current_rows):
        previous_label = _article_previous_balance_period_label(current_label, previous_label)

    normalized_entries = _normalized_article_entries(
        table_id,
        current_rows,
        previous_lookup,
        force_previous_row=force_previous_row,
    )
    if normalized_entries:
        row_source = list(normalized_entries)
        row_source.extend(_article_supplemental_entries(
            current_rows,
            previous_lookup,
            row_source,
            max(0, limit - len(row_source)),
            force_previous_row=force_previous_row,
        ))
    else:
        row_source = []
        for row in current_rows:
            label = _clean_article_label(row.get("label"))
            if label in seen:
                continue
            previous_row = _article_matching_row(row, previous_lookup)
            current, previous = _article_current_previous_amounts(
                row,
                previous_row,
                force_previous_row=force_previous_row,
            )
            if current is None or _article_is_zero_noise(label, current, previous):
                continue
            row_source.append({"label": label, "current": current, "previous": previous})
            seen.add(label)
            if len(row_source) >= limit:
                break

    for entry in row_source:
        source_label = _clean_article_label(entry.get("label"))
        label = _article_display_label(source_label, language)
        current = entry.get("current")
        previous = entry.get("previous")
        if current is None:
            continue
        change = current - previous if previous is not None else None
        pct = (change / abs(previous) * 100) if previous not in (None, 0) and change is not None else None
        source_labels.append(source_label)
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
        source_labels=source_labels,
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
    forced_current_index: int | None = None,
    forced_previous_index: int | None = None,
    force_previous_row: bool = False,
) -> dict | None:
    labels = _report_table_labels(language)
    if forced_current_index is not None:
        current_index = forced_current_index
        previous_index = forced_previous_index
    else:
        current_index, previous_index = _article_current_previous_report_indices(source_rows, table_id)
    current_rows = _article_rows_for_report(source_rows, current_index) or source_rows
    previous_rows = _article_rows_for_report(source_rows, previous_index)
    previous_lookup = _article_row_lookup(previous_rows)
    current_label = _article_report_period_label(source_rows, current_index, labels["current"]) if current_index is not None else labels["current"]
    previous_label = _article_report_period_label(source_rows, previous_index, labels["previous"]) if previous_index is not None else labels["previous"]
    if not force_previous_row and any(_article_amount_pair(row) for row in current_rows):
        previous_label = _article_previous_balance_period_label(current_label, previous_label)

    total = fallback_total
    previous_total = None
    for row in current_rows:
        label = str(row.get("label") or "").lower()
        if total_hint in label:
            total = _article_current_amount(row)
            previous_row = _article_matching_row(row, previous_lookup)
            _, previous_total = _article_current_previous_amounts(
                row,
                previous_row,
                force_previous_row=force_previous_row,
            )
            break
    if not total:
        return None

    rows = []
    source_labels: list[str] = []
    seen = set()
    display_scale = 1000 if abs(total) >= 10_000_000 else 1
    normalized_entries = _normalized_article_entries(
        table_id,
        current_rows,
        previous_lookup,
        force_previous_row=force_previous_row,
    )
    if normalized_entries:
        row_source = list(normalized_entries)
        row_source.extend(_article_supplemental_entries(
            current_rows,
            previous_lookup,
            row_source,
            max(0, limit - len(row_source)),
            force_previous_row=force_previous_row,
        ))
    else:
        row_source = []
        for row in current_rows:
            label = _clean_article_label(row.get("label"))
            if label in seen:
                continue
            previous_row = _article_matching_row(row, previous_lookup)
            current, previous = _article_current_previous_amounts(
                row,
                previous_row,
                force_previous_row=force_previous_row,
            )
            if current is None or _article_is_zero_noise(label, current, previous):
                continue
            row_source.append({"label": label, "current": current, "previous": previous})
            seen.add(label)
            if len(row_source) >= limit:
                break

    for entry in row_source:
        source_label = _clean_article_label(entry.get("label"))
        label = _article_display_label(source_label, language)
        current = entry.get("current")
        previous = entry.get("previous")
        if current is None:
            continue
        share = current / total * 100 if total else None
        previous_share = previous / previous_total * 100 if previous is not None and previous_total else None
        source_labels.append(source_label)
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
        source_labels=source_labels,
    )


def _income_article_table(
    source_rows: list[dict],
    language: str,
    *,
    limit: int = ARTICLE_ANALYSIS_ROW_LIMIT,
    forced_current_index: int | None = None,
    forced_previous_index: int | None = None,
    force_previous_row: bool = False,
) -> dict | None:
    labels = _report_table_labels(language)
    rows = []
    source_labels: list[str] = []
    seen = set()
    if forced_current_index is not None:
        current_index = forced_current_index
        previous_index = forced_previous_index
    else:
        current_index, previous_index = _article_current_previous_report_indices(source_rows, "income_statement_horizontal_vertical")
    current_rows = _article_rows_for_report(source_rows, current_index) or source_rows
    previous_lookup = _article_row_lookup(_article_rows_for_report(source_rows, previous_index))
    current_label = _article_report_period_label(source_rows, current_index, labels["current"]) if current_index is not None else labels["current"]
    previous_label = _article_report_period_label(source_rows, previous_index, labels["previous"]) if previous_index is not None else labels["previous"]

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

    normalized_entries = _normalized_article_entries(
        "income_statement_horizontal_vertical",
        current_rows,
        previous_lookup,
        force_previous_row=force_previous_row,
    )
    if normalized_entries:
        row_source = list(normalized_entries)
        row_source.extend(_article_supplemental_entries(
            current_rows,
            previous_lookup,
            row_source,
            max(0, limit - len(row_source)),
            force_previous_row=force_previous_row,
        ))
    else:
        row_source = []
        for row in current_rows:
            label = _clean_article_label(row.get("label"))
            if label in seen:
                continue
            previous_row = _article_matching_row(row, previous_lookup)
            current, previous = _article_current_previous_amounts(
                row,
                previous_row,
                force_previous_row=force_previous_row,
            )
            if current is None or _article_is_zero_noise(label, current, previous):
                continue
            row_source.append({"label": label, "current": current, "previous": previous})
            seen.add(label)
            if len(row_source) >= limit:
                break

    for entry in row_source:
        source_label = _clean_article_label(entry.get("label"))
        label = _article_display_label(source_label, language)
        current = entry.get("current")
        previous = entry.get("previous")
        if current is None:
            continue
        label_lower = source_label.lower()
        if "отчет о финансовых результатах" in label_lower:
            continue
        pct_interest = (abs(current) / interest_income_base * 100) if interest_income_base else None
        pct_total = None
        if total_income_base and any(token in label_lower for token in ("доход", "прибыль")):
            pct_total = abs(current) / total_income_base * 100
        if operating_expense_base and any(token in label_lower for token in ("заработ", "аренда", "административ", "износ", "страхование", "налог")):
            pct_total = abs(current) / operating_expense_base * 100
        change = current - previous if previous is not None else None
        pct_change = (change / abs(previous) * 100) if previous not in (None, 0) and change is not None else None
        source_labels.append(source_label)
        rows.append([
            label,
            _format_report_number(current, language),
            _format_report_number(previous, language) if previous is not None else "—",
            _format_report_number(change, language, signed=True),
            _format_report_pct(pct_change, language, signed=True),
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
        [
            labels["line"],
            current_label,
            previous_label,
            labels["change"],
            labels["change_pct"],
            {
                "ru": "% от проц. дох.",
                "en": "% of interest income",
                "uz": "Foiz daromadidan %",
            }.get(_normalize_language(language), "% of interest income"),
            {
                "ru": "% от сов. дох.",
                "en": "% of total income",
                "uz": "Jami daromaddan %",
            }.get(_normalize_language(language), "% of total income"),
        ],
        rows,
        source="openinfo_excel.table_rows",
        source_labels=source_labels,
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
    if max_tables <= 0 or max_rows <= 0:
        return []

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


def _article_period_group_label(sort_value: str, fallback: str) -> str:
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(sort_value or "")):
        year, month, day = str(sort_value).split("-")
        return f"{day}.{month}.{year}"
    return fallback


def _article_period_groups(rows: list[dict], limit: int = 6) -> list[dict]:
    groups: dict[str, dict] = {}
    for index in _article_report_indices(rows):
        report_rows = _article_rows_for_report(rows, index)
        if not report_rows:
            continue
        sort_value = _article_report_sort_value(rows, index)
        key = sort_value or f"report:{index}"
        group = groups.setdefault(key, {"sort_value": sort_value, "indices": [], "rows": []})
        group["indices"].append(index)
        group["rows"].extend(report_rows)
    ordered = sorted(groups.values(), key=lambda group: group.get("sort_value") or "", reverse=True)
    return ordered[:limit]


def _article_entry_current_value(entries: list[dict], *keywords: str, last: bool = False) -> float | None:
    if not entries:
        return None
    normalized_keywords = [_normalize_article_label_key(keyword) for keyword in keywords]
    source = reversed(entries) if last else entries
    for entry in source:
        label = str(entry.get("label") or "").lower()
        normalized = _normalize_article_label_key(label)
        matched = True
        for keyword, normalized_keyword in zip(keywords, normalized_keywords):
            lowered_keyword = str(keyword or "").lower()
            if lowered_keyword not in label and normalized_keyword not in normalized:
                matched = False
                break
        if matched:
            return _safe_float(entry.get("current"))
    return None


def _format_article_trend_money(value: float | None, language: str) -> str:
    if value is None:
        return "—"
    formatted = _format_bln_sum_from_thousand(value, language)
    for suffix in (" млрд сум", " bln UZS", " mlrd so'm"):
        if formatted.endswith(suffix):
            return formatted[: -len(suffix)]
    return formatted


def _article_trend_point_from_rows(period_rows: list[dict]) -> dict | None:
    asset_rows = [row for row in period_rows if row.get("article_kind") == "assets"]
    liability_rows = [row for row in period_rows if row.get("article_kind") == "liabilities_equity"]
    income_rows = [row for row in period_rows if row.get("article_kind") == "income_statement"]
    asset_entries = (
        _normalized_article_entries("assets_horizontal", asset_rows, {})
        if _article_report_has_current_data("assets_horizontal", asset_rows)
        else []
    )
    liability_entries = (
        _normalized_article_entries("liabilities_horizontal", liability_rows, {})
        if _article_report_has_current_data("liabilities_horizontal", liability_rows)
        else []
    )
    income_entries = (
        _normalized_article_entries("income_statement_horizontal_vertical", income_rows, {})
        if _article_report_has_current_data("income_statement_horizontal_vertical", income_rows)
        else []
    )

    assets_total = _article_entry_current_value(asset_entries, "итого актив")
    cash = _article_entry_current_value(asset_entries, "касса")
    cbu = _article_entry_current_value(asset_entries, "цбру")
    loans_net = _article_entry_current_value(asset_entries, "кредит", "лизинг", "нетто")
    if loans_net is None:
        loans_net = _article_entry_current_value(asset_entries, "кредит", "лизинг")
    gross_loans = _article_entry_current_value(asset_entries, "брутто", "кредит")
    reserve_loans = _article_entry_current_value(asset_entries, "резерв", "потер")
    deposits = _article_entry_current_value(liability_entries, "клиентские депозиты")
    equity = _article_entry_current_value(liability_entries, "итого собственного капитала")
    interest_income = _article_entry_current_value(income_entries, "итого процентных доход")
    interest_expense = _article_entry_current_value(income_entries, "итого процентных расход")
    non_interest_income = _article_entry_current_value(income_entries, "итого беспроцентных доход")
    operating_expenses = _article_entry_current_value(income_entries, "итого операционных расход")
    pre_operating_income = _article_entry_current_value(income_entries, "чистый доход до операционных расходов")
    net_profit = _article_entry_current_value(income_entries, "чистая прибыль", last=True)

    if not any(not _article_amount_is_zero(value) for value in (assets_total, deposits, loans_net, equity, net_profit)):
        return None
    return {
        "assets_total": assets_total,
        "deposits": deposits,
        "loans_net": loans_net,
        "equity": equity,
        "net_profit": net_profit,
        "first_line_pct": ((cash or 0.0) + (cbu or 0.0)) / assets_total * 100 if assets_total and (cash is not None or cbu is not None) else None,
        "ldr_pct": loans_net / deposits * 100 if loans_net is not None and deposits else None,
        "capital_assets_pct": equity / assets_total * 100 if equity is not None and assets_total else None,
        "reserve_coverage_pct": abs(reserve_loans) / gross_loans * 100 if reserve_loans is not None and gross_loans else None,
        "interest_coverage": interest_income / abs(interest_expense) if interest_income is not None and interest_expense else None,
        "non_interest_share_pct": (
            non_interest_income / (interest_income + non_interest_income) * 100
            if interest_income is not None and non_interest_income is not None and (interest_income + non_interest_income)
            else None
        ),
        "cir_pct": abs(operating_expenses) / abs(pre_operating_income) * 100 if operating_expenses is not None and pre_operating_income else None,
    }


def _multi_period_article_trend_table(
    excel_rows: list[dict],
    language: str,
    *,
    limit: int = 6,
) -> dict | None:
    period_groups = _article_period_groups(excel_rows, limit=limit)
    points: list[dict] = []
    for group in period_groups:
        point = _article_trend_point_from_rows(group.get("rows") or [])
        if not point:
            continue
        point["label"] = _article_period_group_label(group.get("sort_value") or "", "Период")
        points.append(point)
    if len(points) < 2:
        return None

    labels = {
        "ru": {
            "caption": "Таблица 6 — Многоквартальная динамика ключевых показателей",
            "note": "Периоды показаны от последнего отчёта к более ранним; суммы указаны в млрд сум.",
            "metric": "Показатель",
            "assets_total": "Активы",
            "deposits": "Клиентские депозиты",
            "loans_net": "Кредиты и лизинг (нетто)",
            "equity": "Собственный капитал",
            "net_profit": "Чистая прибыль",
            "first_line_pct": "Ликвидность 1-й линии",
            "ldr_pct": "LDR",
            "capital_assets_pct": "Капитал / активы",
            "reserve_coverage_pct": "Резерв / брутто-кредиты",
            "interest_coverage": "Покрытие % расходов",
            "cir_pct": "CIR",
        },
        "en": {
            "caption": "Table 6 — Multi-period key indicator trend",
            "note": "Periods are shown from latest to earlier; amounts are in bln UZS.",
            "metric": "Metric",
            "assets_total": "Assets",
            "deposits": "Client deposits",
            "loans_net": "Loans and leasing, net",
            "equity": "Equity",
            "net_profit": "Net profit",
            "first_line_pct": "First-line liquidity",
            "ldr_pct": "LDR",
            "capital_assets_pct": "Capital / assets",
            "reserve_coverage_pct": "Reserve / gross loans",
            "interest_coverage": "Interest expense coverage",
            "cir_pct": "CIR",
        },
        "uz": {
            "caption": "Jadval 6 — Asosiy ko'rsatkichlarning ko'p davrli dinamikasi",
            "note": "Davrlar eng so'nggi hisobotdan oldingilariga qarab berilgan; summalar mlrd so'mda.",
            "metric": "Ko'rsatkich",
            "assets_total": "Aktivlar",
            "deposits": "Mijoz depozitlari",
            "loans_net": "Kredit va lizing (netto)",
            "equity": "Kapital",
            "net_profit": "Sof foyda",
            "first_line_pct": "1-qator likvidlik",
            "ldr_pct": "LDR",
            "capital_assets_pct": "Kapital / aktivlar",
            "reserve_coverage_pct": "Rezerv / brutto kreditlar",
            "interest_coverage": "Foiz xarajatlari qoplanishi",
            "cir_pct": "CIR",
        },
    }.get(_normalize_language(language), {})
    row_specs = [
        ("assets_total", "money"),
        ("deposits", "money"),
        ("loans_net", "money"),
        ("equity", "money"),
        ("net_profit", "money"),
        ("first_line_pct", "pct"),
        ("ldr_pct", "pct"),
        ("capital_assets_pct", "pct"),
        ("reserve_coverage_pct", "pct"),
        ("interest_coverage", "ratio"),
        ("cir_pct", "pct"),
    ]

    rows: list[list[str]] = []
    for key, kind in row_specs:
        cells = []
        present_count = 0
        for point in points:
            value = point.get(key)
            if value is not None:
                present_count += 1
            if kind == "money":
                cells.append(_format_article_trend_money(value, language))
            elif kind == "pct":
                cells.append(_format_report_pct(value, language) if value is not None else "—")
            elif kind == "ratio":
                cells.append(f"{_format_report_number(value, language=language, digits=2)}×" if value is not None else "—")
        if present_count >= 2:
            rows.append([labels.get(key, key), *cells])

    table = _table_from_rows(
        "multi_period_trend",
        labels.get("caption", "Table 6 — Multi-period key indicator trend"),
        [labels.get("metric", "Metric"), *[point["label"] for point in points]],
        rows,
        source="openinfo_excel.multi_period",
    )
    if table:
        table["note"] = labels.get("note")
    return table

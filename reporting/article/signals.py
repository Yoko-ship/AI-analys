"""Derive comparable financial signals from structured article tables."""

from __future__ import annotations
import re
from numeric_parse import parse_decimal
from reporting.article.labels import _is_total_report_label
from reporting.article.periods import _article_quarter_from_reporting_month
from reporting.localization import _normalize_language
from reporting.presentation import _format_report_number


def _number_from_report_text(value: str) -> float | None:
    """A number out of an already-rendered report cell.

    Lenient (these strings carry unit suffixes and the U+2212 minus), but the
    separator rules come from the shared parser: the old comma->dot rewrite made
    every comma-grouped amount unparseable, so "1,234,567" silently became None.
    """
    text = str(value or "").strip().replace("−", "-")
    return parse_decimal(text, group_sep=",", strip_non_numeric=True)


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


def _table_row_by_keywords(table: dict | None, *keywords: str) -> list[str] | None:
    if not table:
        return None
    lowered_keywords = [keyword.lower() for keyword in keywords]
    source_labels = table.get("_source_labels") or []
    for index, row in enumerate(table.get("rows") or []):
        visible_label = str(row[0] if row else "").lower()
        source_label = str(source_labels[index] if index < len(source_labels) else "").lower()
        label = f"{visible_label} {source_label}".strip()
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
    lang = _normalize_language(language)
    suffix = {
        "ru": "млрд сум",
        "en": "bln UZS",
        "uz": "mlrd so'm",
    }.get(lang, "bln UZS")
    return f"{_format_report_number(value / 1_000_000, language=language, digits=1)} {suffix}"


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


def _annualization_factor_from_label(label: str | None) -> float | None:
    """×(4/q) factor for a cumulative year-to-date figure, from a period label.

    NSBU quarterly statements are cumulative from January 1st, so annualizing
    means scaling by 4/quarter — a blind ×4 is only right for Q1 and overstates
    Q2 by 2× and Q3 by 1.33×. A 31.12 label is the full year (factor 1).
    Returns None when the period cannot be determined — then no annualized
    figure is produced at all rather than a guessed one.
    """
    match = re.fullmatch(r"(\d{2})\.(\d{2})\.(\d{4})", str(label or "").strip())
    if not match:
        return None
    quarter = _article_quarter_from_reporting_month(int(match.group(2)))
    return 4.0 / quarter if quarter else None


def _article_table_signals(
    assets_h: dict | None,
    liab_h: dict | None,
    income_table: dict | None,
) -> dict:
    # Flow figures (profit, interest) in quarterly filings are cumulative YTD —
    # derive the annualization factor from the filing period itself.
    annualize = _annualization_factor_from_label(
        _article_period_label_from_table(assets_h)
        or _article_period_label_from_table(income_table)
    )
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
    provision_expense = _table_value_by_keywords(income_table, "оценка возможных убытков", "кредит")
    if provision_expense is None:
        provision_expense = _table_value_by_keywords(income_table, "резерв")
    pre_tax_profit = _table_value_by_keywords(income_table, "чистая прибыль до")
    profit_tax = _table_value_by_keywords(income_table, "налог на прибыль")
    net_profit = _table_last_value_by_keywords(income_table, "чистая прибыль")

    ldr_pct = loans_net / deposits * 100 if loans_net is not None and deposits else None
    first_line_pct = ((cash or 0.0) + (cbu or 0.0)) / assets_total * 100 if assets_total and (cash is not None or cbu is not None) else None
    reserve_coverage_pct = reserve_loans / gross_loans * 100 if reserve_loans is not None and gross_loans else None
    capital_assets_pct = equity / assets_total * 100 if equity is not None and assets_total else None
    interest_coverage = interest_income / interest_expense if interest_income is not None and interest_expense else None
    net_interest_income = interest_income - interest_expense if interest_income is not None and interest_expense is not None else None
    roa_quarter_pct = net_profit / assets_total * 100 if net_profit is not None and assets_total else None
    roe_quarter_pct = net_profit / equity * 100 if net_profit is not None and equity else None
    nim_quarter_pct = net_interest_income / assets_total * 100 if net_interest_income is not None and assets_total else None
    net_margin_pct = net_profit / interest_income * 100 if net_profit is not None and interest_income else None
    reserve_burden_pct = abs(provision_expense) / abs(interest_income) * 100 if provision_expense is not None and interest_income else None
    effective_tax_pct = abs(profit_tax) / abs(pre_tax_profit) * 100 if profit_tax is not None and pre_tax_profit else None
    liabilities_total = _table_value_by_keywords(liab_h, "итого обязательств")
    debt_assets_pct = liabilities_total / assets_total * 100 if liabilities_total is not None and assets_total else None
    debt_equity = liabilities_total / equity if liabilities_total is not None and equity else None
    leverage_assets_equity = assets_total / equity if assets_total is not None and equity else None
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
        "provision_expense": provision_expense,
        "pre_tax_profit": pre_tax_profit,
        "profit_tax": profit_tax,
        "net_profit": net_profit,
        "net_interest_income": net_interest_income,
        "ldr_pct": ldr_pct,
        "first_line_pct": first_line_pct,
        "reserve_coverage_pct": reserve_coverage_pct,
        "capital_assets_pct": capital_assets_pct,
        "interest_coverage": interest_coverage,
        "roa_quarter_pct": roa_quarter_pct,
        "roa_annual_pct": roa_quarter_pct * annualize if roa_quarter_pct is not None and annualize else None,
        "roe_quarter_pct": roe_quarter_pct,
        "roe_annual_pct": roe_quarter_pct * annualize if roe_quarter_pct is not None and annualize else None,
        "nim_quarter_pct": nim_quarter_pct,
        "nim_annual_pct": nim_quarter_pct * annualize if nim_quarter_pct is not None and annualize else None,
        "annualization_factor": annualize,
        "net_margin_pct": net_margin_pct,
        "reserve_burden_pct": reserve_burden_pct,
        "effective_tax_pct": effective_tax_pct,
        "liabilities_total": liabilities_total,
        "debt_assets_pct": debt_assets_pct,
        "debt_equity": debt_equity,
        "leverage_assets_equity": leverage_assets_equity,
        "non_interest_share_pct": non_interest_share_pct,
        "cir_pct": cir_pct,
    }

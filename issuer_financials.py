"""Issuer identity, filing snapshots and market context shared by reports and routes.

This module owns financial source preparation. It has no web-framework dependency;
HTTP, scheduled work and legacy formatting adapt its results at their own seams.
"""
from __future__ import annotations
import hashlib
import json
import math
import re
from datetime import date, datetime, timezone
from typing import Any
from sector_analysis import SPECIAL_TYPES
from securities_catalog import get_securities_map
from reports_catalog import (
    extract_insurance_balance,
    fetch_report_excel_data,
    get_all_financials,
    get_all_quotes,
    get_all_ratios,
    get_all_trade_stats,
    get_company_index,
    get_company_reports,
    get_financials_series,
    get_financials_series_quarterly,
)


class IssuerNotFoundError(ValueError):
    """No verified issuer matches the supplied identifier."""


class UnsupportedPeriodError(ValueError):
    """The requested standard does not support this reporting period."""


def special_type(issuer):
    # Versioned legal-type routing from the supplied v2.2 specification.
    # These rules contain no financial values.
    ticker = issuer.get("ticker", "").upper()
    if ticker == "UZNF":
        return "investment_fund_ifrs_annual"
    if ticker == "URTS":
        return "commodity_exchange"
    for obj in (issuer, issuer.get("index") or {}, issuer.get("security") or {}):
        kind = obj.get("special_legal_type") or obj.get("organization_type")
        if kind in SPECIAL_TYPES:
            return SPECIAL_TYPES[kind]
    return None


SECTOR_TEMPLATES: dict[str, dict[str, Any]] = {
    "bank": {
        "required_metrics": ["revenue", "net_income", "total_assets", "total_liabilities", "total_equity"],
        "optional_metrics": ["operating_income", "cash"],
        "warning_rules": ["Use only verified bank NSBU lines."],
        "paragraph_structure": ["verdict", "income", "balance", "risks"],
        "version": "bank-nsbu-1.0",
    },
    "insurance": {
        "required_metrics": [
            "revenue", "net_income", "total_assets", "total_equity",
            "gross_insurance_reserves", "reinsurer_share_in_reserves",
            "net_insurance_reserves", "total_liabilities",
        ],
        "optional_metrics": ["operating_income", "cash", "other_liabilities"],
        "warning_rules": ["Gross reserves, reinsurer share and net reserves remain separately traceable."],
        "paragraph_structure": ["verdict", "income", "reserves", "risks"],
        "version": "insurance-nsbu-1.0",
    },
    "non_financial": {
        "required_metrics": ["revenue", "net_income", "net_margin_pct", "roe_pct", "debt_ratio_pct", "current_ratio"],
        "optional_metrics": ["quick_ratio", "pe", "pb"],
        "warning_rules": ["Do not publish EBITDA, CFO, CAPEX or FCF without a separately verified source."],
        "paragraph_structure": ["verdict", "income", "balance", "ratios", "risks"],
        "version": "non-financial-nsbu-1.0",
    },
}

def now() -> datetime:
    return datetime.now(timezone.utc)

def safe_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None

def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)

def snapshot_hash(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()

def normal_name(value: Any) -> str:
    return re.sub(r"[^a-z0-9а-яёўқғҳ]+", " ", str(value or "").lower()).strip()

def classify_organization(issuer: dict[str, Any], standard: str = "nsbu") -> str:
    """Resolve the legal/reporting type before choosing metrics or prose.

    ``sector=finance`` is not specific enough: it contains banks, insurers and
    other financial organizations.  The NSBU Excel URL records the form type
    explicitly and is therefore preferred over name-based fallbacks.
    """
    latest = get_all_financials(standard_form(standard)).get(issuer["ticker"]) or {}
    explicit = str(latest.get("org_type") or "").strip().lower()
    aliases = {
        "jsc": "non_financial",
        "bank": "bank",
        "insurance": "insurance",
        "microfinance": "microfinance",
        "mfo": "microfinance",
        "microfinance_bank": "microfinance_bank",
        "microbank": "microfinance_bank",
        "investment_fund": "investment_fund_ifrs_annual",
        "commodity_exchange": "commodity_exchange",
    }
    special = special_type(issuer)
    if special:
        return special
    if explicit in aliases:
        return aliases[explicit]

    availability = ((issuer.get("index") or {}).get("availability") or {}).get(
        standard_form(standard), {}
    )
    for kind in ("quarter", "annual"):
        for report in availability.get(kind) or []:
            for key in ("excel_url", "excel_url_form1"):
                match = re.search(r"(?:[?&])org_type=([^&]+)", str(report.get(key) or ""), re.I)
                if match and match.group(1).lower() in aliases:
                    return aliases[match.group(1).lower()]

    name = normal_name(f"{issuer.get('name')} {issuer.get('ticker')}")
    if any(token in name for token in ("bank", "банк")):
        return "bank"
    if any(token in name for token in ("insurance", "страх", "sug urta", "sugurta")):
        return "insurance"
    if any(token in name for token in ("microfinance", "микрофинанс", "mikromoliya")):
        return "microfinance"
    if str(issuer.get("sector") or "").strip().lower() == "finance":
        return "financial_unknown"
    return "non_financial"

def sector_template_code(issuer: dict[str, Any], standard: str = "nsbu") -> str:
    organization_type = classify_organization(issuer, standard)
    return organization_type if organization_type in SECTOR_TEMPLATES else "sector_template_missing"

def resolve_issuer(identifier: str) -> dict[str, Any]:
    wanted = str(identifier or "").strip()
    if not wanted:
        raise IssuerNotFoundError("issuer not found")
    upper = wanted.upper()
    securities = get_securities_map()
    ticker = upper if upper in securities else None
    if not ticker:
        ticker = next(
            (key for key, row in securities.items() if str(row.get("isin") or "").upper() == upper),
            None,
        )
    candidates = [ticker] if ticker else list(securities)
    if not ticker:
        for key in candidates:
            idx = get_company_index(key) or {}
            if str(idx.get("org_id") or "") == wanted or normal_name(idx.get("company_name")) == normal_name(wanted):
                ticker = key
                break
    if not ticker:
        raise IssuerNotFoundError("issuer not found")
    security = dict(securities.get(ticker) or {})
    index = dict(get_company_index(ticker) or {})
    return {
        "id": str(index.get("org_id") or ticker),
        "ticker": ticker,
        "tickers": index.get("tickers") or [ticker],
        "isin": security.get("isin"),
        "name": index.get("company_name") or security.get("name") or ticker,
        "sector": index.get("sector") or security.get("sector"),
        "security": security,
        "index": index,
    }

def standard_form(standard: str) -> str:
    return "NSBU" if standard == "nsbu" else "MSFO"

def period_key(period: str) -> tuple[int, int]:
    match = re.fullmatch(r"(\d{4})(?:Q([1-4]))?", str(period or ""))
    if not match:
        return (0, 0)
    return int(match.group(1)), int(match.group(2) or 4)

def period_before(period: str) -> str | None:
    year, quarter = period_key(period)
    if not year:
        return None
    return f"{year - 1}Q{quarter}" if "Q" in period else str(year - 1)

def report_rows(issuer: dict[str, Any], standard: str) -> list[dict[str, Any]]:
    form = standard_form(standard)
    availability = ((issuer.get("index") or {}).get("availability") or {}).get(form) or {}
    rows: list[dict[str, Any]] = []
    for kind in ("annual", "quarter"):
        for row in availability.get(kind) or []:
            period = str(row.get("year") or "") + (f"Q{row.get('quarter')}" if row.get("quarter") else "")
            rows.append({**row, "period": period, "period_type": kind})
    if rows:
        return rows
    for row in get_company_reports(issuer["ticker"]):
        if row.get("report_form") != form:
            continue
        period = str(row.get("year") or "") + (f"Q{row.get('quarter')}" if row.get("quarter") else "")
        rows.append({**row, "period": period})
    return rows

def expected_reporting_period(standard: str, today: date) -> tuple[str, date, bool]:
    if standard == "ifrs":
        period = str(today.year - 1)
        due = date(today.year, 6, 30)
        if today < due:
            period, due = str(today.year - 2), date(today.year - 1, 6, 30)
        return period, due, today < due

    candidates: list[tuple[str, date, date]] = []
    for year in range(today.year - 2, today.year + 1):
        candidates.extend(
            [
                (f"{year}Q1", date(year, 3, 31), date(year, 4, 30)),
                (f"{year}Q2", date(year, 6, 30), date(year, 7, 30)),
                (f"{year}Q3", date(year, 9, 30), date(year, 10, 30)),
                (str(year), date(year, 12, 31), date(year + 1, 3, 31)),
            ]
        )
    ended = [item for item in candidates if item[1] <= today]
    period, _end, due = max(ended, key=lambda item: item[1])
    return period, due, today < due

def freshness_one(issuer: dict[str, Any], standard: str, today: date | None = None) -> dict[str, Any]:
    today = today or now().date()
    rows = report_rows(issuer, standard)
    expected, due, within_window = expected_reporting_period(standard, today)
    latest = max(rows, key=lambda row: period_key(row.get("period")), default=None)
    latest_period = latest.get("period") if latest else None
    published = (latest or {}).get("published_at") or (latest or {}).get("synced_at")
    published_day = None
    try:
        published_day = datetime.fromisoformat(str(published).replace("Z", "+00:00")).date() if published else None
    except ValueError:
        pass
    if not latest:
        status = "no_data"
    elif period_key(latest_period) >= period_key(expected):
        status = "updated" if published_day and (today - published_day).days <= 30 else "current"
    elif within_window:
        status = "awaiting"
    else:
        gap = (period_key(expected)[0] * 4 + period_key(expected)[1]) - (period_key(latest_period)[0] * 4 + period_key(latest_period)[1])
        status = "stale" if gap >= (8 if standard == "nsbu" else 2) else "overdue"
    return {
        "standard": standard,
        "expected_period": expected,
        "latest_period": latest_period,
        "expected_due_date": due.isoformat(),
        "status": status,
        "publication_date": published,
        "calculated_at": now().isoformat(),
        "source": (latest or {}).get("pdf_url") or (latest or {}).get("excel_url"),
    }

def financial_snapshot(issuer: dict[str, Any], standard: str, period: str | None, scope: str) -> dict[str, Any]:
    if standard == 'ifrs' and period and ('Q' in period):
        raise UnsupportedPeriodError('IFRS quarterly data is not part of the market-wide comparable layer')
    ticker = issuer['ticker']
    form = standard_form(standard)
    organization_type = classify_organization(issuer, standard)
    template_code = sector_template_code(issuer, standard)
    is_quarterly = standard == 'nsbu' and bool(period and 'Q' in period)
    if standard == 'nsbu' and period is None:
        annual_series = get_financials_series(ticker, form)
        quarterly_series = get_financials_series_quarterly(ticker, form)
        selected = max([*(str(key) for key in annual_series or {}), *(str(key) for key in quarterly_series or {})], key=period_key, default=None)
        is_quarterly = bool(selected and 'Q' in selected)
        series = quarterly_series if is_quarterly else annual_series
    else:
        series = get_financials_series_quarterly(ticker, form) if is_quarterly else get_financials_series(ticker, form)
        selected = period
    available = sorted((str(key) for key in series or {}), key=period_key, reverse=True)
    selected = selected or (available[0] if available else None)
    reported_values = dict((series or {}).get(selected) or {}) if selected else {}
    values = dict(reported_values)
    reviewed_correction_fields: set[str] = set()
    if selected:
        try:
            import data_quality
            correction_year, correction_quarter = period_key(selected)
            reviewed_correction_fields = set(data_quality.approved_corrections_for(ticker, form, correction_year, correction_quarter))
        except Exception:
            reviewed_correction_fields = set()
    previous_period = period_before(selected) if selected else None
    previous_reported = dict((series or {}).get(previous_period) or {}) if previous_period else {}
    previous = dict(previous_reported)
    period_basis = 'cumulative_ytd' if is_quarterly and selected else 'annual'
    reports = report_rows(issuer, standard)
    source_doc = next((row for row in reports if row.get('period') == selected), None)
    source = {'document_id': (source_doc or {}).get('report_id') or f"catalog:{ticker}:{form}:{selected or 'none'}", 'url': (source_doc or {}).get('pdf_url') or (source_doc or {}).get('excel_url'), 'publication_date': (source_doc or {}).get('published_at') or (source_doc or {}).get('synced_at'), 'provider': 'openinfo/catalog'}
    insurance_balance: dict[str, Any] = {}
    insurance_mapping_error: str | None = None
    if standard == 'nsbu' and organization_type == 'insurance' and selected:
        year, quarter = period_key(selected)
        if 'Q' not in selected:
            quarter = 0
        try:
            workbook = fetch_report_excel_data(ticker, form, year, quarter)
            insurance_balance = extract_insurance_balance(workbook.get('balance') or workbook.get('income')) if workbook.get('ok') else {}
            if insurance_balance.get('gross_insurance_reserves') is None:
                insurance_mapping_error = str(workbook.get('error') or 'insurance reserve lines were not mapped')
            else:
                for field in ('total_assets', 'total_equity', 'total_liabilities', 'gross_insurance_reserves', 'reinsurer_share_in_reserves', 'net_insurance_reserves', 'other_liabilities'):
                    values[field] = insurance_balance.get(field)
                    reported_values[field] = insurance_balance.get(field)
        except Exception as exc:
            insurance_mapping_error = str(exc)
    observations: dict[str, dict[str, Any]] = {}
    missing = object()

    def add(code: str, value: Any, unit: str, raw_value: Any=missing) -> None:
        number = safe_float(value)
        reported = number if raw_value is missing else safe_float(raw_value)
        observations[code] = {'metric': code, 'raw': reported, 'normalized': number, 'period': selected, 'standard': standard, 'scope': scope, 'currency': 'UZS' if 'UZS' in unit else None, 'unit': unit, 'source': source, 'quality': ('normalized' if reported is not None and number is not None and (reported != number) else 'reported') if number is not None else 'missing'}
    direct_codes = ['revenue', 'net_income', 'operating_income', 'cash', 'total_assets', 'total_equity', 'total_liabilities']
    if organization_type == 'non_financial':
        direct_codes.insert(2, 'gross_profit')
    if organization_type == 'insurance':
        direct_codes.extend(['gross_insurance_reserves', 'reinsurer_share_in_reserves', 'net_insurance_reserves', 'other_liabilities'])
    for code in direct_codes:
        add(code, values.get(code), 'thousand UZS', reported_values.get(code))
    if organization_type == 'non_financial':
        ratios = get_all_ratios().get(ticker) or {}
        for source_code, code in (('roe', 'roe_pct'), ('roa', 'roa_pct'), ('debt_to_equity', 'debt_to_equity'), ('current_ratio', 'current_ratio'), ('quick_ratio', 'quick_ratio')):
            value = values.get(source_code)
            ratio_period = selected
            if value is None and ratios.get(source_code) is not None:
                value = ratios.get(source_code)
                ratio_period = (ratios.get('periods') or {}).get(source_code) or ratios.get('period')
            add(code, value, '%' if code.endswith('_pct') else 'x')
            observations[code]['period'] = ratio_period
            if ratio_period and selected and (ratio_period != selected):
                observations[code]['quality'] = 'different_period'

    def derived(code: str, value: Any, formula: str, unit: str='%') -> None:
        add(code, value, unit)
        observations[code]['quality'] = 'derived' if value is not None else 'missing'
        observations[code]['formula'] = formula
    revenue, net_income = (safe_float(values.get('revenue')), safe_float(values.get('net_income')))
    prev_revenue, prev_income = (safe_float(previous.get('revenue')), safe_float(previous.get('net_income')))
    derived('revenue_growth_pct', (revenue - prev_revenue) / abs(prev_revenue) * 100 if revenue is not None and prev_revenue not in (None, 0) else None, '(current-prior)/abs(prior)*100')
    derived('net_income_growth_pct', (net_income - prev_income) / abs(prev_income) * 100 if net_income is not None and prev_income not in (None, 0) else None, '(current-prior)/abs(prior)*100')
    assets = safe_float(values.get('total_assets'))
    equity = safe_float(values.get('total_equity'))
    liabilities = safe_float(values.get('total_liabilities'))
    if organization_type == 'non_financial':
        derived('net_margin_pct', net_income / revenue * 100 if net_income is not None and revenue not in (None, 0) else None, 'net_income/revenue*100')
        derived('debt_ratio_pct', liabilities / assets * 100 if liabilities is not None and assets not in (None, 0) else None, 'total_liabilities/total_assets*100')
    else:
        derived('liabilities_to_assets_pct', liabilities / assets * 100 if liabilities is not None and assets not in (None, 0) else None, 'total_liabilities/total_assets*100')
    data_quality: list[dict[str, Any]] = []
    if template_code == 'sector_template_missing':
        data_quality.append({'code': 'SECTOR_TEMPLATE_MISSING', 'severity': 'blocking', 'message': 'The financial organization type could not be mapped to a sector template'})
    if insurance_mapping_error:
        data_quality.append({'code': 'INSURANCE_RESERVES_OMITTED', 'severity': 'blocking', 'message': 'Gross reserves, reinsurer share and net insurance reserves were not mapped'})
    balance_check: dict[str, Any] = {'status': 'not_checked', 'difference': None, 'tolerance': None}
    if assets is not None and equity is not None and (liabilities is not None):
        difference = assets - equity - liabilities
        tolerance = max(1.0, abs(assets) * 0.0005)
        balance_check = {'status': 'passed' if abs(difference) <= tolerance else 'failed', 'difference': difference, 'tolerance': tolerance, 'formula': 'assets = equity + liabilities'}
        if abs(difference) > tolerance:
            data_quality.append({'code': 'BALANCE_IDENTITY_FAILED', 'severity': 'blocking', 'message': 'Assets do not equal equity plus sector-correct liabilities', 'actual_difference': difference, 'tolerance': tolerance})
    elif selected and values:
        data_quality.append({'code': 'BALANCE_COMPONENTS_MISSING', 'severity': 'warning', 'message': 'The balance identity could not be checked because a component is missing'})
    payload = {'issuer': {key: issuer[key] for key in ('id', 'ticker', 'name', 'sector', 'isin')}, 'standard': standard, 'template_basis': 'NSBU_PRIMARY' if standard == 'nsbu' else 'IFRS_ANNUAL_SEPARATE', 'organization_type': organization_type, 'sector_template_code': template_code, 'template_version': (SECTOR_TEMPLATES.get(template_code) or {}).get('version'), 'scope': scope, 'period': selected, 'period_basis': period_basis, 'available_periods': available, 'previous_comparable_period': previous_period, 'observations': list(observations.values()), 'source': source, 'current_values': values, 'previous_values': previous, 'opening_values': {}, 'reviewed_correction_fields': sorted(reviewed_correction_fields), 'scope_verified': (source_doc or {}).get('scope') == scope, 'audited': (source_doc or {}).get('audited') is True}
    payload['quality'] = {'traceable': all((item['source']['document_id'] for item in observations.values() if item['raw'] is not None)), 'missing_metrics': [code for code, item in observations.items() if item['normalized'] is None], 'verification_status': 'blocked' if any((item['severity'] == 'blocking' for item in data_quality)) else 'verified', 'balance_check': balance_check, 'data_quality': data_quality, 'warnings': (['requested period is unavailable'] if selected and (not values) else []) + ['NSBU and IFRS are separate layers; this response contains only one standard'] + ([insurance_mapping_error] if insurance_mapping_error else [])}
    payload['source_snapshot_hash'] = snapshot_hash(payload)
    return payload

def quote_and_trade(issuer: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    isin = str(issuer.get("isin") or "").upper()
    quote = dict(get_all_quotes().get(isin) or {})
    trade = dict(get_all_trade_stats().get(isin) or {})
    security = issuer.get("security") or {}
    if not quote:
        quote = {
            "close_price": security.get("close_price") or security.get("last_price"),
            "trade_date": security.get("last_trade_date"),
        }
    return quote, trade

def period_label(period: str | None, lang: str) -> str:
    year, quarter = period_key(period or "")
    if not year:
        return "—"
    labels = {
        "ru": {0: f"{year} год", 1: f"I квартал {year} года", 2: f"I полугодие {year} года", 3: f"9 месяцев {year} года", 4: f"{year} год"},
        "uz": {0: f"{year} yil", 1: f"{year} yil I chorak", 2: f"{year} yil I yarim yillik", 3: f"{year} yil 9 oy", 4: f"{year} yil"},
        "en": {0: f"FY {year}", 1: f"Q1 {year}", 2: f"H1 {year}", 3: f"9M {year}", 4: f"FY {year}"},
    }
    return labels.get(lang, labels["ru"])[quarter if period and "Q" in period else 0]

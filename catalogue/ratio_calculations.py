"""Reproducible board coefficients from one NSBU filing at a time.

Flow/stock ratios use the closing balance and an explicitly annualized YTD
flow. This preserves the board's existing closing-assets turnover convention.
ROCE uses operating profit / (assets - current liabilities), not the opaque
published ROCE series. Its distinct origin and formula travel with every value.
ROCE reference: https://www.accaglobal.com/gb/en/student/exam-support-resources/
fundamentals-exams-study-resources/f2/technical-articles/ratio-analysis.html
"""
from copy import deepcopy
from math import isfinite

from catalogue import codecs, filings, periods, read_batch, snapshots


def latest(conn):
    rows = conn.execute(
        "SELECT f.*, r.pdf_url, r.excel_url FROM catalog_financials f "
        "LEFT JOIN catalog_reports r ON r.id=f.report_id WHERE f.form='NSBU' "
        "ORDER BY f.ticker, f.year, f.quarter, f.updated_at"
    ).fetchall()
    out = {}
    last_fy = periods._latest_complete_fiscal_year()
    for record in rows:
        row = dict(record)
        ticker, year, quarter = row['ticker'], row['year'], row['quarter']
        if (not year or quarter not in range(5) or year > last_fy + 1
                or (quarter == 0 and year > last_fy)):
            continue
        period = f'{year}Q{quarter}' if quarter else str(year)
        months = quarter * 3 if quarter else 12
        row['field_periods'] = codecs._decode_field_periods(row.get('field_periods'))
        row.update(snapshots._fin_row_fields(record))
        snapshots._apply_registered_financial_corrections(
            ticker, snapshots._correction_period(row), row, form='NSBU')

        def number(field):
            value = row.get(field)
            field_period = row['field_periods'].get(field, period)
            if field_period != period or not isinstance(value, (int, float)) or not isfinite(value):
                return None
            return value

        def add(field, operands, numerator, denominator, formula, flow=False, percent=False):
            if any(number(key) is None for key in operands) or denominator is None or denominator <= 0:
                return
            value = numerator / denominator * (100 if percent else 1)
            annualized = flow and months < 12
            if annualized:
                value *= 12 / months
                formula += f' * 12 / {months}'
            if not isfinite(value):
                return
            if field in {'current_ratio', 'quick_ratio'}:
                value = round(value, 2)
            evidence = {
                'value': value, 'period': period, 'period_months': months,
                'annualized': annualized, 'basis': 'annualized_ytd' if annualized else 'annual' if flow else 'as_of',
                'origin': 'UZStock_calculated', 'formula': formula,
                'operands': {key: number(key) for key in operands},
                'operand_unit': 'thousand_UZS', 'unit': 'percent' if percent else 'ratio',
                'balance_basis': 'closing', 'ticker': ticker, 'report_id': row.get('report_id'),
                'source_url': row.get('excel_url') or row.get('pdf_url'),
                'updated_at': row.get('updated_at'),
            }
            slot = out.setdefault(ticker, {})
            if field not in slot or _rank(evidence) >= _rank(slot[field]):
                slot[field] = evidence

        ca, cl, inv = (number(k) for k in ('current_assets', 'current_liabilities', 'inventories'))
        assets, liabilities, revenue, profit = (number(k) for k in (
            'total_assets', 'total_liabilities', 'revenue', 'operating_income'))
        if ca is not None and ca >= 0:
            add('current_ratio', ['current_assets', 'current_liabilities'], ca, cl,
                'current_assets / current_liabilities')
            if inv is not None and 0 <= inv <= ca:
                add('quick_ratio', ['current_assets', 'inventories', 'current_liabilities'], ca - inv, cl,
                    '(current_assets - inventories) / current_liabilities')
        if liabilities is not None and liabilities >= 0:
            add('debt_ratio', ['total_liabilities', 'total_assets'], liabilities, assets,
                'total_liabilities / total_assets * 100', percent=True)
        if revenue is not None and revenue >= 0:
            add('total_asset_turnover', ['revenue', 'total_assets'], revenue, assets,
                'revenue / total_assets', flow=True)
        if (profit is not None and assets is not None and assets > 0 and cl is not None and cl >= 0
                and row.get('org_type') in (None, '', 'jsc')):
            add('return_to_capital_employed', ['operating_income', 'total_assets', 'current_liabilities'],
                profit, assets - cl, 'operating_income / (total_assets - current_liabilities)', flow=True)

    # Match verified issuer codes, never a guessed P suffix or a stale org map.
    groups = {}
    for ticker, security in read_batch.securities().items():
        match = filings._ISIN_ISSUER.fullmatch(str(security.get('isin') or '').upper())
        if match:
            groups.setdefault(match.group(1), []).append(ticker)
    for tickers in groups.values():
        shared = {}
        for ticker in sorted(tickers):
            for field, evidence in out.get(ticker, {}).items():
                if field not in shared or _rank(evidence) > _rank(shared[field]):
                    shared[field] = evidence
        if shared:
            for ticker in tickers:
                out[ticker] = deepcopy(shared)
    return out


def _rank(evidence):
    return (*periods._period_key(evidence['period']), str(evidence.get('updated_at') or ''))

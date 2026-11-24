"""Adapt the existing audited fund registry without broadening its authority."""
import json
import re
from decimal import Decimal
from pathlib import Path


def _observation_key(row):
    # A stock belongs to one date. A flow covers the full interval on the filing.
    start = row.get('period_start') if row['kind'] != 'stock' else None
    return row['source_form'], row.get('metric_id'), row['kind'], start, row['period_end']


def audited_fund(ticker, issuer_id, scope, *, imported=(), statement_fields=False):
    # These records are already reviewed by the sector-report pipeline. They
    # explicitly cover separate accounts; never relabel them consolidated.
    if scope != 'separate':
        return []
    registry=json.loads((Path(__file__).resolve().parents[1]/'config/verified_fund_reports.json').read_text(encoding='utf-8'))
    mapping = {
        'total_assets': ('BS', 'total_assets'), 'total_equity': ('BS', 'total_equity'),
        'total_liabilities': ('BS', 'total_liabilities'), 'cash': ('BS', 'cash'),
        'portfolio_fair_value': ('BS', 'investment_portfolio'),
        'financial_assets_fvtpl': ('BS', 'financial_assets_fvtpl'),
        'dividends_receivable': ('BS', 'dividends_receivable'),
        'unrealized_fair_value_gain': ('PL', 'unrealized_investment_gain' if statement_fields else 'unrealized_fair_value_gain'),
        'dividend_income': ('PL', 'dividend_income'), 'management_expenses': ('PL', 'management_expenses'),
        'operating_income': ('PL', 'operating_income'), 'operating_expenses': ('PL', 'operating_expenses'),
        'profit_before_tax': ('PL', 'profit_before_tax'), 'tax': ('PL', 'income_tax'),
        'net_income': ('PL', 'net_income'), 'cfo': ('CF', 'cfo'),
    }
    result=[]
    for record in registry['reports']:
        if record['ticker']!=ticker or record.get('standard')!='IFRS' or not record.get('audited') or not record.get('verification'):
            continue
        if record.get('source_unit')!='million UZS' or not record.get('source_url'):
            continue
        for key,(form,metric) in mapping.items():
            kind = 'stock' if form == 'BS' else 'flow'
            raw=record.get('values',{}).get(key)
            line=record.get('source_lines',{}).get(key)
            if raw is None or not line:
                continue
            page=re.search(r':p(\d+):',line)
            value=Decimal(raw)*1000
            if key=='tax':
                value=-abs(value)
            result.append(dict(metric_id=metric,raw_label=line,source_code=None,
                source_form=form,kind=kind,
                value=str(value),raw_value=raw,unit='UZS_thousand',unit_scale=1000000,currency='UZS',
                quality='valid',standard='MSFO',scope=scope,issuer_id=issuer_id,
                period_end=record['period_end'],period_start=record['period_end'] if kind=='stock' else record['period_start'],
                reported_annual=True,source_version=record['source_document_id'],source_url=record['source_url'],
                page=int(page[1]) if page else None,audit_status='audited',
                normalization='audited million UZS × 1000 = thousand UZS; tax shown as expense',
                published_at=record['publication_date'],role='PRIMARY'))
    if not result or not imported:
        return result
    imported_keys = {_observation_key(row) for row in imported}
    return [row for row in result if _observation_key(row) not in imported_keys]

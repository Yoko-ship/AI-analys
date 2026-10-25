"""Adapt the existing audited fund registry without broadening its authority."""
import json
import re
from decimal import Decimal
from pathlib import Path


def audited_fund(ticker, issuer_id, scope):
    # These records are already reviewed by the sector-report pipeline. They
    # explicitly cover separate accounts; never relabel them consolidated.
    if scope != 'separate':
        return []
    registry=json.loads((Path(__file__).resolve().parents[1]/'config/verified_fund_reports.json').read_text(encoding='utf-8'))
    mapping={
        'total_assets':('total_assets','stock'), 'total_equity':('total_equity','stock'),
        'total_liabilities':('total_liabilities','stock'), 'cash':('cash','stock'),
        'portfolio_fair_value':('investment_portfolio','stock'),
        'unrealized_fair_value_gain':('unrealized_fair_value_gain','flow'),
        'dividend_income':('dividend_income','flow'), 'management_expenses':('management_expenses','flow'),
        'tax':('income_tax','flow'), 'net_income':('net_income','flow'),
    }
    result=[]
    for record in registry['reports']:
        if record['ticker']!=ticker or record.get('standard')!='IFRS' or not record.get('audited') or not record.get('verification'):
            continue
        if record.get('source_unit')!='million UZS' or not record.get('source_url'):
            continue
        for key,(metric,kind) in mapping.items():
            raw=record.get('values',{}).get(key)
            line=record.get('source_lines',{}).get(key)
            if raw is None or not line:
                continue
            page=re.search(r':p(\d+):',line)
            value=Decimal(raw)*1000
            if key=='tax':
                value=-abs(value)
            result.append(dict(metric_id=metric,raw_label=line,source_code=line,
                source_form='BS' if kind=='stock' else 'PL',kind=kind,
                value=str(value),raw_value=raw,unit='UZS_thousand',unit_scale=1000000,currency='UZS',
                quality='valid',standard='MSFO',scope=scope,issuer_id=issuer_id,
                period_end=record['period_end'],period_start=record['period_end'] if kind=='stock' else record['period_start'],
                reported_annual=True,source_version=record['source_document_id'],source_url=record['source_url'],
                page=int(page[1]) if page else None,audit_status='audited',
                normalization='audited million UZS × 1000 = thousand UZS; tax shown as expense',
                published_at=record['publication_date'],role='PRIMARY'))
    return result

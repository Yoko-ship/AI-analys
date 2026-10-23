"""Publication guard for unreviewed unit errors and isolated balance spikes.

The original series remains intact. A source review is bound to the exact
amount and assets, so it cannot exempt a future scale error for that issuer.
Flow/cash jumps were rejected by the measured 2026-10-17 false-positive audit.
"""
from copy import deepcopy
from functools import lru_cache
import hashlib
import json
from pathlib import Path
from . import analytics, journal


@lru_cache(maxsize=1)
def reviews():
    return json.loads(Path(__file__).with_name('quarantine_reviews.json').read_text())['reviews']


def reviewed(ticker, form, period, field, value, assets):
    for row in reviews():
        if ((row['ticker'],row['standard'],row['period'],row['field']) == (ticker,form,period,field)
                and row['value_uzs']==value and row['assets_uzs']==assets):
            return True
    # An approved source correction is a review of this precise number.
    from data_quality import approved_corrections_for
    from financial_corrections import corrections_for
    year=int(period[:4]);quarter=int(period[-1]) if 'Q' in period else 0
    key={'net_profit':'net_income','net_revenue':'revenue'}.get(field,field)
    approved=approved_corrections_for(ticker,form,year,quarter).get(key)
    if approved is not None and approved*1000==value:
        return True
    entry=corrections_for(ticker,f'{year}Q{quarter or 4}').get(key) if form=='NSBU' else None
    return bool(entry and entry.value_thousands_uzs*1000==value)


def protect(data,ticker,form):
    fields=data.get('series') or {}
    amounts=lambda field: analytics.values(data,field)
    assets=amounts('total_assets')
    flagged={}
    for field in ('net_profit','total_equity'):
        for period,value in amounts(field).items():
            if assets.get(period,0)>0 and abs(value)>1.5*assets[period]:
                flagged[(period,field)]='ABS_VALUE_ABOVE_1_5_ASSETS'
    for field in ('total_assets','total_equity','total_liabilities'):
        values=amounts(field)
        for period,value in values.items():
            if len(period)!=4 or not period.isdigit():continue
            neighbors=[values.get(str(int(period)+delta)) for delta in (-1,1)]
            if all(n is not None and n!=0 and abs(value)>20*abs(n) for n in neighbors):
                flagged[(period,field)]='BALANCE_ABOVE_20_BOTH_YEARS'
    if not flagged:return data
    output=deepcopy(data);gaps=output.setdefault('data_gaps',[])
    for (period,field),rule in flagged.items():
        value=amounts(field)[period]
        if reviewed(ticker,form,period,field,value,assets.get(period)):continue
        source_url=None
        try:
            from catalogue.filings import get_company_reports
            quarter=int(period[-1]) if 'Q' in period else 0
            reports=get_company_reports(ticker) or []
            source=next((r for r in reports if r.get('report_form')==form and r.get('year')==int(period[:4]) and int(r.get('quarter') or 0)==quarter),{})
            source_url=source.get('excel_url') or source.get('pdf_url')
        except Exception:
            pass
        output['series'][field]['values'].pop(period,None)
        # Stored derived ratios must not bypass the input guard.
        for key,entry in output['series'].items():
            if not entry.get('money') or entry.get('derived'):
                entry.get('values',{}).pop(period,None)
        gaps.append({'period':period,'field':field,'code':'VALUE_QUARANTINE','rule':rule,'source_url':source_url})
        signature=hashlib.sha256(json.dumps([value,assets.get(period),rule]).encode()).hexdigest()
        journal.emit('value_quarantine',ticker=ticker,standard=form,period=period,source_url=source_url,
                     message=f'{field}: {rule}',details={'field':field,'value':value,'assets':assets.get(period),'unit':'UZS','rule':rule},
                     dedupe_key=f'{ticker}:{form}:{period}:{field}:{signature}')
    if len(gaps)>len(data.get('data_gaps') or []):output['availability']='PARTIAL'
    return output

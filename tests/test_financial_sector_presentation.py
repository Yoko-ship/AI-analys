"""The history API must retain sector meaning after financial normalisation."""
import asyncio
import json
from pathlib import Path

import pytest
from catalogue import organization
from server.company import financials


@pytest.mark.parametrize('ticker,kind,label', [('HMKB','bank','Совокупные доходы'),('UZAS','insurance','Заработанные премии'),('UZNF','fund',None)])
@pytest.mark.parametrize('freq',['annual','quarterly'])
def test_financial_history_does_not_publish_corporate_margin_for_financial_issuers(monkeypatch,ticker,kind,label,freq):
    reports=json.loads((Path(__file__).parent/'fixtures/terminal_sector_reports.json').read_text(encoding='utf-8'))['reports']
    report=reports[ticker]
    facts={f['metric_code']:f.get('current',f.get('value')) for f in report['verified_facts']}
    if kind=='bank':
        # The NSBU history's top line aggregates the two filed income lines.
        facts['revenue']=facts['interest_income']+facts['noninterest_income']
    period=report['period']
    series={key:{'money':True,'values':{period:facts[source]*1000}} for key,source in [('net_revenue','revenue'),('net_profit','net_income'),('total_assets','total_assets')] if facts.get(source) is not None}
    # The indicator feed and old derivation can supply these for any form.
    series['net_margin']={'money':False,'values':{period:5}}
    series['net_profit_margin']={'money':False,'values':{period:.05}}
    async def raw(*args):return {'ok':True,'periods':[period],'series':series}
    monkeypatch.setattr(financials,'_financial_series',raw)
    monkeypatch.setattr(organization,'organization_kind',lambda *args,**kwargs:kind)
    result=asyncio.run(financials.financial_series(ticker,freq))
    assert 'net_margin' not in result['series']
    assert 'net_profit_margin' not in result['series']
    assert result['organization_type']==kind
    assert result['series']['net_profit']['values'][period]==facts['net_income']*1000
    if label:assert result['series']['net_revenue']['label_ru']==label

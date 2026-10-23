from decimal import Decimal
from financial_ingestion import extract, validation


def test_uzauto_six_years_retain_visually_checked_usd_and_dated_fx():
    entries={e['year']:e for e in extract.review_entries() if e['ticker']=='UZMT'}
    assert set(entries)==set(range(2020,2026))
    expected={2020:('1296905','160055'),2021:('2229720','166019'),2022:('3296365','235119'),
              2023:('2963694','333765'),2024:('2464103','314948'),2025:('2640277','339638')}
    for year,(assets,profit) in expected.items():
        entry=entries[year]
        assert entry['currency']=='USD' and entry['unit_scale']==1000
        assert entry['figures']['total_assets']['raw_value']==assets
        assert entry['figures']['net_income']['raw_value']==profit
        assert entry['fx']['as_of']==f'{year}-12-31'
        checks=validation.validate(validation.from_review(entry),page_count=entry['page_count'])
        assert checks['valid'],checks
        assert Decimal(checks['normalized_uzs']['net_income'])==Decimal(profit)*1000*Decimal(str(entry['fx']['rate']))
        assert entry['review_method']=='visual-source-page-check'
    assert entries[2020]['role']=='RESTATEMENT'
    assert entries[2023]['role']=='RESTATEMENT'

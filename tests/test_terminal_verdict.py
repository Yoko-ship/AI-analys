import pytest
from tests.test_sector_text_rules import _report


@pytest.mark.parametrize('ticker',['ALSM','METQ','UZMK'])
def test_real_high_risk_reports_require_attention(ticker):
    report=_report(ticker)
    assert any(r['severity']=='high' for r in report['risks'])
    assert report['verdict']['status']=='attention'


def test_medium_risks_cap_without_claiming_high_risk():
    assert _report('CBSK')['verdict']['status']=='mixed'
    assert _report('IPTB')['verdict']['status']=='positive'

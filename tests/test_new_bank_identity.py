"""Recently listed banks stay attached to their official OpenInfo issuers."""

import entity_resolver
import securities_catalog
from company_catalog import COMPANY_CATALOG, COMPANY_SECTORS


def test_orient_finans_identity_is_official_and_shared_by_both_classes() -> None:
    assert entity_resolver.ORG_OVERRIDES["ORFI"] == "16"
    assert entity_resolver.ORG_OVERRIDES["ORFIP"] == "16"
    assert entity_resolver.ISIN_OVERRIDES["ORFI"] == "UZ7055870008"
    assert entity_resolver.ISIN_OVERRIDES["ORFIP"] == "UZ7055871006"
    assert COMPANY_CATALOG['"Orient finans bank" Xususiy aksiyadorlik tijorat banki'] == "ORFI"
    assert COMPANY_SECTORS["ORFI"] == COMPANY_SECTORS["ORFIP"] == "finance"
    assert securities_catalog._TICKER_SECTORS["ORFI"] == "finance"
    assert securities_catalog._TICKER_SECTORS["ORFIP"] == "finance"


def test_infinbank_identity_is_pinned_to_its_openinfo_card() -> None:
    assert entity_resolver.ORG_OVERRIDES["INFB"] == "25"
    assert entity_resolver.ISIN_OVERRIDES["INFB"] == "UZ7055560005"
    assert COMPANY_CATALOG['"Invest Finance Bank" Aksiyadorlik jamiyati'] == "INFB"
    assert COMPANY_SECTORS["INFB"] == securities_catalog._TICKER_SECTORS["INFB"] == "finance"

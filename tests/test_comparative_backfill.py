"""A missing annual is filled from the next annual's prior-year column
(docs/catalog-terminal/02-data.md, R-D4). Figures are the real filings'."""
import pytest

import catalogue.financial_store as catalogue_financial_store
from financial_ingestion import comparative

# BECM's FY2024 annual (jsc/annual/5406) printing FY2023 beside it, thousands.
BECM_FY2024 = {
    "org_type": "jsc",
    "prior": {"revenue": 636_875_363.0, "gross_profit": 120_000_000.0,
              "net_income": 94_897_078.0, "operating_income": 101_000_000.0},
    "balance": {"assets_start": 759_692_384.0, "equity_start": 600_000_000.0,
                "assets_end": 800_000_000.0, "equity_end": 650_000_000.0},
}


@pytest.fixture
def catalog(tmp_path, monkeypatch):
    monkeypatch.setenv("CATALOG_DB_PATH", str(tmp_path / "catalog.db"))


def test_the_prior_year_column_becomes_that_years_figures():
    values = comparative.comparative_values(BECM_FY2024)
    assert values["revenue"] == 636_875_363.0 and values["net_income"] == 94_897_078.0
    assert values["total_assets"] == 759_692_384.0
    assert values["total_liabilities"] == 159_692_384.0


def test_the_bank_form_has_no_comparative():
    assert comparative.comparative_values({**BECM_FY2024, "org_type": "bank"}) is None


def test_an_unfilled_opening_balance_is_a_gap_not_a_nought():
    metrics = {**BECM_FY2024, "balance": {"assets_start": 0.0, "equity_start": 0.0}}
    values = comparative.comparative_values(metrics)
    assert values["revenue"] == 636_875_363.0
    assert values["total_assets"] is None and values["total_liabilities"] is None


def test_a_comparative_of_noughts_states_nothing():
    metrics = {"org_type": "jsc", "prior": {"revenue": 0.0, "net_income": 0.0}, "balance": {}}
    assert comparative.comparative_values(metrics) is None


def _filed(ticker, year, assets):
    catalogue_financial_store.upsert_financials_cache(
        ticker, "NSBU", year, 0, {"revenue": 500_000_000.0, "net_income": 50_000_000.0,
                                  "total_assets": assets, "total_equity": assets / 2})


def test_only_a_year_with_a_usable_filing_after_it_is_missing(catalog):
    _filed("BECM", 2022, 700_000_000.0)
    _filed("BECM", 2024, 800_000_000.0)
    # 2021: junk filing (line numbers as amounts) followed by a real 2022.
    catalogue_financial_store.upsert_financials_cache("BECM", "NSBU", 2021, 0,
                                                      {"revenue": 10.0, "net_income": 270.0})
    assert comparative.missing_years(["BECM"], last_fy=2025) == [2021, 2023]


def test_the_backfill_stores_the_year_with_its_source(catalog, monkeypatch):
    _filed("BECM", 2022, 700_000_000.0)
    _filed("BECM", 2024, 800_000_000.0)
    monkeypatch.setattr(comparative, "missing_years", lambda aliases: [2023])
    monkeypatch.setattr(comparative, "_annual_detail",
                        lambda org, year: ({"object_id": 5406, "org_type": "jsc", "pub_date": "2025-06-26"}, {"x": 1}))
    import openinfo_reconcile
    monkeypatch.setattr(openinfo_reconcile, "extract_metrics", lambda detail: BECM_FY2024)
    events = []
    filled = comparative.backfill_issuer("1",  ["BECM", "BECMP"], journal=lambda e, **f: events.append((e, f)))
    assert filled == [2023]
    stored = comparative.comparative_years("BECMP")["2023"]
    assert stored["revenue"] == 636_875_363.0
    assert stored["source"]["year"] == 2024 and stored["source"]["object_id"] == 5406
    assert comparative.source_url(stored["source"]) == "https://openinfo.uz/reports/jsc/annual/5406"
    assert events[0][0] == "year_backfill" and events[0][1]["period"] == "2023"

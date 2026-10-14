"""Catalogue analytics by organization kind (audit «Аналитика каталога», К3/К10).

The figures are the issuers' own filed values (thousand UZS) as the catalogue
served them on 2026-10-13, so every threshold is exercised on the cases it
must catch and on the ones it must leave alone.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import catalogue.filings as catalogue_filings
import catalogue.organization as org
import catalogue.periods as catalogue_periods
import catalogue.ratios as catalogue_ratios
import catalogue.snapshots as catalogue_snapshots
import catalogue.sources as catalogue_sources
import server.catalog.analysis as analysis
import server.catalog.routes as routes
import server.catalog.service as service

SQBN_2025 = {"revenue": 10_798_148_130.0, "net_income": 1_880_069_362.0, "total_assets": 102_438_659_711.0,
             "total_equity": 11_875_165_808.0, "total_liabilities": 90_563_493_903.0,
             "gross_profit": 4_265_635_819.0, "operating_expenses": 2_041_362_497.0,
             "operating_income": 2_224_273_322.0, "cash": 2_006_706_908.0}
SQBN_2023 = {"revenue": 7_179_862_148.0, "net_income": 911_684_119.0, "total_assets": 74_634_423_198.0,
             "total_equity": 8_728_360_152.0, "total_liabilities": 65_906_063_046.0,
             "gross_profit": 2_697_928_042.0, "operating_expenses": 1_566_486_337.0}
# SQBN's FY2024 annual on openinfo: the form's line numbers in the amount column.
SQBN_2024_FILED = {"revenue": 1.0, "net_income": 13.0, "total_assets": 0.0, "total_liabilities": 0.0,
                   "total_equity": 0.0, "gross_profit": 14.0, "operating_expenses": 6.0}
HMKB_2025 = {"revenue": 5_174_244_859.0, "net_income": 1_704_969_118.0, "total_assets": 35_911_649_727.0,
             "total_equity": 6_704_709_904.0, "total_liabilities": 29_206_939_823.0,
             "gross_profit": 3_956_102_734.0, "operating_expenses": 1_890_152_285.0}
HMKB_2024 = {"revenue": 4_353_666_010.0, "net_income": 1_426_604_717.0, "total_assets": 28_708_226_712.0,
             "total_equity": 5_161_403_031.0, "total_liabilities": 23_546_823_681.0,
             "gross_profit": 3_168_483_582.0, "operating_expenses": 1_413_924_153.0}
HMKB_2026Q2 = {"revenue": 2_994_355_667.0, "net_income": 969_962_031.0, "total_assets": 41_314_813_995.0,
               "total_equity": 7_674_671_935.0, "total_liabilities": 33_640_142_060.0,
               "gross_profit": 2_300_000_000.0, "operating_expenses": 1_147_000_000.0}
# MCBA's 2023 annual row repeats 2022 to the unit on every line.
MCBA_2022 = {"total_equity": 3_643_911_081.0, "net_income": 21_314_665.0, "revenue": 2_589_031_954.0,
             "total_assets": 16_782_496_965.0, "total_liabilities": 13_138_585_884.0,
             "gross_profit": 757_044_097.0, "operating_income": 51_972_811.0,
             "operating_expenses": 705_071_286.0, "cash": 550_033_332.0}
UZNF_2025 = {"total_equity": 29_861_539_000.0, "net_income": 1_403_150_000.0, "total_assets": 30_286_541_000.02,
             "total_liabilities": 425_002_000.0, "cash": 32_730_000.0, "operating_expenses": -203_250_000.0,
             "revenue": 0.0, "operating_income": 1_459_050_000.0}


def payload(values, quarter=0):
    return {"period": "x", **catalogue_ratios._cached_catalog_ratio_payload(
        values, catalogue_ratios.catalog_period_months(quarter))}


# ---------------------------------------------------------------------------
# Organization kind is resolved before any figure is chosen
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("evidence, kind", [
    ({"org_type": "bank", "name": "\"O'zbekiston sanoat - qurilish banki\" ATB", "sector": "finance"}, org.BANK),
    ({"org_type": "insurance", "name": "\"Alskom sug'urta kompaniyasi\" AJ", "sector": "finance"}, org.INSURANCE),
    ({"org_type": "jsc", "name": "“Daromad Рlus” investisiya fondi  aksiyadorlik jamiyati", "sector": "funds"}, org.FUND),
    ({"org_type": "jsc", "name": "O'zbekiston Respublikasi Milliy Investitsiya jamg'armasi aksiyadorlik jamiyati",
      "sector": "other"}, org.FUND),
    ({"org_type": "jsc", "name": "\"O'zagrolizing\" aksiyadorlik jamiyati", "sector": "finance"}, org.FINANCIAL),
    ({"org_type": "jsc", "name": "\"O'zRTXB\" AJ", "sector": "finance"}, org.FINANCIAL),
    ({"org_type": "microfinance", "name": "\"AGAT CREDIT\" mikromoliya tashkiloti", "sector": "other"}, org.FINANCIAL),
    ({"org_type": None, "name": "Аksiyadorlik tijorat \"Aloqabank\"", "sector": None}, org.BANK),
    # Must stay industrial: a jsc filer whose name and sector say nothing financial.
    ({"org_type": "jsc", "name": "Kvarts AJ", "sector": "manufacturing"}, org.INDUSTRY),
    ({"org_type": "jsc", "name": "\"UZUM SARMOYA\" mas`uliyati cheklangan jamiyati", "sector": "other"}, org.INDUSTRY),
    ({"org_type": "jsc", "name": "\"Qashqadaryo texnologik transport\" AJ", "sector": "transport"}, org.INDUSTRY),
])
def test_organization_kind_from_filing_form_name_and_sector(evidence, kind):
    assert org.resolve_kind(**evidence) == kind


# ---------------------------------------------------------------------------
# A period with no usable statement never reaches an analysis
# ---------------------------------------------------------------------------

def test_unusable_filings_are_recognised():
    assert catalogue_ratios.catalog_period_problem(SQBN_2024_FILED) == {"code": "no_balance"}
    assert catalogue_ratios.catalog_period_problem({k: 0.0 for k in SQBN_2025}) == {"code": "empty_filing"}
    assert catalogue_ratios.catalog_period_problem({"revenue": 1.0, "net_income": 13.0}) == {"code": "implausible_scale"}
    # Must pass: a large bank, and the smallest listed issuer (TGPG, 8.3 bn UZS of assets).
    assert catalogue_ratios.catalog_period_problem(SQBN_2025) is None
    assert catalogue_ratios.catalog_period_problem({"total_assets": 8_310_000.0, "net_income": 120_000.0}) is None


def test_duplicate_periods_are_recognised_and_resolved_by_the_registry():
    series = {"2021": {**MCBA_2022, "net_income": 1.0e6}, "2022": MCBA_2022, "2023": dict(MCBA_2022)}
    assert catalogue_ratios.catalog_duplicate_periods(series) == {"2023": "2022"}
    # The registry says which of the pair has a filing of its own.
    assert catalogue_ratios.catalog_duplicate_periods(series, filed={"2021", "2023"}) == {"2022": "2023"}
    # Must not fire: two real bank years, and a pair agreeing on two lines only.
    assert catalogue_ratios.catalog_duplicate_periods({"2024": HMKB_2024, "2025": HMKB_2025}) == {}
    two_lines = {"2024": {"total_assets": 5.0e8, "cash": 1.0e7, "net_income": 4.0e6},
                 "2025": {"total_assets": 5.0e8, "cash": 1.0e7, "net_income": 6.0e6}}
    assert catalogue_ratios.catalog_duplicate_periods(two_lines) == {}


def test_withheld_period_states_its_reason(monkeypatch):
    monkeypatch.setattr(catalogue_snapshots, "get_financials_series",
                        lambda ticker, form="NSBU": {"2023": SQBN_2023, "2024": SQBN_2024_FILED, "2025": SQBN_2025})
    monkeypatch.setattr(catalogue_ratios, "_filed_periods", lambda ticker, form: {"2023", "2024", "2025"})
    result = catalogue_ratios.get_cached_catalog_period("SQBN", "NSBU", 2024)
    assert result["has_data"] is False and result["unavailable"] == {"code": "no_balance"}
    assert "нет баланса" in analysis._catalog_no_cached_data("ru", "NSBU", "2024 год", result["unavailable"])


def test_dynamics_leave_out_unusable_and_copied_years(monkeypatch):
    monkeypatch.setattr(catalogue_snapshots, "get_financials_series", lambda ticker, form="NSBU": {
        "2022": MCBA_2022, "2023": dict(MCBA_2022), "2024": SQBN_2024_FILED, "2025": SQBN_2025})
    monkeypatch.setattr(catalogue_snapshots, "get_financials_series_quarterly", lambda ticker, form="NSBU": {})
    monkeypatch.setattr(catalogue_ratios, "_filed_periods", lambda ticker, form: None)
    result = catalogue_ratios.build_cached_catalog_dynamics("X", "NSBU")
    assert result["years"] == [2022, 2025]
    assert 0 not in result["series"]["total_assets"]
    assert result["excluded_periods"] == [{"period": "2023", "code": "duplicate_period", "duplicate_of": "2022"},
                                          {"period": "2024", "code": "no_balance"}]


def test_interim_returns_are_annualised():
    half_year = payload(HMKB_2026Q2, quarter=2)
    assert half_year["annualized"] is True and half_year["period_months"] == 6
    assert half_year["metrics"]["ROE"] == pytest.approx(25.28, abs=0.01)
    assert half_year["metrics"]["ROA"] == pytest.approx(4.70, abs=0.01)
    # Must not scale: an annual, or a margin (flow over flow).
    annual = payload(HMKB_2025)
    assert annual["annualized"] is False
    assert annual["metrics"]["ROE"] == pytest.approx(25.43, abs=0.01)
    assert half_year["metrics"]["net_margin"] == pytest.approx(969_962_031 / 2_994_355_667 * 100, abs=0.01)


# ---------------------------------------------------------------------------
# Changes from a near-zero base
# ---------------------------------------------------------------------------

def test_change_from_a_tiny_base_is_stated_as_a_multiple():
    # The legacy comparison printed «+14 462 071 915%» for a bank's profit.
    text = analysis.describe_change(1_880_069_362.0, 13.0, "ru")
    assert "раз" in text and "%" not in text.split("(")[0]
    assert analysis.describe_change(-46_700_000.0, 5_870_000.0, "ru").startswith("с ")  # sign change
    assert analysis.describe_change(2_000.0, 0.0, "en").startswith("from ")
    # Must stay a percentage: a fivefold rise is +400%, not «в 5 раз».
    assert analysis.describe_change(500.0, 100.0, "ru").startswith("+400%")
    assert analysis.times_word(22) == "раза" and analysis.times_word(12) == "раз" and analysis.times_word(105) == "раз"


# ---------------------------------------------------------------------------
# Banks, insurers and funds are scored on their own metrics
# ---------------------------------------------------------------------------

def subject(kind, current, previous=None, opening=None, quarter=0, **extra):
    s = analysis.Subject(ticker="T", name="Issuer", kind=kind, form="NSBU", year=2025, quarter=quarter,
                         current=payload(current, quarter),
                         previous=payload(previous, quarter) if previous else None,
                         opening=payload(opening) if opening else None, **extra)
    return s.evaluate("ru")


def test_banks_are_scored_as_banks_not_as_factories():
    hmkb = subject(org.BANK, HMKB_2025, HMKB_2024, HMKB_2024, cost_of_risk=1.7)
    assert set(hmkb.metrics) == {"ROA", "ROE", "equity_to_assets", "cost_to_income", "cost_of_risk"}
    assert hmkb.metrics["cost_to_income"] == pytest.approx(47.78, abs=0.01)
    assert hmkb.score["value"] == 100 and hmkb.score["verdict"] == "positive"
    sqbn = subject(org.BANK, SQBN_2025, SQBN_2023, SQBN_2023, cost_of_risk=3.9)
    assert sqbn.score["verdict"] == "positive"
    assert {c["code"]: c["passed"] for c in sqbn.score["checks"]}["cost_of_risk"] is False


def test_implausible_bank_ratios_are_withheld():
    # TRSB's 2025 operating-expense line reads as a 1% cost/income; the indicator
    # feed carries a 432% cost of risk for BRBN. Neither is a ratio of the bank.
    trsb = analysis.kind_metrics(org.BANK, payload({**HMKB_2025, "operating_expenses": 39_000_000.0}), 432.14)
    assert trsb["cost_to_income"] is None and trsb["cost_of_risk"] is None
    assert analysis.kind_metrics(org.BANK, payload(HMKB_2025), 1.7)["cost_of_risk"] == 1.7


def test_empty_fields_give_no_score_and_say_no_data():
    insurer = subject(org.INSURANCE, {"total_assets": 117_799_022.5, "total_equity": 73_496_632.9})
    assert insurer.score["value"] is None and insurer.score["verdict"] == "insufficient"
    peer = subject(org.INSURANCE, {"total_assets": 383_048_394.53, "total_equity": 256_692_978.03})
    text = analysis.multi_company_sections(insurer, peer, "ru")["СКОРИНГ"]
    assert "нет данных" in text and "/100" not in text


def test_fund_is_described_by_nav_with_price_against_nav_per_share():
    fund = subject(org.FUND, UZNF_2025, market={"price": 6.6, "price_date": "2026-10-13",
                                                 "shares": 5_054_262_531_127.0})
    assert set(fund.metrics) == {"nav_return", "expense_ratio", "cash_share", "liabilities_to_nav"}
    assert fund.metrics["expense_ratio"] == pytest.approx(0.68, abs=0.01)
    sections = analysis.financial_sections(fund, "ru")
    assert "Выручка" not in sections["ЧТО_С_ДЕНЬГАМИ"] and "ROE" not in sections["ЭФФЕКТИВНОСТЬ"]
    assert "Чистые активы (NAV): 29,9 трлн сум" in sections["ЧТО_С_ДЕНЬГАМИ"]
    assert "NAV на акцию: 5,91 сум" in sections["ОЦЕНКА_ЦЕНЫ"]
    assert "премия 11,7%" in sections["ОЦЕНКА_ЦЕНЫ"]
    no_shares = subject(org.FUND, UZNF_2025, market={})
    assert "не рассчитывается" in analysis.financial_sections(no_shares, "ru")["ОЦЕНКА_ЦЕНЫ"]


# ---------------------------------------------------------------------------
# Red flags lower the score, and the verdict follows the score
# ---------------------------------------------------------------------------

def test_flags_cap_and_lower_the_score():
    clean = analysis.score_subject(org.INDUSTRY, {"net_income": 1.0}, {"net_income": 0.5}, None,
                                   {"ROE": 20.0, "net_margin": 10.0, "debt_ratio": 30.0}, [])
    assert clean["value"] == 100 and clean["verdict"] == "positive"
    # CBSK 2026Q2: every check passes, two medium flags (company page: «смешанно»).
    medium = [{"code": "liabilities_outpace_equity", "severity": "medium", "text": "x"},
              {"code": "inventories_outpace_revenue", "severity": "medium", "text": "y"}]
    cbsk = analysis.score_subject(org.INDUSTRY, {"net_income": 1.0}, {"net_income": 0.5}, None,
                                  {"ROE": 28.7, "net_margin": 49.0, "debt_ratio": 22.9}, medium)
    assert cbsk["base"] == 100 and cbsk["value"] == 70 and cbsk["verdict"] == "mixed"
    # UZTL 2026Q2: 83 on the checks, a high earnings-quality flag and a medium one.
    high = [{"code": "profit_quality", "severity": "high", "text": "q"}, medium[0]]
    uztl = analysis.score_subject(org.INDUSTRY, {"net_income": 1.0, "revenue": 2.0}, {"net_income": 0.5, "revenue": 1.0},
                                  None, {"ROE": 54.6, "net_margin": 15.5, "debt_ratio": 81.0}, high)
    assert uztl["base"] == 83 and uztl["value"] == 53 and uztl["verdict"] == "mixed"


@pytest.mark.parametrize("score", [None, 0, 39, 40, 69, 70, 74, 75, 100])
def test_verdict_is_read_off_the_score(score):
    verdict = analysis.verdict_for(score)
    expected = ("insufficient" if score is None else "positive" if score >= 75
                else "negative" if score < 40 else "mixed")
    assert verdict == expected


def test_conclusion_text_and_score_agree():
    loss = subject(org.INDUSTRY, {"revenue": 24_000_000.0, "net_income": -7_600_000.0, "total_assets": 300_000_000.0,
                                  "total_equity": 27_000_000.0, "total_liabilities": 273_000_000.0,
                                  "operating_income": -5_200_000.0},
                   {"revenue": 89_800_000.0, "net_income": 146_500.0, "total_assets": 290_000_000.0,
                    "total_equity": 31_700_000.0, "total_liabilities": 258_300_000.0, "operating_income": 1_000_000.0})
    sections = analysis.recommendation_sections(loss, "ru")
    assert loss.score["verdict"] == "negative"
    assert "отрицательные" in sections["ВЕРДИКТ"] and f"{loss.score['value']}/100" in sections["ВЕРДИКТ"]
    assert "Чистый убыток" in sections["КРАСНЫЕ_ФЛАГИ"]


def test_a_signal_reported_by_both_sources_costs_once():
    own = [{"code": "net_loss", "severity": "high", "text": "a"}]
    published = [{"code": "net_income_decline", "severity": "high", "title": "b"},
                 {"code": "inventories_outpace_revenue", "severity": "medium", "title": "c"},
                 {"code": "revenue_growth", "severity": "low", "title": "d"}]
    merged = analysis.merge_published_risks(own, published)
    assert [f["code"] for f in merged] == ["net_loss", "inventories_outpace_revenue"]


# ---------------------------------------------------------------------------
# SWOT has all four quadrants and a catalyst of the issuer's own
# ---------------------------------------------------------------------------

def test_swot_fills_every_block_with_the_issuers_own_figures():
    a = subject(org.BANK, HMKB_2025, HMKB_2024, HMKB_2024)
    a.name = "Hamkorbank"
    b = subject(org.BANK, SQBN_2025, SQBN_2023, SQBN_2023)
    b.name = "SQB"
    sa, sb = analysis.swot_sections(a, "ru"), analysis.swot_sections(b, "ru")
    assert list(sa) == ["СИЛЬНЫЕ_СТОРОНЫ", "СЛАБЫЕ_СТОРОНЫ", "ВОЗМОЖНОСТИ", "УГРОЗЫ", "КАТАЛИЗАТОРЫ"]
    assert all(text.strip() for text in sa.values())
    assert "Hamkorbank" in sa["КАТАЛИЗАТОРЫ"] and sa["КАТАЛИЗАТОРЫ"] != sb["КАТАЛИЗАТОРЫ"]
    assert "запас капитала" in sa["ВОЗМОЖНОСТИ"].lower()


# ---------------------------------------------------------------------------
# Peers: same kind, same period, comparable scale
# ---------------------------------------------------------------------------

def test_peer_scale_limit_against_the_listed_universe():
    # ODMP (16.1 bn UZS of assets) and UZNF (30.3 trn): 1 883×.
    assert service._scale_ratio(16_084_985.0, 30_286_541_000.0) > service.PEER_SCALE_LIMIT
    # Must stay comparable: the largest and smallest listed banks (AGBA, OCBK), 87×;
    # the largest and smallest insurers (UZINP, ALSM), 22×.
    assert service._scale_ratio(104_000_000_000.0, 1_190_000_000.0) <= service.PEER_SCALE_LIMIT
    assert service._scale_ratio(2_570_000_000.0, 117_799_022.5) <= service.PEER_SCALE_LIMIT


def test_peer_statistic_is_the_median_and_needs_three_peers():
    assert analysis.peer_average([{"ROE": 1.0}, {"ROE": 2.0}]) == {}
    stats = analysis.peer_average([{"ROE": -200.0}, {"ROE": 5.0}, {"ROE": 8.0}, {"ROE": 12.0}])
    assert stats == {"ROE": 6.5, "n": 4, "stat": "median"}


# ---------------------------------------------------------------------------
# The route: annual periods, null quarters, JSON on every outcome
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("given, expected", [(None, 0), (0, 0), (4, 0), ("4", 0), (2, 2)])
def test_annual_report_is_accepted_as_null_zero_or_four(given, expected):
    request = routes.CatalogAnalyzeRequest(ticker="UZNGP", year=2025, quarter=given, compare_quarter=given)
    assert request.quarter == expected
    assert request.compare_quarter == (None if given is None else expected)


def _wire(monkeypatch, series, quarterly=None, kind="bank"):
    monkeypatch.setattr(catalogue_snapshots, "get_financials_series", lambda t, form="NSBU": series.get(t, {}))
    monkeypatch.setattr(catalogue_snapshots, "get_financials_series_quarterly",
                        lambda t, form="NSBU": (quarterly or {}).get(t, {}))
    monkeypatch.setattr(catalogue_ratios, "_filed_periods", lambda t, form: None)
    monkeypatch.setattr(org, "filing_org_type", lambda t: kind)
    monkeypatch.setattr(catalogue_filings, "list_companies_with_stats", lambda: [])
    monkeypatch.setattr(catalogue_filings, "get_company_reports", lambda t: [])
    monkeypatch.setattr(service, "_published_risks", lambda *a: [])
    monkeypatch.setattr(service, "_indicator", lambda *a: {})
    monkeypatch.setattr(service, "_org_ids", lambda tickers: {})
    monkeypatch.setattr(service, "_siblings", lambda t: [t])


def _request(**kw):
    base = dict(ticker="HMKB", year=2026, quarter=2, form="NSBU", analysis_type="annual_compare",
                language="ru", compare_ticker=None, compare_year=None, compare_quarter=None)
    return SimpleNamespace(**{**base, **kw})


def test_annual_comparison_compares_years_even_from_a_quarter(monkeypatch):
    _wire(monkeypatch, {"HMKB": {"2024": HMKB_2024, "2025": HMKB_2025}},
          {"HMKB": {"2025Q2": HMKB_2026Q2, "2026Q2": HMKB_2026Q2}})
    result = service.analyze(_request(), {}, {"HMKB": "finance"})
    assert (result["period1"]["year"], result["period1"]["quarter"]) == (2025, 0)
    assert (result["period2"]["year"], result["period2"]["quarter"]) == (2024, 0)
    # A compare quarter left over from the quarterly selector does not apply.
    result = service.analyze(_request(compare_year=2024, compare_quarter=2), {}, {"HMKB": "finance"})
    assert result["period2"]["quarter"] == 0


def test_annual_comparison_skips_an_unusable_year_and_says_so(monkeypatch):
    _wire(monkeypatch, {"SQBN": {"2023": SQBN_2023, "2024": SQBN_2024_FILED, "2025": SQBN_2025}})
    result = service.analyze(_request(ticker="SQBN", year=2025, quarter=0), {}, {"SQBN": "finance"})
    assert result["period2"]["year"] == 2023
    assert any("2024" in note and "нет баланса" in note for note in result["notes"])


def test_comparison_refuses_another_kind_or_scale(monkeypatch):
    _wire(monkeypatch, {"ODMP": {"2025": {"total_assets": 16_084_985.0, "total_equity": 13_826_060.0,
                                          "net_income": 6_043_297.6}},
                        "UZNF": {"2025": UZNF_2025}}, kind="jsc")
    sectors = {"ODMP": "funds", "UZNF": "other"}
    approved = {"ODMP": {"company_name": "Daromad Plus investisiya fondi"},
                "UZNF": {"company_name": "Milliy Investitsiya jamg'armasi"}}
    with pytest.raises(HTTPException) as scale:
        service.analyze(_request(ticker="ODMP", year=2025, quarter=0, analysis_type="multi_company",
                                 compare_ticker="UZNF"), approved, sectors)
    assert scale.value.status_code == 400 and "несопоставимы" in scale.value.detail
    monkeypatch.setattr(org, "filing_org_type", lambda t: "bank" if t == "HMKB" else "jsc")
    _wire_kind = {"HMKB": {"2025": HMKB_2025}, "KVTS": {"2025": HMKB_2025}}
    monkeypatch.setattr(catalogue_snapshots, "get_financials_series", lambda t, form="NSBU": _wire_kind.get(t, {}))
    with pytest.raises(HTTPException) as other_kind:
        service.analyze(_request(ticker="HMKB", year=2025, quarter=0, analysis_type="multi_company",
                                 compare_ticker="KVTS"), {}, {"HMKB": "finance", "KVTS": "manufacturing"})
    assert other_kind.value.status_code == 400 and "того же типа" in other_kind.value.detail


def test_a_slow_analysis_returns_a_json_timeout(monkeypatch):
    import time

    monkeypatch.setattr(routes, "CATALOG_ANALYZE_TIMEOUT_SECONDS", 0.05)
    with pytest.raises(HTTPException) as caught:
        asyncio.run(routes._catalog_run("uz", lambda: time.sleep(0.5)))
    assert caught.value.status_code == 504 and "vaqt" in caught.value.detail


# ---------------------------------------------------------------------------
# Upload-time check: the workbook header names the period it belongs to
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("stated, year, quarter, published", [
    ("2025-12-31", 2025, 0, "2026-07-02"),   # the year end
    ("2022-01-01", 2021, 0, "2022-07-14"),   # IPKY FY2021: the next 1 January
    ("2025-06-26", 2024, 0, "2025-06-26"),   # BECM FY2024: the filing day
    ("2021-01-26", 2020, 0, "2021-01-26"),   # BNGP FY2020
    ("2026-12-31", 2025, 0, "2026-07-07"),   # BIOK FY2025: a date after publication is not evidence
    ("2026-07-31", 2026, 2, "2026-07-31"),   # AGMKP 2026Q2: the filing day
    ("2025-04-21", 2025, 1, "2025-04-21"),   # BRBN 2025Q1
    ("nan", 2025, 0, None),                  # no stated date
])
def test_header_period_check_accepts_real_filings(stated, year, quarter, published):
    assert catalogue_periods.header_period_conflict({"reporting_date": stated}, year, quarter, published) is None


@pytest.mark.parametrize("stated, year, quarter", [
    ("2020-12-31", 2025, 0),   # a 2020 statement filed as «2025»
    ("2025-12-31", 2026, 0),   # TKDM: the FY2025 annual catalogued as 2026
    ("2026-06-30", 2026, 1),   # a half-year filed as the first quarter
    ("2025-09-30", 2026, 3),   # last year's nine months
])
def test_header_period_check_refuses_mislabelled_filings(stated, year, quarter):
    assert "catalogued as" in catalogue_periods.header_period_conflict({"reporting_date": stated}, year, quarter)


def test_workbook_reader_refuses_a_header_from_another_year(monkeypatch):
    monkeypatch.setattr(catalogue_filings, "get_report_urls", lambda *a: {
        "excel_url": "https://example.test/x.xlsx", "excel_url_form1": "https://example.test/x.xlsx",
        "published_at": "2026-09-25T18:23:21", "period_type": "annual", "title": None})
    monkeypatch.setattr(catalogue_sources, "parse_excel_report_document",
                        lambda session, doc: {"ok": True, "reporting_date": "2020-12-31", "sheets": []})
    monkeypatch.setattr(catalogue_sources, "_make_session", lambda: object())
    result = catalogue_sources.fetch_report_excel_data("UZNGP", "NSBU", 2025, 0)
    assert result["ok"] is False and "2020-12-31" in result["error"]


# ---------------------------------------------------------------------------
# The freshest standard is named, and the reader is told when it is not used
# ---------------------------------------------------------------------------

def test_a_fresher_statement_in_the_other_standard_is_named(monkeypatch):
    def latest(ticker, form, **kw):
        return (2025, 0) if form == "MSFO" else (2025, 3)
    monkeypatch.setattr(catalogue_ratios, "latest_cached_catalog_period", latest)
    notes = service.freshness_notes("UZMT", "NSBU", 2025, 3, "ru")
    assert notes and "МСФО" in notes[0] and "2025 год" in notes[0]


def test_an_undigitised_newer_report_is_disclosed(monkeypatch):
    # UZMT: NSBU 9M 2025 is the newest digitised statement; the IFRS annual
    # published on 2026-06-09 has no figures in the cache yet.
    monkeypatch.setattr(catalogue_ratios, "latest_cached_catalog_period",
                        lambda ticker, form, **kw: (2025, 3) if form == "NSBU" else None)
    monkeypatch.setattr(catalogue_filings, "get_company_reports", lambda ticker: [
        {"report_form": "NSBU", "year": 2025, "quarter": 3, "published_at": "2025-10-30T10:00:00"},
        {"report_form": "MSFO", "year": None, "quarter": 0, "published_at": "2026-06-09T12:05:21"},
    ])
    notes = service.freshness_notes("UZMT", "NSBU", 2025, 3, "ru")
    assert notes and "2026-06-09" in notes[0] and "не оцифрованы" in notes[0] and "по НСБУ" in notes[0]
    # Must stay silent when the chosen statement is the newest one.
    monkeypatch.setattr(catalogue_filings, "get_company_reports", lambda ticker: [
        {"report_form": "NSBU", "year": 2025, "quarter": 3, "published_at": "2025-10-30T10:00:00"},
        {"report_form": "MSFO", "year": None, "quarter": 0, "published_at": "2025-06-11T15:20:23"},
    ])
    assert service.freshness_notes("UZMT", "NSBU", 2025, 3, "ru") == []

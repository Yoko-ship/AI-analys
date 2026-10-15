"""A fund's income is every income line of form №2, not its nought revenue.

ODMP («Daromad Plus» investitsiya fondi) files the commercial form, sells
nothing, and so states стр.010 «Чистая выручка» at nought every year; its income
is dividends, interest and gains on securities under стр.110. The «Динамика»
table led with «Выручка» and showed a row of dashes. The figures below are
ODMP's own 2025 annual (thousand UZS) and URTS's, a company with both sales and
financial income, which must keep its revenue.
"""
from __future__ import annotations

import catalogue.financial_store as catalogue_financial_store
import catalogue.parsing as catalogue_parsing
import catalogue.ratios as catalogue_ratios
import catalogue.snapshots as catalogue_snapshots
import openinfo_reconcile as orc


def _form2(rows):
    """A parsed form №2 workbook: [code, prior income, prior expense, current income, current expense]."""
    return {"sheets": [{"table_rows": [{"label": label, "numeric_values": list(values)}
                                       for label, values in rows]}]}


ODMP_2025_FORM2 = _form2([
    ("Чистая выручка от реализации продукции (товаров, работ и услуг)", (10, 0, 0, 0, 0)),
    ("Себестоимость реализованной продукции (товаров, работ и услуг)", (20, 0, 0, 0, 0)),
    ("Расходы периода, всего (стр.050+060+070+080), в том числе:", (40, 0, 432_369.7, 0, 635_521.0)),
    ("Прочие доходы от основной деятельности", (90, 0, 0, 0, 0)),
    ("Доходы от финансовой деятельности, всего (стр.120+130+140+150+160), в том числе:",
     (110, 547_346.7, 0, 6_678_818.5, 0)),
    ("Доходы в виде дивидендов", (120, 535_918.7, 0, 743_225.7, 0)),
    ("Чистая прибыль (убыток) отчетного периода (стр.240-250-260)", (270, 114_977.1, 0, 6_043_297.6, 0)),
])


def test_a_fund_with_no_sales_has_its_financial_income():
    assert catalogue_parsing.commercial_total_income(ODMP_2025_FORM2) == 6_678_818.5
    values = catalogue_parsing.compute_financial_ratios(ODMP_2025_FORM2, None)["source_values"]
    assert values["revenue"] is None and values["total_income"] == 6_678_818.5


def test_a_company_that_sells_adds_its_sales_to_it():
    urts = _form2([
        ("Чистая выручка от реализации продукции (товаров, работ и услуг)", (10, 1, 0, 444_463_777, 0)),
        ("Прочие доходы от основной деятельности", (90, 1, 0, 1_000, 0)),
        ("Доходы от финансовой деятельности, всего (стр.120+130+140+150+160)", (110, 1, 0, 242_355_031, 0)),
    ])
    assert catalogue_parsing.commercial_total_income(urts) == 686_819_808.0


def test_a_nought_current_line_does_not_borrow_last_year():
    lapsed = _form2([
        ("Чистая выручка от реализации продукции (товаров, работ и услуг)", (10, 0, 0, 0, 0)),
        ("Доходы от финансовой деятельности, всего", (110, 547_346.7, 0, 0, 0)),
    ])
    assert catalogue_parsing.commercial_total_income(lapsed) == 0.0


def test_forms_that_number_their_lines_otherwise_are_left_alone():
    insurer = _form2([
        ("Доходы от оказания страховых услуг", (10, 5, 0, 418_452_510, 0)),
        ("Доходы от финансовой деятельности", (110, 1, 0, 9, 0)),
    ])
    assert catalogue_parsing.commercial_total_income(insurer) is None
    assert catalogue_parsing.commercial_total_income(None) is None


def test_the_reconciler_reads_the_same_three_lines():
    row = lambda tnum, title, v3: {"tnum": tnum, "title": title, "value1": "0", "value2": "0",
                                    "value3": v3, "value4": "0"}
    detail = {"org_type": "jsc", "reporting_year": "2025-12-31",
              "financial_results_report": [
                  row("010", "Чистая выручка от реализации продукции", "0"),
                  row("090", "Прочие доходы от основной деятельности", "0"),
                  row("110", "Доходы от финансовой деятельности, всего", "6678818.5"),
                  row("270", "Чистая прибыль (убыток) отчетного периода", "6043297.6")],
              "balance_sheet_report": []}
    assert orc.extract_metrics(detail)["total_income"] == 6_678_818.5
    insurer = {**detail, "org_type": "insurance", "financial_results_report": [
        row("010", "Доходы от оказания страховых услуг", "5")]}
    assert orc.extract_metrics(insurer)["total_income"] is None


def test_the_figure_survives_a_push_that_does_not_carry_it(tmp_path, monkeypatch):
    monkeypatch.setenv("CATALOG_DB_PATH", str(tmp_path / "cat.db"))
    catalogue_financial_store.bulk_upsert_financials([{
        "ticker": "ODMP", "year": 2025, "quarter": 0, "net_income": 6_043_297.6,
        "total_assets": 16_084_985.0, "total_equity": 13_826_060.0, "total_income": 6_678_818.5}])
    # A pusher still running code from before the column existed.
    catalogue_financial_store.bulk_upsert_financials([{
        "ticker": "ODMP", "year": 2025, "quarter": 0, "net_income": 6_043_297.6,
        "total_assets": 16_084_985.0, "total_equity": 13_826_060.0}])
    assert catalogue_snapshots.get_financials_series("ODMP")["2025"]["total_income"] == 6_678_818.5


def _wire(monkeypatch, annual, quarterly):
    monkeypatch.setattr(catalogue_snapshots, "get_financials_series", lambda t, form="NSBU": annual)
    monkeypatch.setattr(catalogue_snapshots, "get_financials_series_quarterly", lambda t, form="NSBU": quarterly)
    monkeypatch.setattr(catalogue_ratios, "_filed_periods", lambda t, form: None)


ODMP_2025 = {"revenue": 0.0, "total_income": 6_678_818.5, "net_income": 6_043_297.6,
             "total_assets": 16_084_985.0, "total_equity": 13_826_060.0, "total_liabilities": 2_258_925.0}


def test_fund_dynamics_lead_with_income_and_decumulate_it(monkeypatch):
    q1 = {**ODMP_2025, "total_income": 4_222.73, "net_income": -189_123.76}
    q2 = {**ODMP_2025, "total_income": 161_827.39, "net_income": -245_578.79}
    _wire(monkeypatch, {"2025": ODMP_2025}, {"2026Q1": q1, "2026Q2": q2})
    result = catalogue_ratios.build_cached_catalog_dynamics("ODMP", "NSBU", top_line="total_income")
    assert list(result["series"]) == ["total_income", "net_income", "total_assets", "equity", "total_liabilities"]
    assert result["series"]["total_income"] == [6_678_818.5]
    assert [q["total_income"] for q in result["quarterly"]] == [4_222.73, round(161_827.39 - 4_222.73, 2)]
    assert result["seasonality"]["metric"] == "total_income"


def test_everyone_else_keeps_revenue(monkeypatch):
    _wire(monkeypatch, {"2025": ODMP_2025}, {})
    result = catalogue_ratios.build_cached_catalog_dynamics("URTS", "NSBU")
    assert "revenue" in result["series"] and "total_income" not in result["series"]


def test_the_analysis_asks_for_income_only_for_a_fund(monkeypatch):
    from types import SimpleNamespace

    import catalogue.organization as org
    import server.catalog.service as service

    asked = []

    def dynamics(ticker, form, top_line="revenue"):
        asked.append(top_line)
        return {"years": [2025], "series": {}, "quarterly": []}

    monkeypatch.setattr(catalogue_ratios, "build_cached_catalog_dynamics", dynamics)
    request = SimpleNamespace(ticker="ODMP", year=2026, quarter=2, form="NSBU", analysis_type="dynamics",
                              language="ru", compare_ticker=None, compare_year=None, compare_quarter=None)
    for kind in (org.FUND, org.INDUSTRY, org.BANK):
        monkeypatch.setattr(org, "organization_kind", lambda *a, kind=kind, **k: kind)
        service.analyze(request, {}, {})
    assert asked == ["total_income", "revenue", "revenue"]

"""Root causes from the 13.10.2026 audit of the AI analysis (sector-analysis-3.0).

Each block pins one cause on the filings it was found on — every amount below
is copied from the issuer's own workbook (openinfo export) or published
analysis — and, where the fix rests on a threshold, the filings it must leave
alone:

* К8  the bank loan book was read from whichever of two loan lines came last
      (AGBA, AGBAP, INFB: the «чистые» subtotal left at zero; GRBK: leasing
      only), and a missing key line was silent;
* reserves and provisions — a «минус» reserve line typed negative (ORFI,
      GRBK) and a credit-loss charge typed negative (AGBA) are read by the
      form's own arithmetic;
* К6  the bank form prints no date over its comparison column and banks fill
      it with different dates; the text said «с 1 января» regardless;
* MCBA a comparison column that does not balance is no comparison;
* К9  «из отчёта за I полугодия» — the period was never declined;
* К7  profit formed by exchange differences was not recognised (SQBN 71%);
* К4  the verdict ignored the risks the text printed and the profit's
      direction (ORFI −4.2% «улучшение», OHDN +24.9% «ухудшение»);
* SQBN credit-loss charge matched by other income (gross-up);
* KASU/UZHM «быстрее выручки» for paces of opposite sign or unsigned multiples;
* URTS an exchange's participants' money read as its debt;
* the same figure twice — the headline's percent restated in the body;
* share classes missing from the company registry (AGMK, GRBKP, …) found no
      filing and were blocked for «нет ссылки на исходный документ».
"""
from __future__ import annotations

import re
from copy import deepcopy
from datetime import date
from decimal import Decimal

import pytest

import catalogue.filings as catalogue_filings
import catalogue.storage as catalogue_storage
import financial_analysis.sector_calculations as calc
import financial_analysis.sector_inputs as inputs
import financial_analysis.sector_report as sector_report
import financial_analysis.sector_text_checks as text_checks
import financial_analysis.sector_writer as writer
import issuer_financials as financials
import sector_report_service as service

TODAY = date(2026, 10, 14)
BANK = {"id": "bank", "ticker": "BANK", "name": "Bank", "oked_code": "64190"}
COMPANY = {"id": "co", "ticker": "CO", "name": "Company", "oked_code": "24100"}


def _sheet(rows):
    """Rows as the openinfo parser emits them: the label, then the amounts."""
    return {"sheets": [{"sheet": "Квартальный отчет Банк рус", "table_rows": [
        {"row": index, "label": row[0], "source_cells": list(row)} for index, row in enumerate(rows, 36)]}]}


def _bank_workbook(balance=(), income=()):
    return {"balance": _sheet(balance), "income": _sheet(income)}


def _mapped(workbook, current=None):
    data = {"current_values": dict(current or {}), "previous_values": {}, "opening_values": {}, "quality": {"data_quality": []}}
    service.map_special_lines(data, workbook, "bank")
    return data


# ── К8: the loan book ─────────────────────────────────────────────────────────

AGBA_LOANS = [("7. Кредиты и лизинговые операции", 84183696538, 88402750017),
              ("а. Брутто кредиты", 86547491769, 91210029678),
              ("б. Лизинговые операции, Брутто", 0, 0),
              ("в. Минус: Резерв возможных убытков по кредитам и лизингу", 2363795231, 2807279661),
              ("г. Кредиты и лизинговые операции, чистые", 0, 0)]


def test_agba_loan_book_is_not_hidden_by_a_blank_net_subtotal():
    data = _mapped(_bank_workbook(AGBA_LOANS))
    assert data["current_values"]["loan_portfolio"] == 88402750017
    assert data["opening_values"]["loan_portfolio"] == 84183696538


def test_infb_loan_book_with_a_blank_comparison_column():
    data = _mapped(_bank_workbook([("7. Кредиты и лизинговые операции", 0, 11215215984),
                                   ("а. Брутто кредиты", 0, 11275156968),
                                   ("б. Лизинговые операции, Брутто", 0, 0),
                                   ("в. Минус: Резерв возможных убытков по кредитам и лизингу", 0, 59940984),
                                   ("г. Кредиты и лизинговые операции, чистые", 0, 0)]))
    assert data["current_values"]["loan_portfolio"] == 11215215984


def test_grbk_files_leasing_only_and_both_totals_at_zero():
    data = _mapped(_bank_workbook([("7. Кредиты и лизинговые операции", 0, 0),
                                   ("а. Брутто кредиты", 0, 0),
                                   ("б. Лизинговые операции, Брутто", 1506768812, 1668424935),
                                   ("в. Минус: Резерв возможных убытков по кредитам и лизингу", -349449, 413882),
                                   ("г. Кредиты и лизинговые операции, чистые", 1506419363, 0)]))
    # Gross leasing less the reserve; the opening is the filed net line.
    assert data["current_values"]["loan_portfolio"] == 1668424935 - 413882
    assert data["opening_values"]["loan_portfolio"] == 1506419363
    assert data["field_sources"]["loan_portfolio"]["source_line_id"] == "balance:gross_loans+gross_leasing-loan_reserves"
    # A «минус» reserve typed negative is still a deduction.
    assert data["opening_values"]["loan_reserves"] == 349449


def test_ocbk_line_seven_is_gross_and_the_net_line_is_taken():
    data = _mapped(_bank_workbook([("7. Кредиты и лизинговые операции", 494815045, 609593987),
                                   ("а. Брутто кредиты", 494815045, 609593987),
                                   ("б. Лизинговые операции, Брутто", 0, 0),
                                   ("в. Минус: Резерв возможных убытков по кредитам и лизингу", 207106, 159875),
                                   ("г. Кредиты и лизинговые операции, чистые", 494607939, 609434112)]))
    # OCBK's 609 bn against 16.5 trn of assets is the filing's own loan book:
    # its assets are securities (9.7 trn) and central-bank balances.
    assert data["current_values"]["loan_portfolio"] == 609434112


def test_hmkb_lines_that_agree_are_unchanged():
    data = _mapped(_bank_workbook([("7. Кредиты и лизинговые операции", 26378874646, 29002998524),
                                   ("а. Брутто кредиты", 26097023118, 28792298657),
                                   ("б. Лизинговые операции, Брутто", 690321249, 690321249),
                                   ("в. Минус: Резерв возможных убытков по кредитам и лизингу", 408469721, 479621382),
                                   ("г. Кредиты и лизинговые операции, чистые", 26378874646, 29002998524)]))
    assert data["current_values"]["loan_portfolio"] == 29002998524


def test_sqbn_two_totals_one_reserve_apart_without_gross_lines():
    # SQBN 2025Q2: line 7 carries the gross book, «чистые» the net one.
    value, _ = service._net_loans([(68863077566, "l7"), (66635052996, "lg")], 0, 0, 2228024570)
    assert value == 66635052996


def test_orfi_negative_reserve_is_a_deduction():
    data = _mapped(_bank_workbook([("в. Минус: Резерв возможных убытков по кредитам и лизингу", -90576438, -70569715)]))
    assert data["current_values"]["loan_reserves"] == 70569715
    assert data["opening_values"]["loan_reserves"] == 90576438


def test_annual_bank_form_has_one_column_and_it_is_the_year_end():
    data = _mapped(_bank_workbook([("14. Итого активов", 103596612644),
                                   ("7. Кредиты и лизинговые операции", 79885989474),
                                   ("г. Кредиты и лизинговые операции, чистые", 79885989474)]))
    assert data["current_values"]["total_assets"] == 103596612644
    assert data["current_values"]["loan_portfolio"] == 79885989474
    assert data["opening_values"] == {}


def test_a_missing_key_bank_line_is_recorded_not_silent():
    data = {"current_values": {"total_assets": 1, "total_liabilities": 1, "total_equity": 1, "customer_funds": 1,
                               "interest_income": 1, "net_income": 1}, "quality": {"data_quality": []}}
    service._record_missing_key_lines(data, "ru")
    finding = data["quality"]["data_quality"][0]
    assert finding["code"] == "KEY_LINE_MISSING" and finding["severity"] == "warning"
    assert finding["lines"] == ["loan_portfolio"] and "Кредитный портфель" in finding["message"]
    data["current_values"]["loan_portfolio"] = 1
    service._record_missing_key_lines(data, "ru")
    assert data["quality"]["data_quality"] == []
    # A microfinance organisation takes no deposits: their absence is no finding.
    del data["current_values"]["customer_funds"]
    service._record_missing_key_lines(data, "ru", "microfinance")
    assert data["quality"]["data_quality"] == []
    service._record_missing_key_lines(data, "ru", "bank")
    assert data["quality"]["data_quality"][0]["lines"] == ["customer_funds"]


# ── provisions: the sign from the form's arithmetic ─────────────────────────

AGBA_INCOME = [("3. ЧИСТЫЕ ПРОЦЕНТНЫЕ ДОХОДЫ ДО ОЦЕНКИ ВОЗМОЖНЫХ УБЫТКОВ ПО КРЕДИТАМ И ЛИЗИНГУ", 607695979, "nan"),
               ("а. Минус: Оценка возможных убытков по кредитам и лизингу", -3277350055, "nan"),
               ("б. Чистые процентные доходы после оценки возможных убытков по кредитам и лизингу", -2669654076, "nan")]


def test_agba_negative_credit_loss_line_is_a_charge_by_the_forms_arithmetic():
    # 607.7 bn − 3.28 trn = −2.67 trn: the charge is 3.28 trn, not a release.
    data = _mapped(_bank_workbook(income=AGBA_INCOME))
    assert data["current_values"]["credit_loss_provisions"] == 3277350055


@pytest.mark.parametrize("before, filed, after, expected", [
    (1474187985, 405384742, 994645347, 405384742),     # HMKB: a charge typed positive
    (100, 30, 130, -30),                               # 3б above 3: a release
    (100, -30, 130, -30),
    (219046220, 26139330, 0, 26139330),                # INFB 2025Q2: 3б blank — the filed sign stands
])
def test_credit_loss_sign(before, filed, after, expected):
    income = {"net_interest_income_before_provisions": before, "credit_loss_provisions": filed,
              "net_interest_income_after_provisions": after}
    service._sign_credit_loss_provisions(income)
    assert income["credit_loss_provisions"] == expected


def test_a_release_of_reserves_is_written_as_a_release():
    report = sector_report.make_report(_bank_snapshot(current={"credit_loss_provisions": -50000000},
                                                      previous={"credit_loss_provisions": 80000000}), BANK, "ru", TODAY)
    assert "Резервы восстановлены на 50 млрд сум: это добавило к прибыли; годом ранее отчисления составили 80 млрд сум." in report["text"]
    assert "−50" not in report["text"]


# ── К6: the date of the comparison column ───────────────────────────────────

def _dated(opening, history, sources=None, catalog=None, reports=(), annual=None, monkeypatch=None):
    snapshot = {"period": "2026Q2", "standard": "nsbu", "opening_values": dict(opening), "balance_history": history,
                "comparison_sources": {"opening_from_filing": True, **(sources or {})}}
    if monkeypatch is not None:
        monkeypatch.setattr(financials, "fetch_report_excel_data", lambda *a: deepcopy(annual) if annual else {"ok": False})
    service.date_balance_comparison({"ticker": "BANK"}, snapshot, list(reports), "bank", catalog or {})
    return snapshot


def test_agba_comparison_is_the_end_of_the_first_quarter():
    snapshot = _dated({"total_assets": 111253725894, "total_liabilities": 97442300703, "total_equity": 13811425191},
                      {"2025": {"date": "2025-12-31", "total_assets": 103596612644},
                       "2026Q1": {"date": "2026-03-31", "total_assets": 111253725894}})
    assert snapshot["comparison_sources"]["opening_date"] == "2026-03-31"
    assert snapshot["opening_values"]["total_assets"] == 111253725894


def test_orfi_comparison_is_the_same_quarter_a_year_earlier():
    snapshot = _dated({"total_assets": 18804353595, "total_liabilities": 15210759072, "total_equity": 3593594523},
                      {"2025": {"date": "2025-12-31", "total_assets": 19042048310},
                       "2025Q2": {"date": "2025-06-30", "total_assets": 18804353595},
                       "2026Q1": {"date": "2026-03-31", "total_assets": 19480236799}})
    assert snapshot["comparison_sources"]["opening_date"] == "2025-06-30"


def test_ocbk_comparison_is_the_start_of_the_year_by_its_annual_filing(monkeypatch):
    # The catalogue's annual total for OCBK is 1.19 trn (liabilities plus equity
    # of a filing that does not balance); the annual filing itself states
    # 12.2 trn of assets — the amount in OCBK's comparison column.
    annual = {"ok": True, **_bank_workbook([("14. Итого активов", 12201759061)])}
    snapshot = _dated({"total_assets": 12201759061, "total_liabilities": 11180787917, "total_equity": 1020971144},
                      {"2025": {"date": "2025-12-31", "total_assets": 1190365557},
                       "2026Q1": {"date": "2026-03-31", "total_assets": 15519671031}},
                      reports=[{"period": "2025", "excel_url": "annual"}], annual=annual, monkeypatch=monkeypatch)
    assert snapshot["comparison_sources"]["opening_date"] == "2025-12-31"
    assert snapshot["comparison_sources"]["opening_from_filing"] is True


def test_mcba_comparison_column_that_does_not_balance_is_replaced_by_the_year_start():
    # MCBA 2026Q2: assets of 31.03 against liabilities and equity of 30.09.
    catalog = {"total_assets": 30728787180, "total_liabilities": 24989576234, "total_equity": 5739210946}
    snapshot = _dated({"total_assets": 32299326161, "total_liabilities": 22936198217, "total_equity": 5669288090},
                      {"2026Q1": {"date": "2026-03-31", "total_assets": 32299326161}}, catalog=catalog)
    assert snapshot["opening_values"] == catalog
    assert snapshot["comparison_sources"]["opening_rejected"] == "unbalanced"
    assert snapshot["comparison_sources"]["opening_date"] == "2025-12-31"
    assert snapshot["comparison_sources"]["opening_from_filing"] is False


def test_an_undated_column_is_not_presented_as_1_january():
    catalog = {"total_assets": 100, "total_liabilities": 60, "total_equity": 40}
    snapshot = _dated({"total_assets": 150, "total_liabilities": 90, "total_equity": 60}, {}, catalog=catalog)
    assert snapshot["opening_values"] == catalog
    assert snapshot["comparison_sources"]["opening_rejected"] == "undated"


def test_a_quarter_end_comparison_is_not_completed_with_start_of_year_lines(monkeypatch):
    calls = []
    monkeypatch.setattr(financials, "fetch_report_excel_data", lambda *a: calls.append(a) or {"ok": False})
    snapshot = {"period": "2026Q2", "standard": "nsbu", "template_resolution": {"selected_template": "bank"},
                "current_values": {"total_assets": 2, "loan_portfolio": 1}, "previous_values": {},
                "opening_values": {"total_assets": 1}, "comparison_sources": {"opening_date": "2026-03-31"}}
    service.fill_from_earlier_filings({"ticker": "BANK"}, snapshot, [{"period": "2025", "excel_url": "x"}], "bank")
    assert calls == [] and snapshot["opening_values"] == {"total_assets": 1}


def test_an_unbalanced_start_of_year_is_dropped_and_not_claimed_available():
    snapshot = {"opening_values": {"total_assets": 12201759061, "total_liabilities": 169394413, "total_equity": 1020971144},
                "comparison_sources": {"opening_available": True, "opening_fallback": "2025"}}
    service._drop_unbalanced_opening(snapshot)
    assert snapshot["opening_values"] == {}
    assert snapshot["comparison_sources"]["opening_available"] is False
    assert "opening_fallback" not in snapshot["comparison_sources"]


def _bank_snapshot(current=None, previous=None, opening=None, sources=None, period="2026Q2"):
    return {"organization_type": "bank", "standard": "nsbu", "scope": "separate", "period": period,
            "period_basis": "cumulative_ytd", "previous_comparable_period": "2025Q2",
            "current_values": {"total_assets": 118431903760, "total_liabilities": 104560786862, "total_equity": 13871116898,
                               "interest_income": 11168488904, "net_income": 95620555, **(current or {})},
            "previous_values": {"interest_income": 7736939317, "net_income": 35322424, **(previous or {})},
            "opening_values": {"total_assets": 111253725894, "total_liabilities": 97442300703, "total_equity": 13811425191, **(opening or {})},
            "comparison_sources": dict(sources or {}),
            "source": {"url": "https://openinfo.uz/ru/reports/to_pdf31078/", "document_id": "agba"}, "quality": {"data_quality": []}}


def test_the_text_names_the_date_the_balance_is_compared_with():
    report = sector_report.make_report(_bank_snapshot(sources={"opening_date": "2026-03-31"}), BANK, "ru", TODAY)
    assert "баланс — с 31 марта 2026 года" in report["footnote"]
    assert "1 января" not in report["footnote"]
    facts = {fact["metric_code"]: fact for fact in report["verified_facts"]}
    assert facts["total_assets"]["previous_date"] == "2026-03-31"
    assert facts["net_income"]["previous_date"] == "2025-06-30"
    english = sector_report.make_report(_bank_snapshot(sources={"opening_date": "2026-03-31"}), BANK, "en", TODAY)
    assert "balance sheet against 31 March 2026" in english["footnote"]


def test_the_start_of_the_year_is_still_1_january():
    report = sector_report.make_report(_bank_snapshot(), BANK, "ru", TODAY)
    assert "баланс — с 1 января 2026 года" in report["footnote"]


def test_balance_history_dates_every_filing_at_its_period_end(monkeypatch):
    issuer = {"id": "1", "ticker": "BANK", "name": "Bank", "sector": "bank", "isin": "UZ1"}
    monkeypatch.setattr(financials, "get_financials_series_quarterly", lambda *a: {
        "2026Q2": {"total_assets": 118431903760, "net_income": 1}, "2026Q1": {"total_assets": 111253725894}})
    monkeypatch.setattr(financials, "get_financials_series", lambda *a: {"2025": {"total_assets": 103596612644}})
    monkeypatch.setattr(financials, "report_rows", lambda *a: [])
    monkeypatch.setattr(financials, "classify_organization", lambda *a: "bank")
    snapshot = financials.financial_snapshot(issuer, "nsbu", "2026Q2", "separate")
    assert snapshot["balance_history"]["2026Q1"] == {"date": "2026-03-31", "total_assets": 111253725894}
    assert snapshot["balance_history"]["2025"] == {"date": "2025-12-31", "total_assets": 103596612644}


# ── the comparison column of the enterprise form ─────────────────────────────

def _form1_lines(prior, current):
    codes = ("c400", "c480", "c770", "c410", "c420", "c430", "c440", "c450", "c460", "c470")
    return {f"form1:{code}": {"raw_previous": p, "raw_current": c} for code, p, c in zip(codes, prior, current) if p is not None or c is not None}


def test_dori_comparison_column_that_does_not_balance_keeps_the_catalogue_opening():
    # DORI 2026Q2: 427.7 bn of assets against 435.7 bn of liabilities and equity (1.9%).
    snapshot = {"organization_type": "non_financial", "current_values": {}, "opening_values": {"total_assets": 430000000},
                "source_lines": _form1_lines((427691088, 159454193, 276241505), (428797877, 139305516, 289492361))}
    _, _, opening, _ = inputs.prepare_inputs(snapshot)
    assert opening == {"total_assets": 430000000}


def test_tkdm_typo_of_a_hundredth_of_a_percent_keeps_the_filings_column():
    # TKDM 2026Q2: the comparison column is out by 50 mln sum on 389 bn (0.013%).
    snapshot = {"organization_type": "non_financial", "current_values": {}, "opening_values": {},
                "source_lines": _form1_lines((389092347, 44835612, 344206735 + 50000), (577909472, 85198811, 492710661))}
    _, _, opening, _ = inputs.prepare_inputs(snapshot)
    assert opening["total_assets"] == 389092347


def test_dori_accumulated_deficit_typed_without_its_minus_is_read_by_line_480():
    column = {"total_equity": 139305516, "share_capital": 99209600, "additional_capital": 15305851, "reserve_capital": 42609828,
              "treasury_shares": 0, "retained_earnings": 17819763, "target_receipts": 0, "future_expense_reserves": 0}
    inputs.sign_retained_earnings(column)
    assert column["retained_earnings"] == -17819763
    assert inputs.equity_components_gap(column) == 0


def test_becm_equity_total_that_contradicts_its_components_fails_the_capital_check():
    # BECM 2025Q3: line 480 says 96.4 bn, its components add up to 596.4 bn.
    values = {"total_equity": 96373091, "share_capital": 684828, "additional_capital": 0, "reserve_capital": 164937961,
              "treasury_shares": 0, "retained_earnings": 430750302, "target_receipts": 0, "future_expense_reserves": 0}
    assert calc.capital_analysis(values, {})["reconciliation_status"] == "failed"
    values["total_equity"] = 596373091
    assert calc.capital_analysis(values, {})["reconciliation_status"] != "failed"


# ── К9: the period in its case ──────────────────────────────────────────────

@pytest.mark.parametrize("period, case, expected", [
    ("2025Q2", "acc", "I полугодие 2025 года"), ("2025Q2", "gen", "I полугодия 2025 года"),
    ("2025Q1", "acc", "I квартал 2025 года"), ("2025Q3", "acc", "9 месяцев 2025 года"),
    ("2025", "acc", "2025 год"), ("2025", "gen", "2025 года"),
])
def test_period_names_are_declined(period, case, expected):
    assert writer.period_name(period, "ru", case) == expected


def test_footnote_says_from_the_report_for_the_half_year():
    report = sector_report.make_report(_bank_snapshot(sources={"previous_fallback": "2025Q2"}), BANK, "ru", TODAY)
    assert "Сравнительные данные взяты из отчёта за I полугодие 2025 года." in report["footnote"]
    two = sector_report.make_report(_bank_snapshot(sources={"previous_fallback": "2025Q3", "opening_fallback": "2025"}, period="2026Q3"),
                                    BANK, "ru", TODAY)
    assert "Сравнительные данные взяты из отчётов за 9 месяцев 2025 года и за 2025 год." in two["footnote"]


# ── К7: profit formed by exchange differences ───────────────────────────────

@pytest.mark.parametrize("ticker, values, previous, driver", [
    # Caught: the net FX result is more than 30% of profit before tax.
    ("BRBN", {"fx_income": 490095745, "fx_expenses": 422841434, "profit_before_tax": 214497588}, {}, "FX-driven"),
    ("UNVB", {"fx_income": 113963840, "fx_expenses": 61319862, "profit_before_tax": 167605693}, {}, "FX-driven"),
    ("SQBN", {"fx_income": 1742482343, "fx_expenses": 763773193, "profit_before_tax": 1375654255}, {}, "FX-driven"),
    ("OCBK", {"fx_income": 2029383785, "fx_expenses": 391986574, "profit_before_tax": 179841316}, {}, "FX-driven"),
    # Not caught: below the share, an FX loss, or a swing in a small FX result.
    ("ALKB", {"fx_income": 101589701, "fx_expenses": 30234095, "profit_before_tax": 252768784}, {}, "unknown"),
    ("MCBA", {"fx_income": 131317215, "fx_expenses": 114466082, "profit_before_tax": 76510259}, {}, "unknown"),
    ("UTGA", {"fx_income": 205036050, "fx_expenses": 265299590, "profit_before_tax": 3105135417, "net_income": 2639066579},
     {"fx_income": 1, "fx_expenses": 476292678, "net_income": 1}, "unknown"),
    ("UZTL", {"fx_income": 428963070, "fx_expenses": 380486007, "profit_before_tax": 1034068389, "net_income": 896004259},
     {"fx_income": 1, "fx_expenses": 559842467, "net_income": 1}, "unknown"),
])
def test_fx_driven_profit_threshold(ticker, values, previous, driver):
    assert calc.profit_quality(values, previous)["driver"] == driver, ticker


def test_fx_share_is_stated_in_the_risks_and_holds_the_verdict():
    snapshot = _bank_snapshot(current={"fx_income": 1590498186, "fx_expenses": 1215017046, "profit_before_tax": 1151159101})
    report = sector_report.make_report(snapshot, BANK, "ru", TODAY)
    assert "Чистый валютный доход — около трети прибыли до налога: результат во многом зависит от курса" in report["text"]
    assert report["verdict"]["status"] == "mixed" and "прибыль во многом валютная" in report["verdict"]["reason"]
    over = sector_report.make_report(_bank_snapshot(current={"fx_income": 314701571, "fx_expenses": 282083748, "profit_before_tax": 28557759}),
                                     BANK, "ru", TODAY)
    assert "Чистый валютный доход (32,6 млрд сум) больше прибыли до налога: без него период закрылся бы убытком" in over["text"]


# ── К4: the verdict is held to the profit and to the risks ──────────────────

def test_orfi_profit_down_four_percent_is_not_an_improvement():
    snapshot = _bank_snapshot(current={"interest_income": 1335077916, "net_income": 501625646, "total_assets": 18203311861,
                                       "total_liabilities": 13704185886, "total_equity": 4499125975},
                              previous={"interest_income": 1109064671, "net_income": 523542563},
                              opening={"total_assets": 18804353595, "total_liabilities": 15210759072, "total_equity": 3593594523})
    report = sector_report.make_report(snapshot, BANK, "ru", TODAY)
    assert report["verdict"]["status"] == "mixed"
    assert report["verdict_line"] == "Вердикт: смешанно — процентные доходы растут, но прибыль снижается."


def test_ohdn_profit_up_a_quarter_is_not_a_deterioration():
    snapshot = {"organization_type": "non_financial", "standard": "nsbu", "scope": "separate", "period": "2026Q2",
                "period_basis": "cumulative_ytd", "previous_comparable_period": "2025Q2",
                "current_values": {"revenue": 125842358, "net_income": 1007673, "operating_income": 1961200,
                                   "total_assets": 310990861, "total_equity": 71549337, "total_liabilities": 239441524},
                "previous_values": {"revenue": 155631772, "net_income": 806508, "operating_income": 1031014},
                "opening_values": {"total_assets": 207936734, "total_equity": 65041662, "total_liabilities": 142895072},
                "source": {"url": "https://openinfo.uz/ohdn", "document_id": "ohdn"}, "quality": {"data_quality": []}}
    report = sector_report.make_report(snapshot, COMPANY, "ru", TODAY)
    assert report["verdict"]["status"] == "mixed"
    assert report["verdict"]["reason"] == "прибыль растёт, но выручка снижается"


def test_agba_risk_in_the_text_caps_the_verdict_and_is_named():
    report = sector_report.make_report(_bank_snapshot(), BANK, "ru", TODAY)
    assert "Обязательства растут быстрее капитала" in report["text"]
    assert report["verdict"]["status"] == "mixed"
    assert report["verdict"]["reason"] == "процентные доходы растут, но обязательства растут быстрее капитала"
    flags = report["verdict"]["red_flags"]
    assert [(f["code"], f["effect"]) for f in flags] == [("liabilities_outpace_equity", "caps_at_mixed")]


def test_a_risk_without_a_verdict_phrase_still_caps_the_verdict(monkeypatch):
    import financial_analysis.sector_verdict as sector_verdict
    monkeypatch.setattr(sector_verdict, "RISK_REASONS", {})
    report = sector_report.make_report(_bank_snapshot(), BANK, "ru", TODAY)
    assert report["verdict"]["status"] == "mixed"
    assert report["verdict"]["reason"] == "процентные доходы растут, но в отчёте есть риски"


def test_without_a_risk_an_improvement_stays_an_improvement():
    snapshot = _bank_snapshot(opening={"total_assets": 111253725894, "total_liabilities": 97442300703, "total_equity": 13000000000},
                              current={"total_equity": 13871116898, "total_liabilities": 104560786862})
    snapshot["opening_values"]["total_liabilities"] = 98253725894
    report = sector_report.make_report(snapshot, BANK, "ru", TODAY)
    assert not report["risks"]
    assert report["verdict"]["status"] == "positive"
    assert report["verdict"]["red_flags"] == []


def test_a_red_flag_still_needs_attention():
    snapshot = _bank_snapshot(current={"net_income": -9000000000}, previous={"net_income": 35322424})
    report = sector_report.make_report(snapshot, BANK, "ru", TODAY)
    assert report["verdict"]["status"] == "attention"
    assert {f["effect"] for f in report["verdict"]["red_flags"]} >= {"attention"}


# ── SQBN: provisions matched by other income ────────────────────────────────

@pytest.mark.parametrize("values, flagged", [
    ({"credit_loss_provisions": 9698079760, "other_noninterest_income": 9552876459, "net_interest_income_before_provisions": 2268747484}, True),   # SQBN 9M
    ({"credit_loss_provisions": 8638796655, "other_noninterest_income": 8775851058, "net_interest_income_before_provisions": 1578085871}, True),   # SQBN H1
    ({"credit_loss_provisions": 3277350055, "other_noninterest_income": 4309310111, "net_interest_income_before_provisions": 607695979}, False),   # AGBA
    ({"credit_loss_provisions": 259012441, "other_noninterest_income": 184668326, "net_interest_income_before_provisions": 841061074}, False),    # ORFI
    ({"credit_loss_provisions": 405384742, "other_noninterest_income": 537449992, "net_interest_income_before_provisions": 1474187985}, False),   # HMKB
    ({"credit_loss_provisions": 10, "other_noninterest_income": 10, "net_interest_income_before_provisions": 1000}, False),  # immaterial match
])
def test_gross_up_flag(values, flagged):
    assert calc.provisions_offset_by_other_income(values) is flagged


def test_sqbn_gross_up_is_stated_and_the_provision_share_withheld():
    snapshot = _bank_snapshot(current={"credit_loss_provisions": 9698079760, "other_noninterest_income": 9552876459,
                                       "net_interest_income_before_provisions": 2268747484})
    report = sector_report.make_report(snapshot, BANK, "ru", TODAY)
    assert "Отчисления в резервы (9,7 трлн сум) почти равны прочим непроцентным доходам (9,55 трлн сум)" in report["text"]
    ratio = next(r for r in report["ratios"] if r["metric_code"] == "provisions_to_net_interest_income")
    assert ratio["value"] is None and ratio["calculation_status"] == "withheld_gross_up"
    assert any(f["code"] == "provisions_offset_by_other_income" for f in report["verdict"]["red_flags"])


# ── KASU/UZHM: paces of opposite sign, multiples without a direction ────────

def _company(current, previous, opening):
    return {"organization_type": "non_financial", "standard": "nsbu", "scope": "separate", "period": "2026Q2",
            "period_basis": "cumulative_ytd", "previous_comparable_period": "2025Q2",
            "current_values": current, "previous_values": previous, "opening_values": opening,
            "source": {"url": "https://openinfo.uz/co", "document_id": "co"}, "quality": {"data_quality": []}}


def test_uzhm_inventories_rising_while_revenue_falls_are_not_faster_than_revenue():
    report = sector_report.make_report(_company(
        {"revenue": 24032047, "net_income": -7598814, "inventories": 151759831, "total_assets": 313564490,
         "total_equity": 54004308, "total_liabilities": 259560182},
        {"revenue": 87088571, "net_income": 160432},
        {"inventories": 124848056, "total_assets": 301226428, "total_equity": 63277558, "total_liabilities": 237948870}), COMPANY, "ru", TODAY)
    assert "быстрее выручки" not in report["text"]
    assert "хотя выручка сократилась в 3,6 раза" in report["text"]
    assert "Запасы растут, хотя выручка снижается" in report["text"]


def test_kasu_multiple_states_that_revenue_rose():
    report = sector_report.make_report(_company(
        {"revenue": 433994092, "net_income": 3283637, "receivables": 102827680, "total_assets": 451851450,
         "total_equity": 121930243, "total_liabilities": 329921207},
        {"revenue": 192907330, "net_income": 924358},
        {"receivables": 27434991, "total_assets": 314054232, "total_equity": 118310370, "total_liabilities": 195743862}), COMPANY, "ru", TODAY)
    assert "быстрее выручки (она выросла в 2,2 раза)" in report["text"]


# ── URTS: participants' money is not the exchange's debt ────────────────────

URTS_CURRENT = {"revenue": 264737847, "net_income": 221484280, "total_assets": 7382902408, "total_equity": 535305257,
                "total_liabilities": 6847597151, "settlement_liabilities": 6834477197}
URTS_OPENING = {"total_assets": 5672748945, "total_equity": 619954576, "total_liabilities": 5052794369,
                "settlement_liabilities": 5046787742}


def test_urts_participants_money_is_not_leverage():
    snapshot = _company(URTS_CURRENT, {"revenue": 237634918, "net_income": 186787068}, URTS_OPENING)
    snapshot["template_resolution"] = {"selected_template": "commodity_exchange", "resolution_status": "special_override"}
    report = sector_report.make_report(snapshot, {"id": "urts", "ticker": "URTS", "name": "URTS"}, "ru", TODAY)
    assert "На каждый сум капитала приходится 13 сум обязательств" not in report["text"]
    assert "Средства участников торгов составляют подавляющую часть обязательств." in report["text"]
    assert "liabilities_outpace_equity" not in {r["code"] for r in report["risks"]}


def test_a_company_with_real_leverage_keeps_the_signal():
    # BNGP 2026Q2: liabilities of a quarter of equity grew 2.6-fold.
    report = sector_report.make_report(_company(
        {"revenue": 36093389, "net_income": 572101, "total_assets": 101828233, "total_equity": 80823565, "total_liabilities": 21004667},
        {"revenue": 16238868, "net_income": 833000},
        {"total_assets": 92569631, "total_equity": 84341117, "total_liabilities": 8228513}), COMPANY, "ru", TODAY)
    assert "liabilities_outpace_equity" in {r["code"] for r in report["risks"]}


def test_exchange_reads_participants_money_from_line_760():
    snapshot = {"organization_type": "non_financial", "current_values": {}, "opening_values": {},
                "template_resolution": {"selected_template": "commodity_exchange"}}
    rows = [("Всего по активу баланса (стр.130+стр.390)", "400", 5672748945, 7382902408),
            ("Итого по разделу I (стр.410+420+430-440+450+460+470)", "480", 619954576, 535305257),
            ("Итого по разделу II (стр.490+600)", "770", 5052794369, 6847597151),
            ("Прочие кредиторские задолженности (6900 кроме 6950)", "760", 5046787742, 6834477197)]
    workbook = {"balance": {"sheets": [{"name": "f1", "table_rows": [
        {"row": index, "label": row[0], "source_cells": list(row)} for index, row in enumerate(rows, 84)]}]},
        "income": {"sheets": []}}
    values, _, opening, _ = inputs.prepare_inputs(snapshot, workbook)
    assert values["settlement_liabilities"] == "6834477197" and opening["settlement_liabilities"] == "5046787742"
    snapshot["template_resolution"] = {"selected_template": "industry"}
    values, _, _, _ = inputs.prepare_inputs(snapshot, workbook)
    assert "settlement_liabilities" not in values


# ── one figure once ─────────────────────────────────────────────────────────

def test_the_headline_percent_is_not_restated_below():
    report = sector_report.make_report(_bank_snapshot(), BANK, "ru", TODAY)
    assert "Процентные доходы значительно выросли на 44%" in report["headline"]
    assert report["text"].count("44%") == 1
    assert re.search(r"Процентные доходы (выросли|увеличились) до 11,2 трлн сум\.", report["text"])


def test_the_check_fails_a_restated_headline_percent():
    head = writer.Sentence("Выручка выросла на 40%.", ("revenue",), "headline", percent_codes=("revenue",))
    body = writer.Sentence("Выручка значительно выросла на 40% — до 1 трлн сум.", ("revenue",), "trend",
                           tier="significant", direction="up", pct=Decimal(40), percent_shown=True)
    result = text_checks.run([("headline", head), ("key_points", body)], lang="ru", verdict_status="mixed", complete=False)
    assert next(c for c in result["checks"] if c["code"] == "no_duplicate_sentences")["status"] == "failed"


# ── share classes missing from the company registry ─────────────────────────

@pytest.fixture
def registry(tmp_path, monkeypatch):
    db = tmp_path / "catalog.db"
    monkeypatch.setattr(catalogue_storage, "_catalog_db_path", lambda: str(db))
    conn = catalogue_storage.get_catalog_conn()
    with conn:
        conn.execute("INSERT INTO catalog_companies (ticker, company_name, org_id) VALUES (?,?,?)", ("AGMKP", "Olmaliq KMK", "372"))
        conn.execute("INSERT INTO catalog_companies (ticker, company_name, org_id) VALUES (?,?,?)", ("BNG", "Another issuer", "999"))
        conn.execute("INSERT INTO catalog_reports (ticker, report_form, period_type, year, quarter, pdf_url, excel_url) "
                     "VALUES (?,?,?,?,?,?,?)", ("AGMKP", "NSBU", "quarter", 2026, 2, "https://openinfo.uz/ru/reports/to_pdf1/", "x.xlsx"))
    conn.close()
    import securities_catalog
    monkeypatch.setattr(securities_catalog, "get_securities_map", lambda: {
        "AGMK": {"isin": "UZ7000550002"}, "AGMKP": {"isin": "UZ700055K015"},
        "BNGP": {"isin": "UZ7045550009"}, "BNG": {"isin": "UZ7099990001"}})
    return db


def test_a_share_class_missing_from_the_registry_finds_its_issuers_filings(registry):
    conn = catalogue_storage.get_catalog_conn()
    assert catalogue_filings._org_siblings(conn, "AGMK") == ["AGMK", "AGMKP"]
    conn.close()
    index = catalogue_filings.get_company_index("AGMK")
    assert index["org_id"] == "372"
    assert index["availability"]["NSBU"]["quarter"][0]["pdf_url"].endswith("to_pdf1/")


def test_a_ticker_shape_alone_does_not_join_two_issuers(registry):
    # BNGP is not BNG's preferred share: their ISINs carry different issuer codes.
    conn = catalogue_storage.get_catalog_conn()
    assert catalogue_filings._org_siblings(conn, "BNGP") == ["BNGP"]
    conn.close()


# ── the bank path end to end, as sector_report runs it ──────────────────────

AGBA_BALANCE = [("1. Кассовая наличность и другие платежные документы", 2611622842, 2455155322),
                ("2. К получению из ЦБРУ", 1322100112, 1982747802),
                ("3. К получению из других банков", 6544294461, 3506000393),
                *AGBA_LOANS,
                ("14. Итого активов", 111253725894, 118431903760),
                ("15. Депозиты до востребования", 2814862574, 3525815564),
                ("16.Сберегательные депозиты", 32053107838, 39739806727),
                ("17. Срочные депозиты", 0, 0),
                ("25. Итого обязательств", 97442300703, 104560786862),
                ("30. Итого собственного капитала", 13811425191, 13871116898)]
AGBA_RESULTS = [("л. Итого процентных доходов", 11168488904, "nan"), *AGBA_INCOME,
                ("11. ЧИСТАЯ ПРИБЫЛЬ (УБЫТКИ)", 95620555, "nan")]


def _run_bank(monkeypatch, balance, history):
    snapshot = {"organization_type": "bank", "standard": "nsbu", "scope": "separate", "period": "2026Q2",
                "period_basis": "cumulative_ytd", "previous_comparable_period": "2025Q2",
                "current_values": {"total_assets": 118431903760, "total_equity": 13871116898, "total_liabilities": 104560786862,
                                   "net_income": 95620555},
                "previous_values": {"net_income": 35322424},
                "opening_values": {"total_assets": 103596612644, "total_equity": 13774358264, "total_liabilities": 89822254380},
                "balance_history": history, "comparison_sources": {"opening_available": True, "previous_available": True},
                "source": {"url": "https://openinfo.uz/ru/reports/to_pdf31078/"},
                "quality": {"traceable": True, "verification_status": "verified", "data_quality": []}}
    workbooks = {(2026, 2): {"ok": True, **_bank_workbook(balance, AGBA_RESULTS)}}
    documents = [{"period": "2026Q2", "excel_url": "https://example.org/agba-2026q2.xlsx"}]
    monkeypatch.setattr(financials, "classify_organization", lambda *_: "bank")
    monkeypatch.setattr(financials, "financial_snapshot", lambda *_: deepcopy(snapshot))
    monkeypatch.setattr(financials, "report_rows", lambda *_: documents)
    monkeypatch.setattr(financials, "fetch_report_excel_data",
                        lambda ticker, form, year, quarter: deepcopy(workbooks.get((year, quarter), {"ok": False})))
    monkeypatch.setattr(financials, "quote_and_trade", lambda *_: ({}, {}))
    monkeypatch.setattr(service, "_REPORT_CACHE", {})
    issuer = {"id": "19", "ticker": "AGBA", "name": "Agrobank", "sector": "bank", "oked_code": "64190"}
    return service.sector_report(issuer, "nsbu", "2026Q2", "separate", "ru", persist=False)


def test_agba_end_to_end(monkeypatch):
    report = _run_bank(monkeypatch, AGBA_BALANCE, {"2025": {"date": "2025-12-31", "total_assets": 103596612644},
                                                    "2026Q1": {"date": "2026-03-31", "total_assets": 111253725894}})
    facts = {fact["metric_code"]: fact for fact in report["verified_facts"]}
    assert facts["loan_portfolio"]["value"] == 88402750017
    assert facts["credit_loss_provisions"]["value"] == 3277350055
    assert facts["total_assets"]["previous"] == 111253725894 and facts["total_assets"]["previous_date"] == "2026-03-31"
    assert "баланс — с 31 марта 2026 года" in report["footnote"]
    assert not any(item["code"] == "KEY_LINE_MISSING" for item in report["data_quality"])


def test_a_bank_without_a_readable_loan_line_says_so(monkeypatch):
    balance = [row for row in AGBA_BALANCE if "редит" not in row[0] and "Брутто" not in row[0] and "Резерв" not in row[0]]
    report = _run_bank(monkeypatch, balance, {"2026Q1": {"date": "2026-03-31", "total_assets": 111253725894}})
    missing = next(item for item in report["data_quality"] if item["code"] == "KEY_LINE_MISSING")
    assert missing["lines"] == ["loan_portfolio"] and missing["severity"] == "warning"
    assert report["status"] == "available"

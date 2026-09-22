"""The filed balance block (ТЗ мультипликаторов 2026-08-10, лист 09).

Equity and assets come from the SAME filing as the P&L, start and end of the
period, by the line numbers of the RIGHT form — and the forms reuse the same
numbers for different things:

    jsc        480 = источники собственных средств,  400 = итого актив
    insurance  570 = итого собственный капитал,      490 = ИТОГО АКТИВ БАЛАНСА
    bank       «30. Итого собственного капитала»,    «31. Итого обязательств и
               собственного капитала» — no tnum at all, matched by title.

Reading the insurance capital anywhere but line 570 is the systemic error the
external audit found: ALSM's P/B carried the insurance reserves inside its
equity and was three times off. The jsc line 490 is долгосрочные обязательства
— the same number that means «итого активы» one form over — which is why the
extraction branches on org_type and never on wording alone.
"""
from __future__ import annotations

import pytest

import openinfo_reconcile as orc
import reports_catalog as rc


def _jsc_detail():
    return {
        "org_type": "jsc", "reporting_year": "2026-06-30",
        "quarter_financial_results_report": [
            {"tnum": "010", "title": "Чистая выручка", "value1": "50.0", "value2": "0.0",
             "value3": "100.0", "value4": "0.0"},
            {"tnum": "270", "title": "Чистая прибыль (убыток) отчетного периода",
             "value1": "5.0", "value2": "0.0", "value3": "20.0", "value4": "0.0"},
        ],
        "quarter_balance_sheet_report": [
            {"tnum": "400", "title": "Итого по активу баланса", "value1": "900.0", "value2": "1100.0"},
            {"tnum": "480", "title": "Итого по разделу I. Источники собственных средств",
             "value1": "300.0", "value2": "500.0"},
            {"tnum": "490", "title": "Итого по разделу II. Долгосрочные обязательства",
             "value1": "100.0", "value2": "150.0"},
        ],
    }


def _insurance_detail():
    return {
        "org_type": "insurance", "reporting_year": "2026-06-30",
        "quarter_financial_results_report": [
            {"tnum": "010", "title": "Доходы от оказания страховых услуг",
             "value1": "50.0", "value2": "0.0", "value3": "100.0", "value4": "0.0"},
            {"tnum": "320", "title": "Чистая прибыль (убыток)",
             "value1": "5.0", "value2": "0.0", "value3": "20.0", "value4": "0.0"},
        ],
        "quarter_balance_sheet_report": [
            # On the INSURANCE form 490 is the asset total, not a liability.
            {"tnum": "490", "title": "Итого актив баланса", "value1": "900.0", "value2": "1100.0"},
            {"tnum": "570", "title": "Итого собственный капитал", "value1": "300.0", "value2": "500.0"},
        ],
    }


class TestJscBalance:
    def test_equity_is_480_and_assets_400_start_and_end(self):
        got = orc.extract_metrics(_jsc_detail())
        assert got["balance"] == {"equity_start": 300.0, "equity_end": 500.0,
                                  "assets_start": 900.0, "assets_end": 1100.0}

    def test_line_490_never_enters_the_block(self):
        """490 is долгосрочные обязательства here — the exact line the old
        Долг/Капитал numerator confused; it has no place in equity or assets."""
        got = orc.extract_metrics(_jsc_detail())
        assert 150.0 not in got["balance"].values()


class TestInsuranceBalance:
    def test_equity_is_line_570_and_nothing_else(self):
        got = orc.extract_metrics(_insurance_detail())
        assert got["balance"]["equity_end"] == 500.0

    def test_assets_are_line_490_of_the_insurance_form(self):
        got = orc.extract_metrics(_insurance_detail())
        assert got["balance"]["assets_end"] == 1100.0
        assert got["balance"]["assets_start"] == 900.0


class TestBankBalance:
    def _detail(self, quarterly=True):
        value = (lambda s, e: {"value1": s, "value2": e}) if quarterly \
            else (lambda s, e: {"value": e})
        # The live bank form (verified against HMKB's Q2 2026 filing): the P&L
        # is a single `value` column on BOTH the annual and the quarterly form;
        # only the balance sheet differs — value1/value2 on a quarter, one
        # `value` on an annual.
        return {
            "org_type": "bank", "reporting_year": "2026-06-30",
            "quarter_financial_results_report": [
                {"title": "    л. Итого процентных доходов", "value": "500.0"},
                {"title": "     е. Итого беспроцентных доходов", "value": "300.0"},
                {"title": "11. ЧИСТАЯ ПРИБЫЛЬ (УБЫТКИ)", "value": "100.0"},
            ],
            "quarter_balance_sheet_report": [
                {"title": "25. Итого обязательств", **value("800.0", "900.0")},
                {"title": "30. Итого собственного капитала", **value("300.0", "500.0")},
                {"title": "31. Итого обязательств и собственного капитала",
                 **value("1100.0", "1400.0")},
            ],
        }

    def test_the_bank_titles_30_and_31(self):
        got = orc.extract_metrics(self._detail())
        assert got["balance"] == {"equity_start": 300.0, "equity_end": 500.0,
                                  "assets_start": 1100.0, "assets_end": 1400.0}

    def test_noninterest_income_is_extracted(self):
        """Лист 05: маржа банка делится на процентные + беспроцентные доходы."""
        got = orc.extract_metrics(self._detail())
        assert got["noninterest_income"] == 300.0
        assert got["revenue"] == 500.0

    def test_bank_operating_expenses_are_read_from_the_filed_line(self):
        detail = self._detail()
        detail["quarter_financial_results_report"].append(
            {"title": "Итого операционных расходов", "value": "929275668.00"})
        assert orc.extract_metrics(detail)["operating_expenses"] == 929_275_668.0

    def test_an_annual_bank_form_has_an_end_but_no_start(self):
        """The annual bank form publishes ONE value column: the period end is
        real, the start is honestly unknown — never the end copied over."""
        got = orc.extract_metrics(self._detail(quarterly=False))
        assert got["balance"]["equity_end"] == 500.0
        assert got["balance"]["equity_start"] is None


class TestItSurvivesStorageAndThePush:
    def test_the_block_rides_the_row_through_the_admin_push(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CATALOG_DB_PATH", str(tmp_path / "cat.db"))
        rc.bulk_replace_financials([{
            "ticker": "TEST", "year": 2026, "quarter": 2,
            "revenue": 100.0, "net_income": 20.0, "org_type": "insurance",
            "noninterest_income": None,
            "balance": {"equity_start": 300.0, "equity_end": 500.0,
                        "assets_start": 900.0, "assets_end": 1100.0},
        }])
        served = rc.get_all_financials()["TEST"]
        assert served["org_type"] == "insurance"
        assert served["balance"] == {"equity_start": 300.0, "equity_end": 500.0,
                                     "assets_start": 900.0, "assets_end": 1100.0}

    def test_a_legacy_row_written_before_the_columns_still_reads(self):
        assert rc._decode_balance_period(None) is None
        assert rc._decode_balance_period("not json") is None
        assert rc._decode_balance_period("{}") is None

    def test_same_period_top_level_totals_restore_a_missing_balance_block(self, tmp_path, monkeypatch):
        """DRBK already had official assets/equity; the read path dropped them."""
        monkeypatch.setenv("CATALOG_DB_PATH", str(tmp_path / "cat.db"))
        rc.bulk_upsert_financials([{
            "ticker": "DRBK", "year": 2026, "quarter": 2,
            "revenue": 1_852.0, "net_income": 368.0,
            "total_assets": 13_194.0, "total_equity": 2_394.0,
            "balance": None,
        }])

        served = rc.get_all_financials()["DRBK"]

        assert served["balance"] == {
            "equity_start": None, "equity_end": 2_394.0,
            "assets_start": None, "assets_end": 13_194.0,
        }

    def test_an_all_empty_block_is_not_stored(self):
        assert rc._encode_balance_period({"equity_start": None, "equity_end": None,
                                          "assets_start": None, "assets_end": None}) is None
        assert rc._encode_balance_period(None) is None


class TestQ4StandsInForAMissingAnnual:
    """KSCM files no annuals since 2022; its Q4 quarterly IS twelve cumulative
    months with a 31 December balance, and serves as the TTM base."""

    def test_the_companion_falls_back_to_the_q4_quarterly(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CATALOG_DB_PATH", str(tmp_path / "cat.db"))
        rc.bulk_upsert_financials([
            {"ticker": "KSCM", "year": 2025, "quarter": 4, "revenue": 900.0, "net_income": 80.0},
            {"ticker": "KSCM", "year": 2026, "quarter": 2, "revenue": 600.0, "net_income": 50.0},
        ])
        served = rc.get_all_financials()["KSCM"]
        assert served["quarter"] == 2 and served["year"] == 2026
        assert served["annual"]["year"] == 2025
        assert served["annual"]["quarter"] == 4
        assert served["annual"]["period_months"] == 12

    def test_a_real_annual_still_outranks_the_q4(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CATALOG_DB_PATH", str(tmp_path / "cat.db"))
        rc.bulk_upsert_financials([
            {"ticker": "X", "year": 2025, "quarter": 4, "net_income": 80.0},
            {"ticker": "X", "year": 2025, "quarter": 0, "net_income": 85.0},
            {"ticker": "X", "year": 2026, "quarter": 1, "net_income": 30.0},
        ])
        served = rc.get_all_financials()["X"]
        assert served["annual"]["quarter"] == 0
        assert served["annual"]["net_income"] == pytest.approx(85.0)

    def test_a_q4_latest_row_is_not_its_own_companion(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CATALOG_DB_PATH", str(tmp_path / "cat.db"))
        rc.bulk_upsert_financials([
            {"ticker": "Y", "year": 2025, "quarter": 4, "net_income": 80.0},
        ])
        served = rc.get_all_financials()["Y"]
        assert served["annual"] is None


class TestThePriorInterimCompanion:
    """The TTM subtrahend when the form prints no comparative.

    ``TTM = annual(Y−1) + YTD(Y) − YTD(Y−1)``. The jsc form prints YTD(Y−1)
    beside every P&L line, so the subtrahend rides on the filing. The BANK form
    has a single value column and prints none — every bank sat with
    ``prior = None``, the TTM branch could not close, and fourteen issuers were
    priced off a profit that ended seven months before the balance beside it.
    The issuer's own filing of that quarter is already in this cache.
    """

    def test_a_bank_gets_its_subtrahend_from_the_stored_quarter(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CATALOG_DB_PATH", str(tmp_path / "cat.db"))
        monkeypatch.setenv("FINANCIALS_ENRICH_ON_READ", "0")
        rc.bulk_upsert_financials([
            {"ticker": "ALKB", "year": 2025, "quarter": 2, "net_income": 40.0,
             "revenue": 300.0, "org_type": "bank"},
            {"ticker": "ALKB", "year": 2025, "quarter": 0, "net_income": 100.0,
             "revenue": 700.0, "org_type": "bank"},
            {"ticker": "ALKB", "year": 2026, "quarter": 2, "net_income": 60.0,
             "revenue": 400.0, "org_type": "bank"},
        ])
        served = rc.get_all_financials()["ALKB"]
        assert served["prior"]["year"] == 2025 and served["prior"]["quarter"] == 2
        assert served["prior"]["net_income"] == pytest.approx(40.0)
        assert served["prior"]["source"] == "catalog"
        # …and the TTM the fundamentals layer builds from it closes:
        # 100 + 60 − 40 = 120, not the bare 100 of the annual.
        import fundamentals
        flows = fundamentals.twelve_month_flows(served)
        assert flows["values"]["net_income"] == pytest.approx(120.0)
        assert flows["methods"]["net_income"] == "ttm"

    def test_the_comparative_printed_in_the_filing_wins(self, tmp_path, monkeypatch):
        """A separately filed report cannot net a restatement; the form's own
        comparative can, so it is never overwritten."""
        monkeypatch.setenv("CATALOG_DB_PATH", str(tmp_path / "cat.db"))
        rc.bulk_upsert_financials([
            {"ticker": "UZTL", "year": 2025, "quarter": 2, "net_income": 40.0},
            {"ticker": "UZTL", "year": 2026, "quarter": 2, "net_income": 60.0,
             "prior": {"year": 2025, "quarter": 2, "net_income": 45.0}},
        ])
        served = rc.get_all_financials()["UZTL"]
        assert served["prior"]["net_income"] == pytest.approx(45.0)
        assert served["prior"].get("source") is None

    def test_no_stored_quarter_leaves_the_comparative_absent(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CATALOG_DB_PATH", str(tmp_path / "cat.db"))
        rc.bulk_upsert_financials([
            {"ticker": "NEW", "year": 2026, "quarter": 2, "net_income": 60.0},
        ])
        assert rc.get_all_financials()["NEW"]["prior"] is None

    def test_an_annual_latest_row_asks_for_no_subtrahend(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CATALOG_DB_PATH", str(tmp_path / "cat.db"))
        rc.bulk_upsert_financials([
            {"ticker": "Z", "year": 2024, "quarter": 2, "net_income": 10.0},
            {"ticker": "Z", "year": 2025, "quarter": 0, "net_income": 90.0},
        ])
        served = rc.get_all_financials()["Z"]
        assert served["quarter"] == 0
        assert served["prior"] is None

"""Bank and insurance reports in the plain-language analysis.

The analysis text follows «AI-анализ отчётности: ТЗ по секторам» (2026-10-12):
amounts at scale, words chosen from figures, caveats only in the footnote.
The earlier formulation library (2026-09-24) still sets what may be claimed:
never present an analytical ratio as a regulatory standard, never claim that
loan quality worsened, never mix premiums with insurance revenue, never call
a falling result insolvency.  These tests pin both against the real HMKB
(bank) and UZAS (insurer) filings, so every number below is the filing's own.
"""
from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

import pytest

import financial_analysis.sector_report as financial_analysis_sector_report
from sector_report_service import map_special_lines

TODAY = date(2026, 8, 30)
FILINGS = json.loads((Path(__file__).parent / "fixtures/sector_v22_filings.json").read_text(encoding="utf8"))


def _report(ticker: str, lang: str = "ru") -> dict:
    filing = FILINGS[ticker]
    data = {
        "organization_type": filing["organization_type"], "standard": "nsbu", "scope": "separate",
        "period": "2026Q2", "period_basis": "cumulative_ytd", "previous_comparable_period": "2025Q2",
        "current_values": {}, "previous_values": {}, "opening_values": {},
        "source": filing["source"], "quality": {"data_quality": []},
    }
    map_special_lines(data, filing["workbook"], filing["organization_type"])
    report = financial_analysis_sector_report.make_report(data, filing["issuer"], lang, TODAY, filing["workbook"])
    assert report["status"] == "available", report["data_quality"]
    assert report["content_status"] == "complete"
    return report


@pytest.fixture(scope="module")
def bank() -> str:
    return _report("HMKB")["text"]


@pytest.fixture(scope="module")
def insurer() -> str:
    return _report("UZAS")["text"]


# ── bank ────────────────────────────────────────────────────────────────────

def test_bank_assets_and_loans(bank):
    # The headline states «активы выросли на 7%»; the list adds the amount
    # and the driver without the percent a second time.
    assert "а активы выросли на 7%." in bank and bank.lower().count("активы выросли на 7%") == 1
    assert "Активы выросли до 41,3 трлн сум, за счёт роста кредитного портфеля на 2,62 трлн сум." in bank
    assert "Крупнейшая статья активов — кредитный портфель: большая часть активов." in bank


def test_bank_reserves_never_claim_that_loan_quality_worsened(bank):
    assert "Резервы по кредитам равны 1,7% кредитного портфеля." in bank
    assert "качество портфеля ухудш" not in bank


def test_bank_funding_and_liquidity(bank):
    # Loans above deposits are a multiple, never «172%».
    assert "Кредитный портфель превышает средства клиентов в 1,7 раза." in bank
    assert "Крупнейшая часть средств клиентов — срочные депозиты: около двух третей." in bank
    assert all(float(p.replace(",", ".")) <= 100 for p in re.findall(r"(\d+(?:,\d+)?)%", bank))


def test_bank_income_is_stated_by_shares_not_raw_thousands(bank):
    assert "Процентные расходы забирают около половины процентных доходов." in bank
    assert "Отчисления в резервы забирают около 27% чистого процентного дохода." in bank
    assert "тыс. сум" not in bank and ".00" not in bank


def test_bank_efficiency_and_capital_are_not_presented_as_prudential_ratios(bank):
    assert "Операционные расходы поглощают около половины чистого дохода банка." in bank
    assert "Собственный капитал составляет около пятой части активов." in bank
    assert bank.count("Нормативы ЦБ по этим данным не рассчитываются.") == 1
    for forbidden in ("Базел", "CAR", "норматив достаточности", "(норм.)"):
        assert forbidden not in bank


# ── insurer ─────────────────────────────────────────────────────────────────

def test_insurance_premiums_are_not_mixed_with_revenue(insurer):
    # The headline states «в 2,4 раза»; the list adds the amount, not the multiple again.
    assert "Страховые премии сократились в 2,4 раза, и" in insurer
    assert "Страховые премии снизились до 94,6 млрд сум." in insurer
    assert insurer.count("в 2,4 раза") == 1
    assert "Чистая выручка от страховых услуг значительно выросла на 48% — до 112 млрд сум." in insurer


def test_insurance_premium_retention_is_calculated_from_ceded_premiums(insurer):
    assert "Перестраховщикам уходит небольшая доля (6,8%) премий." in insurer


def test_insurance_service_result_without_an_uncalculable_loss_ratio(insurer):
    assert "Результат от страховых услуг заметно увеличился на 38% — до 61 млрд сум." in insurer
    # Both paces are stated just above; the relation follows without them.
    assert "Расходы на страховые услуги резко выросли на 61% — до 50,9 млрд сум." in insurer
    assert "Расходы на страховые услуги росли быстрее, чем чистая выручка от страховых услуг." in insurer
    assert "коэффициент убыточности" not in insurer.lower()


def test_insurance_technical_reserves(insurer):
    assert "На перестраховщиков приходится более половины страховых резервов." in insurer
    assert "Обязательства снизились на 15% — до 185 млрд сум, за счёт снижения чистых страховых резервов на 23,8 млрд сум." in insurer


# ── conclusions and data limits ─────────────────────────────────────────────

def test_caveats_stand_once_in_the_footnote(bank, insurer):
    for text in (bank, insurer):
        assert text.count("Причины изменений можно подтвердить только примечаниями к отчётности.") == 1
        assert text.rstrip().endswith("отчётности." if text is insurer else "не рассчитываются.")
        assert "НСБУ, отдельная отчётность." in text


def test_a_worse_verdict_names_what_worsened():
    report = _report("UZAS")
    assert report["verdict"]["status"] == "negative"
    assert report["verdict_line"] == "Вердикт: ухудшение — страховые премии снижаются и прибыль снижается."
    assert report["card_text"].endswith(report["verdict_line"])


def test_negative_conclusion_never_claims_insolvency():
    current = {
        "total_assets": 1000, "total_equity": 100, "total_liabilities": 900, "cash": 50,
        "loan_portfolio": 700, "customer_funds": 600, "loan_reserves": 30,
        "interest_income": 100, "interest_expenses": 60, "net_income": 5,
        "operating_expenses": 30, "net_revenue_before_operating_expenses": 45,
    }
    data = {
        "organization_type": "bank", "standard": "nsbu", "scope": "separate",
        "period": "2026Q2", "period_basis": "cumulative_ytd", "previous_comparable_period": "2025Q2",
        "current_values": current,
        "previous_values": {"interest_income": 100, "interest_expenses": 50, "net_income": 20},
        "opening_values": {"total_assets": 900, "total_equity": 110, "total_liabilities": 790,
                           "loan_portfolio": 650, "customer_funds": 580, "loan_reserves": 20, "cash": 60},
        "source": {"document_id": "filing-1", "url": "https://example.org/filing.pdf"},
        "quality": {"data_quality": []},
    }
    bank_issuer = {"id": "BANK", "ticker": "BANK", "name": "Bank", "special_legal_type": "bank"}
    report = financial_analysis_sector_report.make_report(data, bank_issuer, "ru", TODAY)
    assert report["verdict"]["status"] == "negative"
    assert report["verdict"]["reason"] == "прибыль снижается и доля капитала снижается"
    text = report["text"].lower()
    for claim in ("неплатёжеспособ", "банкрот", "нарушени", "качество портфеля ухудш"):
        assert claim not in text


@pytest.mark.parametrize("ticker", ["HMKB", "UZAS"])
@pytest.mark.parametrize("lang", ["uz", "en"])
def test_translations_follow_the_same_rules(ticker, lang):
    report = _report(ticker, lang)
    text = report["text"]
    assert not re.search(r"[А-Яа-яЁё]", text)
    assert report["text_checks"]["status"] == "passed"
    assert {"uz": "BHMS", "en": "NSBU"}[lang] in report["footnote"]


# ── structure ───────────────────────────────────────────────────────────────

def test_insurer_blocks_follow_the_six_block_order():
    report = _report("UZAS")
    assert [section["id"] for section in report["sections"]] == [
        "headline", "key_points", "results", "balance", "strength", "risks", "footnote"]
    assert [section["title"] for section in report["sections"] if section["title"]] == [
        "Главное", "Результаты", "Баланс", "Устойчивость", "Риски и что смотреть дальше"]
    labels = {fact["metric"]: fact["label"] for fact in report["verified_facts"]}
    assert labels["revenue"] == "Чистая выручка от страховых услуг"


def test_a_deepening_loss_is_shown_as_amounts_and_not_as_a_percent():
    report = _report("UZAS")
    change = next(item["text"] for item in report["key_changes"] if item["code"] == "operating_income")
    assert change == "Операционный убыток вырос с 1,88 до 5,55 млрд сум."
    assert "196%" not in report["text"] and "−195" not in report["text"]


def test_no_double_spaces(bank, insurer):
    assert "  " not in bank and "  " not in insurer

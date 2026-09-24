"""Bank and insurance reports speak the customer's formulation library.

Source: «Библиотека аналитических формулировок — банковский и страховой секторы
(НСБУ)», supplied 2026-09-24.  Its rules: metric → direction → factor → caveat;
never equate a change with its cause; never present an analytical ratio as a
regulatory standard; never calculate a metric whose source lines are missing;
in insurance, never mix premiums, insurance revenue, insurance result and net
profit.  These tests pin those phrases against the real HMKB (bank) and UZAS
(insurer) filings, so every number below is the filing's own arithmetic.
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

import sector_analysis as core
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
    report = core.make_report(data, filing["issuer"], lang, TODAY, filing["workbook"])
    assert report["status"] == "available", report["data_quality"]
    assert report["content_status"] == "complete"
    return report


@pytest.fixture(scope="module")
def bank() -> str:
    return _report("HMKB")["text"]


@pytest.fixture(scope="module")
def insurer() -> str:
    return _report("UZAS")["text"]


# ── 01 · bank: assets and loan portfolio ────────────────────────────────────

def test_bank_assets_and_loans(bank):
    assert "Активы банка за период увеличились на 6.99%, главным образом за счёт роста кредитного портфеля." in bank
    assert "Кредитный портфель рос быстрее активов: 9.95% против 6.99%. В структуре баланса усилилась роль кредитования." in bank
    assert "Основную часть активов составляет «Кредитный портфель» — 70.20%. Такая структура указывает на значительную концентрацию баланса в этом направлении." in bank
    assert "Доля «Кредитный портфель» в активах выросла с 68.31% до 70.20%, что отражает изменение структуры активов." in bank


# ── 01 · bank: loan quality and reserves ────────────────────────────────────

def test_bank_reserves_use_the_gross_portfolio_and_never_claim_deterioration(bank):
    assert "Резервы под кредитные потери увеличились на 17.42%, тогда как валовой кредитный портфель вырос на 10.06%." in bank
    assert ("Резервы росли быстрее кредитного портфеля. Это требует внимания, однако без данных о просрочке "
            "и классификации кредитов нельзя однозначно заключить, что качество портфеля ухудшилось.") in bank
    assert ("Отношение резервов к валовому кредитному портфелю составило 1.63% против 1.52%. "
            "Это аналитический коэффициент на основе отчётности, а не регуляторный норматив.") in bank
    assert "нет достаточной детализации по просроченным и обесцененным кредитам" in bank
    assert "Рост резервов может отражать как увеличение кредитного риска, так и изменение оценки ожидаемых потерь." in bank


# ── 01 · bank: deposits, funding and liquidity ──────────────────────────────

def test_bank_funding_and_liquidity(bank):
    assert "Средства клиентов увеличились на 15.28%, опережая рост активов на 8.29 п.п. В отчётности это соответствует усилению клиентской ресурсной базы." in bank
    assert ("Расчётное отношение кредитного портфеля к средствам клиентов (LDR) составляет 172.42%. Показатель описывает "
            "соотношение двух статей баланса и не является самостоятельной оценкой платёжеспособности банка.") in bank
    assert "Доля средств до востребования выросла." in bank
    assert "без данных о сроках активов и обязательств нельзя определить влияние на риск ликвидности" in bank
    assert "Денежные средства и средства в центральном и других банках сократились на 19.21%." in bank
    assert "Снижение отдельных денежных остатков сопровождается ростом кредитного портфеля." in bank
    assert "не позволяет само по себе сделать вывод о дефиците ликвидности" in bank


# ── 01 · bank: income and profitability ─────────────────────────────────────

def test_bank_income_and_profitability(bank):
    assert "Чистый процентный доход до оценки кредитных потерь составил 1 474 187 985.00 тыс. сум. После учёта расходов на оценку потерь он составил 994 645 347.00 тыс. сум." in bank
    assert "Расходы на оценку кредитных потерь уменьшили чистый процентный результат на 27.50%. Их влияние существенно" in bank
    assert "Основной вклад в доходы до операционных расходов внесли процентные операции." in bank
    assert "Чистый результат по валютным операциям составил 375 481 140.00 тыс. сум и оказал положительное влияние на прибыль периода." in bank
    assert "Рентабельность активов (ROA), рассчитанная по доступным данным, составила" in bank
    assert "с использованием средних активов" in bank
    assert "Рентабельность капитала (ROE) составила" in bank
    assert "пересчёту неполного года" in bank


# ── 01 · bank: efficiency and capital ───────────────────────────────────────

def test_bank_efficiency_and_capital_are_not_presented_as_prudential_ratios(bank):
    assert ("Операционные расходы составили 49.88% от выбранной базы операционных доходов (Cost-to-Income). "
            "В расчёте использована формула: операционные расходы / чистый доход до операционных расходов.") in bank
    assert "Капитал вырос на 7.00%, а активы — на 6.99%. Балансовое соотношение капитала к активам изменилось с 18.57% до 18.58%." in bank
    assert "не является нормативом достаточности капитала" in bank
    assert "нельзя подтвердить соблюдение банковских пруденциальных нормативов" in bank
    for forbidden in ("Базел", "CAR", "норма:", "(норм.)"):
        assert forbidden not in bank


# ── 02 · insurance: premiums ────────────────────────────────────────────────

def test_insurance_premiums_are_not_mixed_with_revenue(insurer):
    assert "это разные показатели и этапы учёта" in insurer
    assert "Объём страховых премий за период составил 94 587 125.90 тыс. сум." in insurer
    assert "Премии сократились на 57.78%. Для оценки устойчивости этой динамики нужны сопоставимые данные по видам страхования и каналам продаж." in insurer
    assert ("Премии снизились на 57.78%, тогда как чистая выручка от страховых услуг изменилась на 47.62%. "
            "Показатели отражают разные этапы учёта, поэтому их нельзя считать взаимозаменяемыми.") in insurer


# ── 02 · insurance: reinsurance and retention ───────────────────────────────

def test_insurance_premium_retention_is_calculated_from_ceded_premiums(insurer):
    assert "Переданные перестраховщикам премии составили 6.82% от валовых премий — против 78.78% в сопоставимом периоде." in insurer
    assert "Расчётные удержанные премии составили 88 133 432.30 тыс. сум: валовые премии за вычетом переданных перестраховщикам премий." in insurer
    assert "Доля удержания премий составила 93.18%. Это расчёт по премиям и не тождественно доле удержания страховых убытков." in insurer
    assert "одной отчётности недостаточно, чтобы установить причину" in insurer
    assert "премиального потока" not in insurer  # the share fell; the «increase» phrase must not appear
    assert "нельзя рассчитывать без раскрытых переданных премий" not in insurer


# ── 02 · insurance: services, claims and result ─────────────────────────────

def test_insurance_service_result_and_uncalculable_ratios(insurer):
    assert "Доход от страховых услуг составил 111 891 908.50 тыс. сум. Показатель отражает признанный в отчётности доход за период, а не обязательно сумму начисленных премий." in insurer
    assert "Расходы на страховые услуги увеличились на 61.34%, опережая рост чистой выручки на 13.72 п.п." in insurer
    assert "Результат от страховых услуг составил 60 980 509.30 тыс. сум против 44 241 937.60 тыс. сум годом ранее; изменение обусловлено динамикой выручки и расходов на страховые услуги." in insurer
    assert "коэффициент убыточности по доступным данным не рассчитывается" in insurer
    assert "Комбинированный коэффициент не рассчитывается" in insurer


# ── 02 · insurance: technical reserves ──────────────────────────────────────

def test_insurance_technical_reserves(insurer):
    assert "Валовые технические резервы составили 261 035 521.40 тыс. сум, доля перестраховщиков — 156 509 821.10 тыс. сум, расчётные резервы за вычетом доли перестраховщиков — 104 525 700.30 тыс. сум." in insurer
    assert "Валовые резервы снизились на 20.63%, а доля перестраховщиков — на 21.99%." in insurer
    assert "Расчётные чистые технические резервы снизились на 18.52%. Это изменение балансовой оценки обязательств и само по себе не является мерой прибыльности." in insurer
    assert "Доля перестраховщиков в технических резервах составила 59.96%. Это показывает их участие в отражённых резервах, но не подтверждает фактическое получение возмещений." in insurer
    assert "нельзя определить достаточность резервов относительно будущих выплат без актуарной оценки" in insurer


# ── 02 · insurance: profitability ───────────────────────────────────────────

def test_insurance_profit_is_split_into_its_sources(insurer):
    assert "Финансовый результат поддержал чистую прибыль на 6 125 348.10 тыс. сум." in insurer
    assert "Чистый валютный результат составил 108 057.10 тыс. сум против -670 786.30 тыс. сум. Его изменение поддержало итоговую прибыль." in insurer
    assert "важно разделять страховой результат, инвестиционный и прочий финансовый результат, а также влияние налога" in insurer
    # Net profit fell, so the «growth of net profit» phrasing must not appear.
    assert "рост чистой прибыли не следует" not in insurer


# ── 03 · conclusions and data limits ────────────────────────────────────────

def test_both_sectors_close_with_the_nsbu_limitation(bank, insurer):
    for text in (bank, insurer):
        assert "Вывод основан на доступных формах НСБУ за 2026Q2 и не заменяет оценку по регуляторной отчётности." in text


def test_mixed_conclusion_names_what_improved_and_what_worsened(insurer):
    assert ("Картина неоднородная: показатель «чистая выручка от страховых услуг» улучшился, "
            "тогда как показатель «чистая прибыль» ухудшился.") in insurer
    assert "Ключевой вопрос для дальнейшего наблюдения — дальнейшая динамика показателя «чистая прибыль»." in insurer


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
    report = core.make_report(data, bank_issuer, "ru", TODAY)
    assert report["verdict"]["status"] == "negative"
    text = report["text"]
    assert "За период ухудшился показатель «чистая прибыль», что оказало давление на прибыльность." in text
    assert "Наблюдаемая динамика требует внимания, но не позволяет самостоятельно заключить о нарушении нормативов или неплатёжеспособности." in text
    # Reserves grew while the loan book grew slower: quality caveat, never a verdict.
    assert "нельзя однозначно заключить, что качество портфеля ухудшилось" in text


@pytest.mark.parametrize("ticker", ["HMKB", "UZAS"])
@pytest.mark.parametrize("lang", ["uz", "en"])
def test_translations_carry_the_same_caveats(ticker, lang):
    text = _report(ticker, lang)["text"]
    markers = {
        ("HMKB", "en"): ["not a regulatory standard", "does not by itself assess the bank's solvency", "prudential"],
        ("HMKB", "uz"): ["regulyativ me’yor emas", "to‘lov qobiliyatini", "prudensial"],
        ("UZAS", "en"): ["different accounting stages", "loss ratio is not calculated", "actuarial"],
        ("UZAS", "uz"): ["hisobning turli bosqichlari", "zararlilik koeffitsiyenti", "aktuar"],
    }[(ticker, lang)]
    for marker in markers:
        assert marker in text, marker
    assert "НСБУ" not in text or lang == "ru"


# ── readability fixes found while reviewing the generated text ──────────────

def test_insurer_sections_are_titled_by_their_content():
    report = _report("UZAS")
    assert [section["title"] for section in report["sections"]] == [
        "Общие сведения и методология анализа", "Технические резервы и перестраховщики",
        "Перестрахование и удержание риска", "Премии, страховые услуги и прибыльность",
        "Коэффициентный анализ", "Вердикт",
    ]
    labels = {fact["metric"]: fact["label"] for fact in report["verified_facts"]}
    assert labels["revenue"] == "Чистая выручка от страховых услуг"


def test_a_deepening_loss_is_shown_as_amounts_and_not_as_a_divergence():
    report = _report("UZAS")
    change = next(item["text"] for item in report["key_changes"] if item["code"] == "profit_divergence")
    assert change == "Операционный результат: -1 876 050.20 → -5 547 703.40 тыс. сум, а чистая прибыль снизилась на 91.59%."
    assert "Операционный результат изменился на -195.71%" not in report["text"]


def test_expense_sentence_starts_with_a_capital_and_no_double_spaces(bank):
    assert "Расходы и стоимость ресурсов. Процентные расходы" in bank
    assert "  " not in bank

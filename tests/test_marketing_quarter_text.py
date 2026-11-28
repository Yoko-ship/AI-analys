"""Quarter labels must match the financial interval of the displayed flow."""
import pytest


def material(body, *, start="2026-01-01", amount=900, calculation=None):
    item = {"rubric": "quarterly", "period": "2026Q3", "title": "HMKB · Q3 analysis", "body": body,
            "claims": [{"evidence_id": "profit", "field": "net_income", "value": amount, "unit": "thousand UZS"}],
            "calculation": calculation}
    original = {"id": "profit", "period_start": start, "period": "2026-09-30", "period_kind": "cumulative" if start.endswith("01-01") else "quarter",
                "data": {"net_income": amount}, "units": {"net_income": "thousand UZS"}}
    return item, [original]


@pytest.mark.parametrize("body", [
    "Чистая прибыль за III квартал — 900 тыс. сум.",
    "Чистая прибыль за 3-й квартал — 900 тыс. сум.",
    "Q3 net income was 900 thousand UZS.",
    "Net profit for the third quarter: 900 thousand UZS.",
    "III chorak sof foyda: 900 ming so‘m.",
    "3-chorak uchun sof foyda — 900 ming so‘m.",
    "Чистая прибыль за квартал — 900 тыс. сум.",
    "Quarterly net income: 900 thousand UZS.",
    "Choraklik sof foyda — 900 ming so‘m.",
])
def test_cumulative_profit_cannot_be_relabelled_as_a_standalone_quarter(body):
    from marketing import quarter_text
    assert quarter_text.check(*material(body))


@pytest.mark.parametrize("body", [
    "Чистая прибыль за девять месяцев — 900 тыс. сум.",
    "Net income for nine months: 900 thousand UZS.",
    "To‘qqiz oy uchun sof foyda — 900 ming so‘m.",
    "В разборе III квартала чистая прибыль за девять месяцев — 900 тыс. сум.",
])
def test_quarter_analysis_heading_does_not_change_explicit_cumulative_figures(body):
    from marketing import quarter_text
    assert not quarter_text.check(*material(body))


@pytest.mark.parametrize("body", ["Чистая прибыль за III квартал — 300 тыс. сум.",
                                  "Q3 net income: 300 thousand UZS.", "III chorak sof foyda — 300 ming so‘m."])
def test_an_explicit_standalone_original_can_support_quarter_wording(body):
    from marketing import quarter_text
    assert not quarter_text.check(*material(body, start="2026-07-01", amount=300))


@pytest.mark.parametrize("displayed,passed", [(300, True), (900, False)])
def test_quarter_difference_must_be_the_displayed_result_not_a_sidecar_excuse(displayed, passed):
    from marketing import quarter_text
    item, rows = material(f"Чистая прибыль за III квартал — {displayed} тыс. сум. Расчёт: 900 − 600 = 300.",
                          calculation={"operation": "difference", "field": "net_income", "left": "profit", "right": "half", "value": 300})
    rows.append({**rows[0], "id": "half", "period": "2026-06-30", "data": {"net_income": 600}})
    assert (not quarter_text.check(item, rows)) is passed


def test_missing_start_wrong_quarter_and_wrong_scale_are_not_proof():
    from marketing import quarter_text
    assert quarter_text.check(*material("Чистая прибыль за III квартал — 900 тыс. сум.", start=""))
    assert quarter_text.check(*material("Чистая прибыль за II квартал — 300 тыс. сум.", start="2026-07-01", amount=300))
    assert quarter_text.check(*material("Чистая прибыль за III квартал — 300 сум.", start="2026-07-01", amount=300))
    assert quarter_text.check(*material("Чистая прибыль за III квартал — 900."))


@pytest.mark.parametrize("body", ["Чистая прибыль за шесть месяцев — 900 тыс. сум.",
                                  "Net income for six months: 900 thousand UZS.",
                                  "Olti oy uchun sof foyda — 900 ming so‘m."])
def test_an_explicit_cumulative_duration_must_also_match_the_original(body):
    from marketing import quarter_text
    assert quarter_text.check(*material(body))


def test_a_correctly_labeled_half_year_comparison_remains_usable_in_q3_analysis():
    from marketing import quarter_text
    item, rows = material("Чистая прибыль за шесть месяцев — 600 тыс. сум.", amount=600)
    rows[0]["period"] = "2026-06-30"
    assert not quarter_text.check(item, rows)


def test_cumulative_label_needs_a_known_start_and_cannot_hide_a_second_amount():
    from marketing import quarter_text
    assert quarter_text.check(*material("Чистая прибыль за девять месяцев — 900 тыс. сум.", start=""))
    assert quarter_text.check(*material("Чистая прибыль за девять месяцев — 900 тыс. сум. и 600 тыс. сум."))


@pytest.mark.parametrize("claimed", ["revenue", "total_assets"])
def test_another_metric_claim_cannot_excuse_unproved_quarter_profit(claimed):
    from marketing import quarter_text
    item, rows = material("Чистая прибыль за III квартал — 900 тыс. сум.")
    item["claims"][0]["field"] = claimed
    rows[0]["data"] = {claimed: 900}
    rows[0]["units"] = {claimed: "thousand UZS"}
    assert quarter_text.check(item, rows)

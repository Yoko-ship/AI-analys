"""Visible dividend statements must agree with their original, in every rubric.

The ORFI 4061 amount/classes are the observed calendar case already preserved in
test_dividends_capitalisation_t16. The proposed/paid states and bad copy below
are controlled alternatives, not assertions that ORFI made those announcements.
"""
import pytest

from marketing import content, store
from test_marketing_core import NOW, account, candidate, evidence, isolated  # noqa: F401


def decision(state="approved", share_class="ordinary"):
    return evidence(entity="ORFI", url="https://openinfo.uz/facts/32/4061",
        data={"dividend": 458.88, "dividend_state": state, "share_class": share_class},
        excerpt="Утверждено 458,88 сум на простую акцию.")


def material(body, *, language="ru", rubric="dividend", title="ORFI", **changes):
    return candidate("orfi-4061", entity="ORFI", rubric=rubric, title=title, body=body, language=language,
        claims=[{"evidence_id": "decision", "field": field, "value": value, "unit": unit} for field, value, unit in [
            ("dividend", 458.88, "UZS/share"), ("dividend_state", "approved", ""), ("share_class", "ordinary", "")]], **changes)


@pytest.mark.parametrize("rubric", ["dividend", "news"])
@pytest.mark.parametrize("body,language", [
    ("Выплачено 458,88 сум на простую акцию.", "ru"),
    ("Дивиденд утверждён: 458,88 сум на простую акцию. Деньги перечислены.", "ru"),
    ("Oddiy aksiya uchun 458,88 so‘m dividend to‘landi.", "uz"),
    ("Dividend tasdiqlandi. Oddiy aksiya uchun 458,88 so'm to'lab berildi.", "uz"),
    ("Paid 458.88 UZS per ordinary share.", "en"),
])
def test_approved_decision_never_becomes_paid_copy(body, language, rubric):
    account(rubrics=[rubric], languages=[language])
    decision()
    item = material(body, language=language, rubric=rubric)
    checked = content.check_candidate(item["id"], NOW)
    assert checked["status"] == "skipped"
    assert "Dividend wording" in checked["check"]["reason"]
    # Re-triggering cannot revive an automatic semantic failure.
    assert material(body, language=language, rubric=rubric)["status"] == "skipped"
    with store.connection() as c:
        assert store.list_items(c, "delivery") == []


@pytest.mark.parametrize("body,language", [
    ("Утверждено 458,88 сум на простую акцию. Дата выплаты не объявлена.", "ru"),
    ("Утверждено 458,88 сум на простую акцию; дивиденд ещё не выплачен.", "ru"),
    ("Утверждено 458,88 сум на простую акцию. Выплата не подтверждена.", "ru"),
    ("Утверждено 458,88 сум на простую акцию. Выплата планируется.", "ru"),
    ("Oddiy aksiya uchun 458,88 so‘m dividend tasdiqlandi. Hali to‘lanmagan.", "uz"),
    ("Oddiy aksiya uchun 458,88 so'm dividend tasdiqlangan. To'lov sanasi noma'lum.", "uz"),
    ("Approved 458.88 UZS per ordinary share. It has not been paid yet.", "en"),
])
def test_approval_copy_and_explicitly_unconfirmed_payment_remain_publishable(body, language):
    account(rubrics=["dividend"], languages=[language])
    decision()
    checked = content.check_candidate(material(body, language=language)["id"], NOW)
    assert checked["status"] == "ready", checked["check"]["reason"]


@pytest.mark.parametrize("body,field,value", [
    ("Утверждено 458,88 сум на простую акцию.", "dividend_state", "proposed"),
    ("Предложено 458,88 сум на простую акцию.", "dividend_state", "approved"),
    ("Утверждено 458,88 сум на простую акцию.", "dividend_state", "paid"),
    ("Выплачено 458,88 сум на простую акцию. Дивиденд не выплачен.", "dividend_state", "paid"),
    ("Утверждено 458,88 сум на привилегированную акцию.", "share_class", "ordinary"),
    ("Утверждено 458,88 USD на простую акцию.", "share_class", "ordinary"),
    ("Утверждено 458,88 тыс. сум на простую акцию.", "share_class", "ordinary"),
    ("Утверждено 458,88% на простую акцию.", "share_class", "ordinary"),
    ("Утверждено 458,88 сум.", "share_class", "ordinary"),
])
def test_visible_state_class_and_amount_unit_are_required_not_just_sidecar_fields(body, field, value):
    from marketing import checks
    source = decision(state=value if field == "dividend_state" else "approved")
    item = material(body)
    for claim in item["claims"]:
        if claim["field"] == field:
            claim["value"] = value
    failures = checks.check(item, {"decision": source}, NOW, {})
    assert any("Dividend" in failure for failure in failures)


@pytest.mark.parametrize("state,body", [
    ("proposed", "Предложено 458,88 сум на простую акцию."),
    ("paid", "Выплачено 458,88 сум на простую акцию."),
])
def test_confirmed_proposal_and_payment_have_their_own_visible_states(state, body):
    from marketing import checks
    source = decision(state)
    item = material(body)
    item["claims"][1]["value"] = state
    assert checks.check(item, {"decision": source}, NOW, {}) == []


def test_a_paid_headline_cannot_be_hidden_by_an_accurate_approved_body():
    account(rubrics=["dividend"])
    decision()
    item = material("Утверждено 458,88 сум на простую акцию.", title="ORFI выплатил дивиденд")
    checked = content.check_candidate(item["id"], NOW)
    assert checked["status"] == "skipped"


def test_a_payment_window_does_not_substitute_for_the_state_of_a_news_claim():
    account()
    evidence(entity="ORFI", data={"dividend": 458.88, "share_class": "ordinary", "payment_end": "2026-08-25"})
    checked = content.check_candidate(material("Выплачено 458,88 сум на простую акцию.", rubric="news")["id"], NOW)
    assert checked["status"] == "skipped"
    assert "Dividend" in checked["check"]["reason"]


@pytest.mark.parametrize("field,value", [("dividend_state", ["approved"]), ("share_class", {"name": "ordinary"})])
def test_untyped_source_fields_block_release_without_crashing(field, value):
    from marketing import checks
    source = decision()
    source["data"][field] = value
    assert checks.check(material("Утверждено 458,88 сум на простую акцию."), {"decision": source}, NOW, {})


def test_different_originals_cannot_supply_amount_and_state_for_each_other():
    from marketing import checks
    source = decision()
    source["data"].pop("dividend_state")
    other = {**source, "id": "other", "data": {"dividend_state": "approved"}}
    item = material("Утверждено 458,88 сум на простую акцию.")
    item["evidence_ids"].append("other")
    item["claims"][1]["evidence_id"] = "other"
    assert any("Dividend" in reason for reason in checks.check(item, {"decision": source, "other": other}, NOW, {}))

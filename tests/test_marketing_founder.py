"""Personal posts use owner-confirmed wording and versioned proof."""
import pytest

from marketing import content, delivery, store
from marketing.errors import MarketingError
from test_marketing_core import OWNER, NOW, account, candidate, evidence, isolated  # noqa: F401


def fact_data(**changes):
    return {"title": "Роль в UZStock", "category": "role", "proof_url": "https://uzstock.uz/about",
            "verification_note": "Владелец сверил роль и разрешает эту формулировку.",
            "wordings": {"ru": ["Я развиваю UZStock."], "uz": ["Men UZStock loyihasini rivojlantiryapman."]},
            "status": "verified", "valid_until": "2026-12-31T23:59:00Z", **changes}


def personal(**changes):
    account("personal", platform="linkedin", personal_profile=True, mode="automatic")
    evidence()
    return candidate(target="personal", body="Я развиваю UZStock. Утверждено 120 сум на простую акцию.", founder_fact_ids=["founder-role"], **changes)


def test_a_nonexistent_fact_id_does_not_authorize_an_invented_personal_claim():
    item = personal()
    checked = content.check_candidate(item["id"], NOW)
    assert checked["status"] == "skipped"
    assert "founder" in checked["check"]["reason"].lower()


def test_verified_wording_is_bound_to_this_language_and_rejects_invented_experience():
    from marketing import founder
    founder.save(OWNER, "founder-role", fact_data(), 0)
    item = personal()
    checked = content.check_candidate(item["id"], NOW)
    assert checked["status"] == "ready" and checked["check"]["founder_versions"] == {"founder-role": 1}
    fabricated = candidate(event="invented-experience", target="personal", body="Я управлял крупным инвестиционным фондом. Утверждено 120 сум на простую акцию.", founder_fact_ids=["founder-role"])
    assert content.check_candidate(fabricated["id"], NOW)["status"] == "skipped"


def test_fact_revocation_invalidates_already_scheduled_automatic_personal_post():
    from marketing import founder
    saved = founder.save(OWNER, "founder-role", fact_data(), 0)
    item = personal()
    content.check_candidate(item["id"], NOW)
    delivery.schedule(item["id"], NOW)
    founder.save(OWNER, "founder-role", fact_data(status="disabled"), saved["version"])
    class NoSend:
        def publish(self, *args):
            pytest.fail("Revoked personal wording reached transport")
    assert not delivery.run_one(NoSend(), NOW)
    with store.connection() as c:
        assert store.get(c, "candidate", item["id"])["status"] == "skipped"


def test_founder_map_is_owner_only_and_requires_reviewable_proof():
    from marketing import founder
    with pytest.raises(MarketingError, match="owner"):
        founder.save({"id": "pr", "role": "pr"}, "founder-role", fact_data(), 0)
    with pytest.raises(ValueError):
        founder.save(OWNER, "founder-role", fact_data(verification_note=""), 0)
    with pytest.raises(MarketingError):
        founder.save(OWNER, "founder-role", fact_data(proof_url="javascript:alert(1)"), 0)


def test_actual_founder_map_reaches_model_context_and_unsupported_ids_cannot_start():
    from marketing import agents, founder
    from test_marketing_production import ProductionModel, brief, prepare_accounts
    prepare_accounts()
    founder.save(OWNER, "founder-role", fact_data(), 0)
    agents.start(OWNER, kind="content", message="Учесть роль основателя", evidence_ids=["decision"], production=brief(founder_fact_ids=["founder-role"]))
    model = ProductionModel()
    agents.run_one(model, NOW)
    assert model.calls[0][1]["founder_facts"][0]["wordings"]["ru"] == ["Я развиваю UZStock."]
    with pytest.raises(MarketingError):
        agents.start(OWNER, kind="content", message="Missing map", evidence_ids=["decision"], production=brief(event_id="missing-map", founder_fact_ids=["missing"]))

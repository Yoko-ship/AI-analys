"""Real role checkpoints produce reviewable drafts, never publication authority."""
import json

import pytest

from marketing import agents, content, store
from test_marketing_core import OWNER, NOW, account, evidence, isolated  # noqa: F401
from test_marketing_agents import output


def brief(**changes):
    return {"event_id": "hmkb-decision-123", "rubric": "news", "entity": "HMKB", "period": "", "destination_url": "https://uzstock.uz/news/123",
            "expires_at": "2026-11-24T07:00:00Z", "mode": "draft",
            "targets": [{"account_id": name, "languages": ["ru", "uz"], "primary_language": "ru", "format": "post"}
                        for name in ("telegram", "instagram", "facebook", "linkedin")], **changes}


def prepare_accounts(mode="draft"):
    for name in ("telegram", "instagram", "facebook", "linkedin"):
        account(name, platform=name, mode=mode, languages=["ru", "uz"], personal_profile=name == "linkedin")
    evidence()


class ProductionModel:
    def __init__(self, *, reject=None, foreign_account=False):
        self.calls = []
        self.reject = reject
        self.foreign_account = foreign_account

    def complete_json(self, system, user, **options):
        context = json.loads(user)
        self.calls.append((system, context))
        if 'You are UZStock\'s copywriter ' in system:
            drafts = []
            for target in context["production"]["targets"]:
                for language in target["languages"]:
                    platform = next(a["platform"] for a in context["accounts"] if a["id"] == target["account_id"])
                    body = f"{platform}: Утверждено 120 сум на простую акцию." if language == "ru" else f"{platform}: Oddiy aksiya uchun 120 so‘m dividend tasdiqlandi."
                    drafts.append({"account_id": "foreign" if self.foreign_account else target["account_id"],
                        "language": language, "title": f"{platform} · решение" if language == "ru" else f"{platform} · qaror",
                        "body": body, "evidence_ids": ["decision"], "claims": [{"evidence_id": "decision", "field": "dividend", "value": 120, "unit": "UZS/share"}],
                        "destination_url": "https://uzstock.uz/news/123", "founder_fact_ids": []})
            return output("Отдельные версии подготовлены", drafts=drafts)
        if 'You are UZStock\'s quality ' in system:
            reviews = [{"draft_id": draft["id"], "draft_digest": draft["digest"],
                        "verdict": "reject" if draft["account_id"] == self.reject else "accept",
                        "reason": "Unsupported central claim" if draft["account_id"] == self.reject else "Compared with supplied originals",
                        "fragments": []} for draft in context["drafts"]]
            return output("Проверка каждого варианта завершена", reviews=reviews)
        return output("Использовать подтверждённое решение и сохранить ограничения")


def run_team(model, count=8):
    for _ in range(count):
        assert agents.run_one(model, NOW)


@pytest.mark.parametrize("destination,expected", [("https://uzstock.uz/news/123", "ready"),
                                                ("https://uzstock.uz/news/another-decision", "skipped")])
def test_owner_selected_destination_is_pinned_to_generated_content(destination, expected):
    prepare_accounts(mode="automatic")
    scope = brief(mode="account", destination_url=destination,
                  targets=[{"account_id": "telegram", "languages": ["ru"], "primary_language": "ru", "format": "post"}])
    task = agents.start(OWNER, kind="content", message="Use the exact owner-selected article", evidence_ids=["decision"], production=scope)
    model = ProductionModel()
    run_team(model)
    with store.connection() as c:
        item, = store.list_items(c, "candidate")
        assert item["status"] == expected
        assert store.get(c, "task", task["id"])["production"]["destination_url"] == destination
    assert model.calls[0][1]["production"]["destination_url"] == destination


def test_generated_draft_with_no_reviewed_destination_stays_unchecked():
    prepare_accounts()
    scope = brief(destination_url="", targets=[{"account_id": "telegram", "languages": ["ru"], "primary_language": "ru", "format": "post"}])
    agents.start(OWNER, kind="content", message="Do not invent a source destination", evidence_ids=["decision"], production=scope)
    run_team(ProductionModel())
    with store.connection() as c:
        item, = store.list_items(c, "candidate")
        assert item["status"] == "needs_revision" and not item["check"]["passed"]
        assert "destination" in item["check"]["reason"].lower()


def test_owner_can_supply_a_missing_destination_in_an_existing_internal_draft():
    from marketing import production
    prepare_accounts()
    scope = brief(destination_url="", targets=[{"account_id": "telegram", "languages": ["ru", "uz"], "primary_language": "ru", "format": "post"}])
    agents.start(OWNER, kind="content", message="Prepare an internal draft awaiting the real link", evidence_ids=["decision"], production=scope)
    run_team(ProductionModel())
    with store.connection() as c:
        item, = store.list_items(c, "candidate")
    assert item["status"] == "needs_revision"
    with store.connection() as c:
        uz = next(variant for variant in store.list_items(c, "draft_variant") if variant["language"] == "uz")
    item = production.select_variant(OWNER, uz["id"], item["version"], now=NOW)
    assert item["status"] == "needs_revision" and not item.get("destination_review")
    revised = content.revise_candidate(OWNER, item["id"], {"destination_url": "https://uzstock.uz/news/123"}, item["version"])
    checked = content.check_candidate(revised["id"], NOW)
    assert checked["status"] == "draft" and checked["check"]["passed"]
    assert checked["destination_review"]["actor"] == OWNER["id"]
    assert checked["destination_review"]["url"] == checked["destination_url"]
    with store.connection() as c:
        assert not store.list_items(c, "delivery")


def test_team_saves_distinct_four_platform_ru_uz_variants_without_eight_publications():
    prepare_accounts()
    task = agents.start(OWNER, kind="content", message="Подготовить решение для четырёх площадок на RU/UZ", evidence_ids=["decision"], production=brief())
    model = ProductionModel()
    run_team(model)
    with store.connection() as c:
        variants = store.list_items(c, "draft_variant")
        assert len(variants) == 8
        assert len({variant["body"] for variant in variants}) == 8
        saved = store.get(c, "task", task["id"])
        assert saved["status"] == "complete" and len(saved["candidate_ids"]) == 4
        candidates = store.list_items(c, "candidate")
        assert len(candidates) == 4
        assert {candidate["language"] for candidate in candidates} == {"ru"}
        assert store.list_items(c, "delivery") == []
        assert all("external_id" not in a for a in model.calls[0][1]["accounts"])
    repeated = agents.start(OWNER, kind="content", message="Повторный сигнал", evidence_ids=["decision"], production=brief())
    assert repeated["id"] == task["id"]


def test_quality_rejection_terminates_only_that_automatic_material_and_cannot_be_rewritten():
    prepare_accounts(mode="automatic")
    scope = brief(mode="account", targets=[{"account_id": p, "languages": ["ru"], "primary_language": "ru", "format": "post"} for p in ("telegram", "facebook")])
    task = agents.start(OWNER, kind="content", message="Подготовить органику в разрешённых границах", evidence_ids=["decision"], production=scope)
    run_team(ProductionModel(reject="telegram"))
    with store.connection() as c:
        items = {item["account_id"]: item for item in store.list_items(c, "candidate")}
        assert items["telegram"]["status"] == "skipped"
        assert items["facebook"]["status"] == "ready"
        assert len(store.get(c, "task", task["id"])["outputs"]) == 8
    assert not agents.run_one(ProductionModel(), NOW)
    assert content.create_candidate({key: items["telegram"][key] for key in content.Candidate.model_fields})["status"] == "skipped"


def test_model_cannot_add_a_recipient_outside_the_owner_brief():
    prepare_accounts()
    task = agents.start(OWNER, kind="content", message="Только выбранные аккаунты", evidence_ids=["decision"], production=brief())
    run_team(ProductionModel(foreign_account=True), count=6)
    with store.connection() as c:
        assert store.get(c, "task", task["id"])["status"] == "error"
        assert store.list_items(c, "candidate") == []
        assert store.list_items(c, "draft_variant") == []


def test_secondary_language_replaces_the_same_manual_candidate_and_invalidates_approval():
    from marketing import production
    prepare_accounts(mode="manual")
    planned = "2026-11-23T15:00:00+05:00"
    task = agents.start(OWNER, kind="content", message="Два языка", evidence_ids=["decision"], production=brief(mode="account", not_before=planned))
    run_team(ProductionModel())
    with store.connection() as c:
        ru = next(item for item in store.list_items(c, "candidate") if item["account_id"] == "telegram")
        uz = next(item for item in store.list_items(c, "draft_variant") if item["account_id"] == "telegram" and item["language"] == "uz")
    approved = content.approve_candidate(OWNER, ru["id"], ru["version"])
    selected = production.select_variant(OWNER, uz["id"], approved["version"], now=NOW)
    assert selected["id"] == ru["id"] and selected["language"] == "uz"
    assert selected["approval"] is None and selected["status"] == "awaiting_approval"
    assert selected["not_before"] == ru["not_before"] == planned
    with store.connection() as c:
        assert len(store.list_items(c, "candidate")) == 4


def test_production_scope_rejects_unrequested_languages_before_model_work():
    prepare_accounts()
    scope = brief(targets=[{"account_id": "telegram", "languages": ["ru"], "primary_language": "uz", "format": "post"}])
    with pytest.raises(ValueError):
        agents.start(OWNER, kind="content", message="Invalid scope", evidence_ids=["decision"], production=scope)


def test_completion_recovery_does_not_reset_an_existing_manual_approval():
    from marketing import production
    prepare_accounts(mode="manual")
    task = agents.start(OWNER, kind="content", message="Восстановить после остановки", evidence_ids=["decision"], production=brief(mode="account"))
    run_team(ProductionModel())
    with store.connection(write=True) as c:
        saved = store.get(c, "task", task["id"])
        candidate = next(item for item in store.list_items(c, "candidate") if item["account_id"] == "telegram")
        store.put(c, "task", {**saved, "candidate_ids": []}, actor=OWNER, action="simulate_lost_materialization_link", expected_version=saved["version"])
    approved = content.approve_candidate(OWNER, candidate["id"], candidate["version"])
    assert production.recover_completed(NOW)
    with store.connection() as c:
        recovered = store.get(c, "candidate", candidate["id"])
        assert recovered["approval"] == approved["approval"] and recovered["version"] == approved["version"]
        assert len(store.list_items(c, "candidate")) == 4


@pytest.mark.parametrize("kind,steps", [("content", 7), ("draft", 3)])
def test_quality_waits_for_a_real_image_and_then_sees_its_manifest(kind, steps):
    from marketing import media
    account("instagram", platform="instagram", formats=["image"], mode="automatic", instagram_link_ready=True)
    evidence()
    scope = brief(mode="account", targets=[{"account_id": "instagram", "languages": ["ru"], "primary_language": "ru", "format": "image"}])
    task = agents.start(OWNER, kind=kind, message="Карточка для Instagram", evidence_ids=["decision"], production=scope)
    model = ProductionModel()
    run_team(model, count=steps)
    assert not agents.run_one(model, NOW)
    with store.connection() as c:
        assert store.get(c, "task", task["id"])["status"] == "waiting_assets"
        assert store.list_items(c, "candidate") == []
    assert media.run_one(NOW)
    assert agents.run_one(model, NOW)
    assert model.calls[-1][1]["assets"][0]["sha256"]
    with store.connection() as c:
        item = store.list_items(c, "candidate")[0]
        assert item["status"] == "ready"
        assert media.valid_asset(store.get(c, "asset", item["assets"][0]["id"]))

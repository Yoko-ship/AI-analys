"""A digest binds each visible item to one independently confirmed event."""
import pytest
import json
from datetime import timedelta

from marketing import content, publishing, sources, store
from test_marketing_core import OWNER, NOW, account, candidate, isolated  # noqa: F401
from test_marketing_sources import article, source_input
from test_marketing_production import ProductionModel, brief, run_team


def originals(now=NOW, count=2, age_hours=1):
    source = sources.save_source(OWNER, "digest-news", source_input(method="manual"), 0)
    values = [
        article("hmkb", canonical_event_id="hmkb-approved", title="HMKB · дивиденды утверждены",
                published_at=(now - timedelta(hours=age_hours)).isoformat(), event_at=(now - timedelta(hours=age_hours + 1)).isoformat(),
                excerpt="Утверждено 120 сум на простую акцию.",
                data={"dividend": 120, "dividend_state": "approved", "share_class": "ordinary"},
                destination_url="https://uzstock.uz/news/hmkb-approved"),
        article("uztl", canonical_event_id="uztl-paid", entity="UZTL", publisher="UZTL",
                title="UZTL · дивиденды выплачены", url="https://openinfo.uz/facts/456",
                published_at=(now - timedelta(hours=age_hours)).isoformat(), event_at=(now - timedelta(hours=age_hours + 2)).isoformat(),
                excerpt="Выплачено 45 сум на привилегированную акцию.",
                data={"dividend": 45, "dividend_state": "paid", "share_class": "preferred"},
                destination_url="https://uzstock.uz/news/uztl-paid"),
    ]
    for index in range(2, count):
        values.append({**values[index % 2], "source_item_id": f"decision-{index}", "canonical_event_id": f"decision-{index}",
                       "url": f"https://openinfo.uz/facts/decision-{index}", "destination_url": f"https://uzstock.uz/news/decision-{index}"})
    values = values[:count]
    sources.import_materials(OWNER, source["id"], values, now)
    with store.connection() as c:
        records = [store.get(c, "evidence", store.digest([source["id"], row["source_item_id"]])) for row in values]
    return [sources.verify_evidence(OWNER, row["id"], row["version"], "Сверено с оригиналом решения") for row in records]


def material(rows, *, first="Утверждено 120 сум на простую акцию.", second="Выплачено 45 сум на привилегированную акцию.", **changes):
    return candidate("digest-2026-11-23", rubric="digest", entity="", title="Дивидендные решения и выплаты",
        body="Общий черновик заменяется проверяемыми пунктами.", evidence_ids=[row["id"] for row in rows],
        destination_url=rows[0]["destination_url"],
        claims=[{"evidence_id": row["id"], "field": field, "value": value, "unit": row["units"].get(field, "")}
                for row in rows for field, value in row["data"].items()],
        digest_items=[{"evidence_ids": [row["id"]], "text": text} for row, text in zip(rows, (first, second))], **changes)


def test_digest_preserves_each_events_date_issuer_original_and_site_link():
    account(rubrics=["digest"])
    rows = originals()
    item = material(rows)
    assert "Общий черновик" not in item["body"]
    assert item["body"].count("23.11.2026") >= 2
    for row in rows:
        assert row["entity"] in item["body"] and row["url"] in item["body"] and row["destination_url"] in item["body"]
    checked = content.check_candidate(item["id"], NOW)
    assert checked["status"] == "ready", checked["check"]
    assert publishing.text(checked, {row["id"]: row for row in rows}).count("https://openinfo.uz/facts/456") == 1
    with store.connection() as c:
        assert store.list_items(c, "delivery") == []


@pytest.mark.parametrize("wrong", ["Выплачено 120 сум на простую акцию.",
                                  "Утверждено 45 сум на простую акцию.",
                                  "Утверждено 120 сум на привилегированную акцию."])
def test_another_digest_item_cannot_justify_wrong_status_amount_or_class(wrong):
    account(rubrics=["digest"])
    item = material(originals(), first=wrong)
    checked = content.check_candidate(item["id"], NOW)
    assert checked["status"] == "skipped" and not checked["check"]["passed"]


def test_owner_digest_edits_rebuild_visible_copy_and_invalidate_manual_approval():
    account(rubrics=["digest"], mode="manual")
    item = material(originals(), mode="manual")
    checked = content.check_candidate(item["id"], NOW)
    approved = content.approve_candidate(OWNER, item["id"], checked["version"])
    entries = [{**entry} for entry in approved["digest_items"]]
    entries[0]["text"] = "Выплачено 120 сум на простую акцию."
    changed = content.revise_candidate(OWNER, item["id"], {"digest_items": entries}, approved["version"])
    assert changed["approval"] is None and changed["check"] is None
    assert entries[0]["text"] in changed["body"]
    assert content.check_candidate(item["id"], NOW)["status"] == "needs_revision"


def test_a_digest_headline_cannot_borrow_one_items_payment_status_for_another_issuer():
    account(rubrics=["digest"])
    item = material(originals())
    changed = content.revise_candidate(OWNER, item["id"], {"title": "HMKB выплатил 120 сум на простую акцию"}, item["version"])
    checked = content.check_candidate(changed["id"], NOW)
    assert checked["status"] == "skipped" and "headline" in checked["check"]["reason"]


class DigestModel(ProductionModel):
    def __init__(self, *, omit_last=False):
        super().__init__()
        self.omit_last = omit_last

    def complete_json(self, system, user, **options):
        result = super().complete_json(system, user, **options)
        context = json.loads(user)
        for draft in result.get("drafts", []):
            rows = sorted(context["evidence"], key=lambda row: row["entity"])
            if self.omit_last:
                rows = rows[:-1]
            draft.update(title="Дивидендные решения и выплаты", body="Черновик до сборки пунктов",
                evidence_ids=[row["id"] for row in rows], destination_url=context["production"]["destination_url"] or rows[0]["destination_url"],
                claims=[{"evidence_id": row["id"], "field": field, "value": value, "unit": row["units"].get(field, "")}
                        for row in rows for field, value in row["data"].items()],
                digest_items=[{"evidence_ids": [row["id"]], "text": row["excerpt"]} for row in rows])
        return result


def test_quality_reviews_the_assembled_digest_before_the_same_copy_becomes_a_candidate():
    from marketing import agents
    account(rubrics=["digest"])
    rows = originals()
    scope = brief(rubric="digest", entity="", destination_url=rows[0]["destination_url"], mode="account",
                  targets=[{"account_id": "tg", "languages": ["ru"], "primary_language": "ru", "format": "post"}])
    agents.start(OWNER, kind="content", message="Два разных подтверждённых решения", evidence_ids=[row["id"] for row in rows], production=scope)
    model = DigestModel()
    run_team(model)
    with store.connection() as c:
        item, = store.list_items(c, "candidate")
        variant, = store.list_items(c, "draft_variant")
    assert item["status"] == "ready", item["check"]
    assert item["digest_items"] == variant["digest_items"]
    quality = model.calls[-1][1]
    assert quality["drafts"][0]["body"] == item["body"] == variant["body"]
    assert "Черновик до сборки" not in item["body"]


def test_assembled_digest_cannot_bypass_the_content_length_limit():
    from marketing.errors import MarketingError
    account(rubrics=["digest"])
    rows = originals(count=8)
    with pytest.raises(MarketingError, match="shorter digest"):
        candidate("oversized-digest", rubric="digest", entity="", body="Short placeholder", claims=[],
                  evidence_ids=[row["id"] for row in rows], destination_url=rows[0]["destination_url"],
                  digest_items=[{"evidence_ids": [row["id"]], "text": "Контекст. " * 290} for row in rows])
    with store.connection() as c:
        assert store.list_items(c, "candidate") == []

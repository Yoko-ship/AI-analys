from datetime import timedelta

import pytest

from marketing import sources, store
from marketing.errors import MarketingError
from test_marketing_core import OWNER, NOW, isolated  # noqa: F401


def source_input(**changes):
    return {"name": "Internal confirmed news", "url": "https://uzstock.uz/news", "category": "uzstock",
            "method": "internal_news", "language": "ru", "owner": "owner", "geography": "UZ",
            "topics": ["issuers"], "frequency_minutes": 60, "stale_after_hours": 24,
            "rights": "link_and_excerpt", "terms_checked_on": "2026-11-23", "may_store": True,
            "may_display": True, "commercial_use": True, **changes}


def article(key="original", **changes):
    return {"source_item_id": key, "canonical_event_id": "issuer-decision-123", "title": "Dividend approved",
            "url": "https://openinfo.uz/facts/123", "publisher": "Issuer", "entity": "HMKB",
            "published_at": "2026-11-23T06:00:00Z", "event_at": "2026-11-22T08:00:00Z",
            "excerpt": "Approved dividend 120 UZS per ordinary share", "data": {"dividend": 120},
            "units": {"dividend": "UZS/share"}, "rights": "link_and_excerpt", **changes}


def test_source_registry_never_claims_connection_before_successful_collection():
    src = sources.save_source(OWNER, "news", source_input(), 0)
    assert src["status"] == "candidate" and src["last_success_at"] is None
    enabled = sources.enable_source(OWNER, src["id"], src["version"])
    assert enabled["status"] == "reviewing"
    sources.collect_one(lambda source: [article()], NOW)
    with store.connection() as c:
        saved = store.get(c, "source", "news")
        assert saved["status"] == "connected" and saved["last_success_at"] == NOW.isoformat()
        assert len(store.list_items(c, "evidence")) == 1


def test_failed_source_does_not_become_no_news_and_does_not_block_other_sources():
    for name in ("bad", "good"):
        src = sources.save_source(OWNER, name, source_input(), 0)
        sources.enable_source(OWNER, name, src["version"])
    def fetch(src):
        if src["id"] == "bad":
            raise RuntimeError("private connection detail")
        return [article()]
    for _ in range(2):
        sources.collect_one(fetch, NOW)
    with store.connection() as c:
        bad = store.get(c, "source", "bad")
        assert bad["status"] == "unavailable" and bad["last_success_at"] is None
        assert "private" not in str(bad)
        assert store.get(c, "source", "good")["status"] == "connected"


def test_reprints_group_by_event_and_changed_original_creates_evidence_revision():
    src = sources.save_source(OWNER, "news", source_input(), 0)
    sources.enable_source(OWNER, "news", src["version"])
    sources.collect_one(lambda source: [article(), article("reprint", publisher="Business media", url="https://example.test/reprint")], NOW)
    with store.connection() as c:
        topics = store.list_items(c, "topic")
        assert len(topics) == 1
        assert topics[0]["classification"] == "new_event"
        assert topics[0]["independent_events"] == 1
    sources.collect_one(lambda source: [article(excerpt="Correction: approved 100 UZS", data={"dividend": 100})], NOW + timedelta(hours=2))
    with store.connection() as c:
        evidence = [e for e in store.list_items(c, "evidence") if e["url"] == "https://openinfo.uz/facts/123"][0]
        assert evidence["version"] == 2
        assert len(store.history(c, "evidence", evidence["id"])) == 2


def test_source_configuration_requires_rights_before_monitoring():
    src = sources.save_source(OWNER, "unreviewed", source_input(rights="unknown", terms_checked_on=None), 0)
    with pytest.raises(MarketingError):
        sources.enable_source(OWNER, src["id"], src["version"])


def test_repeated_unchanged_observation_does_not_invalidate_evidence_version():
    src = sources.save_source(OWNER, "news", source_input(), 0)
    sources.enable_source(OWNER, "news", src["version"])
    sources.collect_one(lambda source: [article()], NOW)
    sources.collect_one(lambda source: [article()], NOW + timedelta(hours=2))
    with store.connection() as c:
        assert store.list_items(c, "evidence")[0]["version"] == 1


def test_storage_permission_is_required_before_fetching_and_revocation_blocks_release():
    src = sources.save_source(OWNER, "no-storage", source_input(may_store=False), 0)
    with pytest.raises(MarketingError, match="storage"):
        sources.enable_source(OWNER, src["id"], src["version"])
    src = sources.save_source(OWNER, "news", source_input(), 0)
    enabled = sources.enable_source(OWNER, src["id"], src["version"])
    sources.collect_one(lambda source: [article()], NOW)
    with store.connection() as c:
        evidence = store.list_items(c, "evidence")[0]
        current = store.get(c, "source", src["id"])
    sources.enable_source(OWNER, src["id"], current["version"], enabled=False)
    with store.connection() as c:
        assert sources.current_evidence(c, evidence["id"])["status"] == "disabled"


def test_manual_import_and_verification_preserve_original_and_reject_missing_reason():
    src = sources.save_source(OWNER, "upload", source_input(method="manual", category="manual"), 0)
    imported = sources.import_materials(OWNER, src["id"], [article()], NOW)
    assert imported["count"] == 1
    with store.connection() as c:
        item = store.list_items(c, "evidence")[0]
    with pytest.raises(MarketingError):
        sources.verify_evidence(OWNER, item["id"], item["version"], "")
    verified = sources.verify_evidence(OWNER, item["id"], item["version"], "Compared with the original issuer decision")
    assert verified["status"] == "verified" and verified["excerpt"] == article()["excerpt"]
    with store.connection() as c:
        assert len(store.history(c, "evidence", item["id"])) == 2


def test_source_reconfiguration_invalidates_evidence_until_recollected_and_cannot_overgrant_rights():
    src = sources.save_source(OWNER, "news", source_input(), 0)
    sources.enable_source(OWNER, "news", src["version"])
    sources.collect_one(lambda source: [article()], NOW)
    with store.connection() as c:
        src = store.get(c, "source", "news")
        ev = store.list_items(c, "evidence")[0]
    sources.save_source(OWNER, "news", source_input(url="https://different.test/feed"), src["version"])
    with store.connection() as c:
        assert sources.current_evidence(c, ev["id"])["status"] == "unavailable"
    with pytest.raises(MarketingError, match="rights"):
        sources.import_materials(OWNER, "news", [article(rights="owned")], NOW)


def test_headline_only_permission_never_stores_the_full_extract_or_claims():
    source = sources.save_source(OWNER, "headlines", source_input(method="manual", data_type="headline"), 0)
    sources.import_materials(OWNER, source["id"], [article(excerpt="Not licensed to retain this full paragraph")], NOW)
    with store.connection() as c:
        saved = store.list_items(c, "evidence")[0]
        assert saved["excerpt"] == article()["title"]
        assert saved["data"] == {} and saved["units"] == {}


def test_excerpt_permission_cannot_enable_full_document_storage():
    source = sources.save_source(OWNER, "full", source_input(data_type="full"), 0)
    with pytest.raises(MarketingError, match="full"):
        sources.enable_source(OWNER, source["id"], source["version"])
    with pytest.raises(MarketingError, match="full"):
        sources.import_materials(OWNER, source["id"], [article()], NOW)

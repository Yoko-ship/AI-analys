"""Dated, deduplicated theme observations; growth needs reviewed comparable history."""
from datetime import timedelta

import pytest

from marketing import sources, store
from marketing.errors import MarketingError
from test_marketing_core import OWNER, NOW, isolated  # noqa: F401
from test_marketing_sources import article, source_input


def setup_source(key="news"):
    sources.save_source(OWNER, key, source_input(method="manual"), 0)


def material(key, day, **changes):
    return article(key, canonical_event_id=key, themes=["Dividends"],
                   url=f"https://example.test/{key}", published_at=f"2026-11-{day:02}T06:00:00Z",
                   event_at=None, **changes)


def import_items(*items, source="news"):
    sources.import_materials(OWNER, source, list(items), NOW)


def review(**changes):
    return {"theme": " dividends ", "source_ids": ["news"], "starts_on": "2026-11-16",
            "ends_on": "2026-11-23", "complete": True, "review_reason": "Compared both full exports and merged reprints",
            "audience_relevance": "Investors compare issuer decisions", "risk": "A decision is not a payment",
            "proposed_format": "Explainer with original links", **changes}


def save(**changes):
    from marketing import trends
    return trends.save(OWNER, "dividends", review(**changes), 0, NOW)


def current():
    from marketing import trends
    with store.connection() as c:
        return trends.current(c, store.get(c, "trend", "dividends"), NOW)


def test_growth_uses_equal_closed_windows_and_counts_reprints_once_across_sources():
    setup_source()
    setup_source("syndicated")
    import_items(material("old", 10), material("new-a", 17), material("new-b", 22))
    import_items({**material("copy", 18), "canonical_event_id": "old"}, source="syndicated")
    saved = save(source_ids=["news", "syndicated"])
    assert saved["classification"] == "measured_growth"
    assert saved["baseline"]["mentions"] == 1 and saved["current"]["mentions"] == 2
    assert saved["baseline"]["starts_on"] == "2026-11-09"
    assert saved["growth"] == {"absolute": 1, "percent": 100.0}
    assert saved["baseline"]["source_ids"] == ["news"]
    assert saved["current"]["source_ids"] == ["news"]
    assert len(saved["basis"]["evidence"]) == 4
    assert saved["review_status"] == "current"


def test_incomplete_history_can_only_claim_observed_recurring_theme():
    setup_source()
    import_items(material("old", 10), material("a", 17), material("b", 22))
    saved = save(complete=False, review_reason="One feed may be truncated")
    assert saved["classification"] == "recurring_theme"
    assert saved["growth"] is None
    assert saved["current"]["mentions"] == 2


@pytest.mark.parametrize("baseline,current_count,classification,change,percent", [
    (0, 2, "measured_growth", 2, None),
    (2, 2, "recurring_theme", 0, 0.0),
    (2, 1, "new_event", -1, -50.0),
    (1, 0, "editorial_hypothesis", -1, -100.0),
])
def test_zero_baseline_flat_and_declining_counts_are_not_invented_growth(baseline, current_count, classification, change, percent):
    setup_source()
    items = [material(f"old-{i}", 10) for i in range(baseline)] + [material(f"new-{i}", 22) for i in range(current_count)]
    import_items(*items)
    saved = save()
    assert saved["classification"] == classification
    assert saved["growth"] == {"absolute": change, "percent": percent}


def test_same_original_url_with_different_event_keys_does_not_inflate_mentions():
    setup_source()
    import_items(material("a", 17), {**material("b", 18), "url": "https://example.test/a#copy"})
    assert save(complete=False)["current"]["mentions"] == 1


def test_untagged_earlier_original_still_prevents_tagged_reprint_becoming_a_new_event():
    setup_source()
    import_items({**material("original", 1), "themes": []},
                 {**material("copy", 18), "canonical_event_id": "original"})
    saved = save(complete=False)
    assert saved["current"]["mentions"] == 0
    assert len(saved["basis"]["evidence"]) == 2


def test_one_old_mention_in_long_window_is_a_hypothesis_not_a_fresh_event():
    setup_source()
    import_items(material("old", 1))
    assert save(starts_on="2026-11-01", complete=False)["classification"] == "editorial_hypothesis"


def test_tashkent_half_open_boundaries_and_unrelated_theme_are_excluded():
    setup_source()
    import_items({**material("before", 15), "published_at": "2026-11-15T18:59:59Z"},
                 {**material("start", 15), "published_at": "2026-11-15T19:00:00Z"},
                 {**material("end", 22), "published_at": "2026-11-22T19:00:00Z"},
                 {**material("unrelated", 18), "themes": ["Trading"]})
    saved = save()
    assert saved["baseline"]["mentions"] == 1
    assert saved["current"]["mentions"] == 1
    assert len(saved["basis"]["evidence"]) == 2


def test_freshness_compares_instants_across_original_time_zone_offsets():
    setup_source()
    import_items({**material("earlier", 22), "published_at": "2026-11-22T01:00:00+05:00"},
                 {**material("later", 21), "published_at": "2026-11-21T23:30:00-05:00"})
    assert save()["current"]["latest_published_at"] == "2026-11-21T23:30:00-05:00"


@pytest.mark.parametrize("change", ["late", "amended", "permission", "configuration"])
def test_late_original_correction_or_changed_source_invalidates_frozen_review(change):
    setup_source()
    import_items(material("old", 10), material("a", 17), material("b", 22))
    original = save()
    if change == "late":
        import_items(material("missed", 11))
    elif change == "amended":
        import_items({**material("a", 17), "canonical_event_id": "old"})
    else:
        with store.connection() as c:
            src = store.get(c, "source", "news")
        if change == "permission":
            sources.enable_source(OWNER, "news", src["version"], False)
        else:
            sources.save_source(OWNER, "news", source_input(method="manual", topics=["changed"]), src["version"])
    value = current()
    assert value["review_status"] == "stale" and value["growth"] is None
    assert value["classification"] != "measured_growth"
    with store.connection() as c:
        assert store.revision(c, "trend", "dividends", 1) == original


def test_unrelated_later_material_and_expired_release_freshness_do_not_rewrite_history():
    from marketing import trends
    setup_source()
    import_items(material("old", 10), material("a", 17), material("b", 22))
    saved = save()
    import_items({**material("other", 18), "themes": ["Other"]}, material("later", 23))
    with store.connection() as c:
        assert trends.current(c, saved, NOW + timedelta(days=30))["growth"] == saved["growth"]


def test_plain_evidence_in_registered_source_and_replaced_import_do_not_break_workspace():
    from marketing import content
    from test_marketing_core import evidence
    setup_source()
    import_items(material("old", 10), material("a", 17), material("b", 22))
    save()
    plain = evidence("plain", source_id="news", url="https://example.test/unrelated", published_at="2026-11-10T00:00:00Z")
    assert current()["review_status"] == "current"
    with store.connection() as c:
        imported = next(item for item in store.list_items(c, "evidence") if item.get("canonical_event_id") == "a")
    replacement = {key: value for key, value in plain.items() if key not in {"id", "version", "updated_at"}}
    content.save_evidence(OWNER, imported["id"], replacement, imported["version"])
    assert current()["review_status"] == "stale"


def test_owner_must_explicitly_review_completeness_and_cannot_compare_future_window():
    from marketing import trends
    setup_source()
    import_items(material("a", 17))
    for changes in ({"review_reason": " "}, {"ends_on": "2026-11-24"}, {"starts_on": "2026-11-23"}):
        with pytest.raises((MarketingError, ValueError)):
            save(**changes)
    with pytest.raises(MarketingError):
        trends.save({"id": "model", "role": "market"}, "dividends", review(), 0, NOW)


def test_unavailable_source_cannot_be_treated_as_an_empty_complete_window():
    setup_source()
    with pytest.raises(MarketingError, match="source"):
        save()


def test_review_again_creates_version_without_changing_original_comparison():
    from marketing import trends
    setup_source()
    import_items(material("old", 10), material("a", 17), material("b", 22))
    save()
    import_items(material("missed", 11))
    revised = trends.save(OWNER, "dividends", review(), 1, NOW)
    assert revised["growth"]["absolute"] == 0
    with store.connection() as c:
        assert store.revision(c, "trend", "dividends", 1)["growth"]["absolute"] == 1
        assert len(store.history(c, "trend", "dividends")) == 2


def test_team_receives_selected_dated_counts_and_stops_if_inventory_changes_during_reasoning():
    from marketing import agents
    from test_marketing_agents import Model, output
    setup_source()
    import_items(material("old", 10), material("a", 17), material("b", 22))
    save()
    task = agents.start(OWNER, kind="dialogue", message="Interpret this source population", trend_ids=["dividends"])
    model = Model([output("Interest in this selected source population increased")])
    agents.run_one(model, NOW)
    context = model.calls[0][1]["trend_observations"][0]
    assert context["growth"]["percent"] == 100 and context["starts_on"] == "2026-11-16"
    assert context["version"] == 1 and context["source_ids"] == ["news"]
    with store.connection() as c:
        assert store.get(c, "task", task["id"])["outputs"][0]["trend_versions"] == {"dividends": 1}
    task = agents.start(OWNER, kind="dialogue", message="Review it again", trend_ids=["dividends"])

    class ChangingModel(Model):
        def complete_json(self, *args, **kwargs):
            import_items(material("missed", 11))
            return super().complete_json(*args, **kwargs)

    agents.run_one(ChangingModel([output("Unsupported old growth claim")]), NOW)
    with store.connection() as c:
        saved = store.get(c, "task", task["id"])
        assert saved["status"] == "blocked" and not saved["outputs"]
    with pytest.raises(MarketingError):
        agents.retry(OWNER, saved["id"], saved["version"])
    with pytest.raises(MarketingError):
        agents.start(OWNER, kind="dialogue", message="Do not pass stale growth", trend_ids=["dividends"])
    from marketing import trends
    trends.save(OWNER, "dividends", review(), 1, NOW)
    queued = agents.start(OWNER, kind="dialogue", message="Keep the selected revision", trend_ids=["dividends"])
    trends.save(OWNER, "dividends", review(), 2, NOW)
    unused = Model([])
    agents.run_one(unused, NOW)
    assert unused.calls == []
    with store.connection() as c:
        saved = store.get(c, "task", queued["id"])
        assert saved["status"] == "blocked" and "Selected theme observations changed" in saved["reason"]


def test_role_acceptance_uses_completion_time_for_materials_arriving_during_model_call(monkeypatch):
    from marketing import agents
    from test_marketing_agents import Model, output
    setup_source()
    import_items(material("old", 10), material("a", 17), material("b", 22))
    save()
    task = agents.start(OWNER, kind="dialogue", message="Use this dated comparison", trend_ids=["dividends"])
    finished = NOW + timedelta(minutes=1)

    class Clock:
        @staticmethod
        def now(tz):
            return finished

    class ModelWithArrival(Model):
        def complete_json(self, *args, **kwargs):
            sources.import_materials(OWNER, "news", [material("late", 11)], finished)
            return super().complete_json(*args, **kwargs)

    monkeypatch.setattr(agents, "datetime", Clock)
    agents.run_one(ModelWithArrival([output("The earlier growth is no longer valid")]), NOW)
    with store.connection() as c:
        saved = store.get(c, "task", task["id"])
        assert saved["status"] == "blocked" and not saved["outputs"]
